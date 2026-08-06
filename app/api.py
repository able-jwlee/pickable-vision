from datetime import datetime
from pathlib import Path

import numpy as np
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app import config
from app.annotate import draw_for_response, draw_pick_targets, save_annotated
from app.blob_detector import detect_blobs, dish_pick_region
from app.detector import detect, pick_region
from app.image_io import (
    decode_base64_image,
    encode_jpeg_base64,
    encode_png_base64,
    read_image_file,
)
from app.models import Colony, DetectRequest, DetectResponse, PreviewResponse
from app.param_mapping import (
    edge_to_margin_px,
    max_size_to_area,
    min_size_to_area,
    sensitivity_to_min_t,
    sensitivity_to_offset,
)
from app.scoring import score_colonies

router = APIRouter()


def _load_image(req: DetectRequest) -> np.ndarray:
    """image_path가 있으면 로컬 파일에서, 없으면 base64에서 이미지를 읽는다."""
    try:
        if req.image_path:
            return read_image_file(req.image_path)
        return decode_base64_image(req.image)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/image")
def serve_image(path: str) -> FileResponse:
    """원본 이미지를 그대로 돌려준다 (오퍼레이터 UI 표시용).

    좌표만 받아 클라이언트가 오버레이를 그리려면 **클라이언트도 원본 이미지를
    가져야 한다.** 지금까지는 UI 를 file:// 로 열어 상대경로로 읽었지만, 서버를
    배포하면 그 방법이 깨진다. 이 엔드포인트가 그 간극을 메운다.

    `/detect/preview` 와 다르다 — 그쪽은 검출 결과를 그려 넣은 이미지를 base64 로
    주고, 이쪽은 표시 대상인 **원본**을 바이트 그대로 준다.

    경로는 서버 실행 디렉터리 안으로 제한한다. `/detect` 의 `image_path` 는 로컬
    튜닝 편의용이라 제약이 없지만, 그쪽은 파일을 **읽어서 검출에 쓸 뿐**이고
    이쪽은 **내용을 그대로 반환**하므로 노출 성격이 다르다. 확장자도 이미지로
    제한해 설정 파일 등이 새어 나가지 않게 한다.
    """
    root = Path.cwd().resolve()
    try:
        target = (root / path).resolve()
    except (OSError, ValueError):
        raise HTTPException(status_code=400, detail="invalid path")
    if not target.is_relative_to(root):
        raise HTTPException(status_code=403, detail="path outside server root")
    if target.suffix.lower() not in {".jpg", ".jpeg", ".png", ".bmp", ".tif",
                                     ".tiff", ".webp"}:
        raise HTTPException(status_code=403, detail="not an image file")
    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"not found: {path}")
    return FileResponse(target)


def _resolve_params(req: DetectRequest) -> dict:
    """추상 0~100 필드가 지정되면 raw로 매핑, 아니면 기존 raw/config 유지.

    반환 dict는 응답의 applied_params가 된다.
    """
    threshold_offset = (
        sensitivity_to_offset(req.sensitivity)
        if req.sensitivity is not None else req.threshold_offset
    )
    min_area = (
        min_size_to_area(req.min_size)
        if req.min_size is not None else req.min_area
    )
    max_area = (
        max_size_to_area(req.max_size)
        if req.max_size is not None else req.max_area
    )
    pick_edge_margin = (
        edge_to_margin_px(req.edge_margin)
        if req.edge_margin is not None else config.PICK_EDGE_MARGIN
    )
    # blob 경로의 감도: raw min_t > sensitivity 매핑 > config default 순으로 우선.
    if req.min_t is not None:
        min_t = req.min_t
    elif req.sensitivity is not None:
        min_t = sensitivity_to_min_t(req.sensitivity)
    else:
        min_t = config.BLOB_MIN_T
    return {
        "method": req.method,
        "plate_type": req.plate_type,
        "polarity": req.polarity,
        "min_t": min_t,
        "min_diam_frac": req.min_diam_frac,
        "max_diam_frac": req.max_diam_frac,
        "colour_credit": req.colour_credit,
        "work_size": req.work_size,
        "adaptive_scale": req.adaptive_scale,
        "min_solidity": req.min_solidity,
        "min_roundness": req.min_roundness,
        "watershed_split": req.watershed_split,
        "split_area_ratio": req.split_area_ratio,
        "threshold_offset": threshold_offset,
        "min_area": min_area,
        "max_area": max_area,
        "pick_edge_margin": pick_edge_margin,
        "split_touching": req.split_touching,
        "pick_top_n": req.pick_top_n,
        "pick_radius_min": (config.PICK_RADIUS_MIN if req.pick_radius_min is None
                            else req.pick_radius_min),
        "pick_radius_max": (config.PICK_RADIUS_MAX if req.pick_radius_max is None
                            else req.pick_radius_max),
    }


