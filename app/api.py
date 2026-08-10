from datetime import datetime
from pathlib import Path

import numpy as np
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app import config
from app.annotate import draw_for_response, draw_pick_targets, save_annotated
from app.blob_detector import detect_blobs, dish_pick_region
from app.image_io import (
    decode_base64_image,
    encode_jpeg_base64,
    encode_png_base64,
    read_image_file,
)
from app.models import Colony, DetectRequest, DetectResponse, PreviewResponse
from app.param_mapping import edge_to_margin_px, sensitivity_to_min_t
from app.scoring import score_colonies
from app.well_plate import pick_region

router = APIRouter()


def _load_image(req: DetectRequest) -> np.ndarray:
    """image_path가 있으면 로컬 파일에서, 없으면 base64에서 이미지를 읽는다."""
    try:
        if req.image_path:
            return read_image_file(req.image_path)
        return decode_base64_image(req.image)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "/image",
    tags=["image"],
    summary="원본 이미지 바이트",
    response_class=FileResponse,
    responses={
        200: {"content": {"image/*": {}}, "description": "이미지 바이트"},
        400: {"description": "경로 형식 오류"},
        403: {"description": "서버 루트 밖이거나 이미지 확장자가 아님"},
        404: {"description": "파일 없음"},
    },
)
def serve_image(path: str) -> FileResponse:
    """UI 배경으로 깔 **원본 이미지**를 바이트 그대로 돌려준다.

    `POST /detect` 가 좌표만 반환하므로 클라이언트도 원본 이미지를 가져야
    오버레이를 그릴 수 있다. `<img src="/image?path=...">` 로 쓰면 브라우저가
    캐시하므로 감도를 바꿔 재검출해도 이미지는 다시 받지 않는다.

    `path` 는 서버 실행 디렉터리 기준 상대 경로이고, 디렉터리 밖으로 나가거나
    이미지가 아닌 확장자면 403 이다.

    `/detect/preview` 와 다르다 — 그쪽은 검출 결과를 **그려 넣은** 이미지를
    base64 로 주고, 이쪽은 표시 대상인 **원본**을 바이트로 준다.
    """
    # 경로를 서버 실행 디렉터리 안으로 제한한다. `/detect` 의 `image_path` 는
    # 로컬 튜닝 편의용이라 제약이 없지만, 그쪽은 파일을 **읽어서 검출에 쓸 뿐**
    # 이고 이쪽은 **내용을 그대로 반환**하므로 노출 성격이 다르다. 확장자도
    # 이미지로 제한해 설정 파일 등이 새어 나가지 않게 한다.
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
    pick_edge_margin = (
        edge_to_margin_px(req.edge_margin)
        if req.edge_margin is not None else config.PICK_EDGE_MARGIN
    )
    # 감도: raw min_t > sensitivity 매핑 > config default 순으로 우선.
    if req.min_t is not None:
        min_t = req.min_t
    elif req.sensitivity is not None:
        min_t = sensitivity_to_min_t(req.sensitivity)
    else:
        min_t = config.BLOB_MIN_T
    return {
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
        "candidate_source": req.candidate_source,
        "threshold_levels": req.threshold_levels,
        "min_circularity": req.min_circularity,
        "min_fill": req.min_fill,
        "watershed_split": req.watershed_split,
        "split_area_ratio": req.split_area_ratio,
        "pick_edge_margin": pick_edge_margin,
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
        candidate_source=resolved["candidate_source"],
        threshold_levels=resolved["threshold_levels"],
        min_circularity=resolved["min_circularity"],
        min_fill=resolved["min_fill"],
    )
    geom = [
        {"x": x, "y": y, "radius": r, "circularity": c}
        for x, y, r, c in circles
    ]
    # 피킹 대상은 경계에서 안전 여백만큼 안쪽만 인정 (테두리 근처 반점 제외).
    # petri 는 접시 원을, well8 은 4×2 격자를 기준으로 삼는다.
    # mask_walls=False 는 "경계 제한 없음"을 뜻한다.
    if not req.mask_walls:
        pick_mask = None
    elif resolved["plate_type"] == "well8":
        pick_mask = pick_region(img, edge_margin=resolved["pick_edge_margin"])
    else:
        pick_mask = dish_pick_region(
            img, edge_margin=resolved["pick_edge_margin"]
        )
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


@router.get("/health", tags=["ops"], summary="헬스체크")
def health() -> dict:
    """서버가 살아 있는지만 확인한다. `{"status": "ok"}`."""
    return {"status": "ok"}


@router.post(
    "/detect",
    response_model=DetectResponse,
    tags=["detect"],
    summary="콜로니 검출 → 좌표",
    responses={
        400: {"description": "이미지 디코딩 실패 또는 입력 누락"},
        422: {"description": "파라미터 범위 위반"},
    },
)
def detect_colonies(req: DetectRequest) -> DetectResponse:
    """이미지에서 콜로니를 검출해 **원본 픽셀 좌표**를 반환한다.

    프론트엔드가 쓰는 주 엔드포인트다. 응답은 좌표만 담아 4000px 이미지에서도
    약 3.9KB 이고, 배경 이미지는 `GET /image` 로 따로 받아 브라우저가 캐시한다.

    좌표는 `work_size` 로 축소해 처리하더라도 **원본 픽셀로 되돌려 준다.**

    보낼 값은 보통 `sensitivity`(0~100) 하나다. 서버가 적용한 raw 값은
    `applied_params` 로 되돌아오므로 UI 는 그것을 표시하면 된다 —
    **매핑식을 클라이언트에서 재계산하지 말 것.**

    `pickable` 은 로봇이 안전하게 집을 수 있는 후보인지이고, `score` 는 그
    랭킹이다. 둘 다 **검출 신뢰도가 아니다.**
    """
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


@router.post(
    "/detect/preview",
    response_model=PreviewResponse,
    tags=["detect"],
    summary="콜로니 검출 → 표시 이미지 (좌표 없음)",
    responses={
        400: {"description": "이미지 디코딩 실패 또는 입력 누락"},
        422: {"description": "파라미터 범위 위반"},
    },
)
def detect_preview(req: DetectRequest) -> PreviewResponse:
    """검출 결과를 **그려 넣은 이미지**만 반환한다. 좌표는 담기지 않는다.

    파라미터를 눈으로 튜닝할 때 쓰는 개발용 엔드포인트다.
    **웹 UI 는 `POST /detect` + `GET /image` 를 쓸 것** — 그쪽이 67배 작고
    확대해도 마커가 뭉개지지 않는다.

    좌표와 이미지를 한 번에 받아야 하면 `POST /detect` 에
    `return_image: true` 를 주면 된다.
    """
    img = _load_image(req)
    resolved = _resolve_params(req)
    colonies = _detect_and_score(img, req, resolved)
    annotated = draw_pick_targets(img, colonies, mode=req.annotate)
    if req.save_annotated:
        save_annotated(annotated, config.OUTPUT_DIR, _output_name(req))
    return PreviewResponse(count=len(colonies), image=encode_png_base64(annotated))
