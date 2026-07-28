from datetime import datetime
from pathlib import Path

import numpy as np
from fastapi import APIRouter, HTTPException

from app import config
from app.annotate import draw_pick_targets, save_annotated
from app.detector import detect, pick_region
from app.image_io import decode_base64_image, encode_png_base64, read_image_file
from app.models import Colony, DetectRequest, DetectResponse, PreviewResponse
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


def _detect_and_score(img: np.ndarray, req: DetectRequest) -> list[Colony]:
    """검출 → 피킹 적합도 점수화 → Colony 리스트."""
    circles = detect(
        img,
        min_area=req.min_area,
        max_area=req.max_area,
        min_circularity=req.min_circularity,
        invert=req.invert,
        tophat_kernel=req.tophat_kernel,
        mask_walls=req.mask_walls,
        threshold_offset=req.threshold_offset,
        split_touching=req.split_touching,
    )
    geom = [
        {"x": x, "y": y, "radius": r, "circularity": c}
        for x, y, r, c in circles
    ]
    # 피킹 대상은 웰 경계에서 안전 여백만큼 안쪽만 인정 (벽 근처 반점 제외).
    pick_mask = (
        pick_region(img, edge_margin=config.PICK_EDGE_MARGIN)
        if req.mask_walls
        else None
    )
    scores = score_colonies(geom, top_n=req.pick_top_n, pick_mask=pick_mask)
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
    colonies = _detect_and_score(img, req)

    annotated_path: str | None = None
    if req.save_annotated:
        annotated = draw_pick_targets(img, colonies, mode=req.annotate)
        saved = save_annotated(annotated, config.OUTPUT_DIR, _output_name(req))
        annotated_path = str(saved.resolve())

    return DetectResponse(
        width=width,
        height=height,
        count=len(colonies),
        colonies=colonies,
        annotated_path=annotated_path,
        applied_params={
            "threshold_offset": req.threshold_offset,
            "min_area": req.min_area,
            "max_area": req.max_area,
            "pick_edge_margin": config.PICK_EDGE_MARGIN,
            "split_touching": req.split_touching,
            "pick_top_n": req.pick_top_n,
        },
    )


@router.post("/detect/preview", response_model=PreviewResponse)
def detect_preview(req: DetectRequest) -> PreviewResponse:
    img = _load_image(req)
    colonies = _detect_and_score(img, req)
    annotated = draw_pick_targets(img, colonies, mode=req.annotate)
    if req.save_annotated:
        save_annotated(annotated, config.OUTPUT_DIR, _output_name(req))
    return PreviewResponse(count=len(colonies), image=encode_png_base64(annotated))