def _detect_and_score(
    img: np.ndarray, req: DetectRequest, resolved: dict
) -> list[Colony]:
    """검출 → 피킹 적합도 점수화 → Colony 리스트."""
    if resolved["method"] == "blob":
        circles = detect_blobs(
            img,
            min_t=resolved["min_t"],
            plate_type=resolved["plate_type"],
            force_bright={"bright": True, "dark": False}.get(resolved["polarity"]),
            # "auto" 는 접시별 자동 판정, "both" 는 양극성 병합(구동작).
            auto_polarity=(resolved["polarity"] != "both"),
            min_diam_frac=resolved["min_diam_frac"],
            max_diam_frac=resolved["max_diam_frac"],
            colour_credit=resolved["colour_credit"],
            work_size=resolved["work_size"],
            adaptive_scale=resolved["adaptive_scale"],
            min_solidity=resolved["min_solidity"],
            min_roundness=resolved["min_roundness"],
            watershed_split=resolved["watershed_split"],
            split_area_ratio=resolved["split_area_ratio"],
        )
    else:
        circles = detect(
            img,
            min_area=resolved["min_area"],
            max_area=resolved["max_area"],
            min_circularity=req.min_circularity,
            invert=req.invert,
            tophat_kernel=req.tophat_kernel,
            mask_walls=req.mask_walls,
            threshold_offset=resolved["threshold_offset"],
            split_touching=resolved["split_touching"],
        )
    geom = [
        {"x": x, "y": y, "radius": r, "circularity": c}
        for x, y, r, c in circles
    ]
    # 피킹 대상은 경계에서 안전 여백만큼 안쪽만 인정 (테두리 근처 반점 제외).
    # blob 경로는 원형 접시를, tophat 경로는 기존 2×4 웰 격자를 기준으로 삼는다.
    # mask_walls=False는 두 경로 모두에서 "경계 제한 없음"을 뜻한다(하위호환).
    if not req.mask_walls:
        pick_mask = None
    elif resolved["method"] == "blob":
        pick_mask = dish_pick_region(
            img, edge_margin=resolved["pick_edge_margin"]
        )
    elif req.mask_walls:
        pick_mask = pick_region(img, edge_margin=resolved["pick_edge_margin"])
    else:
        pick_mask = None
    scores = score_colonies(
        geom,
        top_n=resolved["pick_top_n"],
        pick_mask=pick_mask,
        radius_min=resolved["pick_radius_min"],
        radius_max=resolved["pick_radius_max"],
    )
    return [
        Colony(
            id=i + 1,
            x=x,
            y=y,
            radius=r,
            circularity=c,
            score=scores[i]["score"],
            pickable=scores[i]["pickable"],
        )
        for i, (x, y, r, c) in enumerate(circles)
    ]


def _output_name(req: DetectRequest) -> str:
    """저장 파일명: <원본stem 또는 detect>_<타임스탬프>.jpg"""
    stem = Path(req.image_path).stem if req.image_path else "detect"
    ts = datetime.now().strftime("%y%m%d-%H%M%S")
    return f"{stem}_{ts}.jpg"


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.post("/detect", response_model=DetectResponse)
def detect_colonies(req: DetectRequest) -> DetectResponse:
    img = _load_image(req)
    height, width = img.shape[:2]
    resolved = _resolve_params(req)
    colonies = _detect_and_score(img, req, resolved)

    annotated_path: str | None = None
    if req.save_annotated:
        annotated = draw_pick_targets(img, colonies, mode=req.annotate)
        saved = save_annotated(annotated, config.OUTPUT_DIR, _output_name(req))
        annotated_path = str(saved.resolve())

    # 좌표와 표시 이미지를 한 응답에 함께 담는다.
    annotated_image: str | None = None
    image_scale = 1.0
    if req.return_image:
        vis, image_scale = draw_for_response(
            img, colonies, mode=req.annotate, max_width=req.image_max_width,
            marker=req.marker,
        )
        annotated_image = (
            encode_png_base64(vis) if req.image_format == "png"
            else encode_jpeg_base64(vis, req.image_quality)
        )

    return DetectResponse(
        width=width,
        height=height,
        count=len(colonies),
        colonies=colonies,
        annotated_path=annotated_path,
        annotated_image=annotated_image,
        annotated_image_scale=image_scale,
        applied_params=resolved,
    )


@router.post("/detect/preview", response_model=PreviewResponse)
def detect_preview(req: DetectRequest) -> PreviewResponse:
    img = _load_image(req)
    resolved = _resolve_params(req)
    colonies = _detect_and_score(img, req, resolved)
    annotated = draw_pick_targets(img, colonies, mode=req.annotate)
    if req.save_annotated:
        save_annotated(annotated, config.OUTPUT_DIR, _output_name(req))
    return PreviewResponse(count=len(colonies), image=encode_png_base64(annotated))
