"""색 축 파라미터 — min_rel_sat.

|내부채도 - 주변채도| 하한이다. 점자식 인쇄 잉크·데브리는 이 값이 -0.1~+1.7 이고
콜로니는 7~57 이라 판별력이 크다. blob_detector 는 처음부터 이 인자를 받았지만
DetectRequest 에 없어서 호출자가 쓸 수 없었다.
"""
import glob

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.blob_detector import detect_blobs
from main import app

client = TestClient(app)

SAMPLES = sorted(glob.glob("sample/lower-resolution/*.jpg"))
pytestmark = pytest.mark.skipif(
    not SAMPLES, reason="sample/ 이미지가 없으면 건너뜀 (저장소에 커밋되지 않음)"
)


def _detect(**kw):
    resp = client.post("/detect", json={"image_path": SAMPLES[0], **kw})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _count(**kw):
    return _detect(**kw)["count"]


def test_min_rel_sat_default_matches_config():
    from app import config
    assert _detect()["applied_params"]["min_rel_sat"] == pytest.approx(
        config.BLOB_MIN_REL_SAT
    )


def test_min_rel_sat_is_echoed():
    assert _detect(min_rel_sat=6.0)["applied_params"]["min_rel_sat"] == pytest.approx(6.0)


def test_min_rel_sat_direction_stricter_finds_fewer():
    """색 요구를 올리면 검출이 줄어든다. 뒤집히면 UI 슬라이더가 거꾸로 동작한다."""
    assert _count(min_rel_sat=12.0) < _count(min_rel_sat=0.0)


def test_min_rel_sat_zero_disables_the_gate():
    """0 = 끔. 기본값보다 검출이 많아야 한다."""
    assert _count(min_rel_sat=0.0) >= _count()


def test_min_rel_sat_out_of_range_rejected():
    for bad in ({"min_rel_sat": -1.0}, {"min_rel_sat": 100.0}):
        resp = client.post("/detect", json={"image_path": SAMPLES[0], **bad})
        assert resp.status_code == 422, f"{bad} 는 422여야 함"


def test_applied_params_reports_has_chroma():
    """UI 가 색 그룹을 잠글지 판단하는 값이다."""
    ap = _detect()["applied_params"]
    assert "has_chroma" in ap
    assert isinstance(ap["has_chroma"], bool)


def test_colour_sample_reports_chroma_true():
    """sample/ 의 컬러 접시는 색 축이 적용돼야 한다."""
    assert _detect()["applied_params"]["has_chroma"] is True


# --- target_color / color_boost (오퍼레이터가 찍은 색으로 검출 돕기) ---

def _plate(colour=(60, 60, 60)):
    """접시 안에 같은 색 콜로니 3개."""
    img = np.full((300, 300, 3), 200, dtype=np.uint8)
    for cx, cy in [(90, 90), (150, 170), (215, 110)]:
        cv2.circle(img, (cx, cy), 11, colour, -1)
    return img


def test_color_boost_off_by_default_changes_nothing():
    """기본값에서는 색 축이 무동작이라 결과가 완전히 같아야 한다.

    이 파라미터의 안전성은 전적으로 여기에 달려 있다 — 켜지 않은 사람에게
    영향이 가면 안 된다.
    """
    img = _plate()
    base = detect_blobs(img, plate_type="petri")
    # 색을 줘도 boost 가 0 이면 무시된다
    same = detect_blobs(img, plate_type="petri", target_color=(255, 0, 0))
    assert same == base


def test_color_boost_needs_a_target_colour():
    """boost 만 켜고 색을 안 주면 역시 무동작이다."""
    img = _plate()
    base = detect_blobs(img, plate_type="petri")
    assert detect_blobs(img, plate_type="petri", color_boost=0.6) == base


def test_color_boost_never_loses_detections():
    """색 축은 gray 를 대체하지 않고 max 로 더한다.

    그래서 엉뚱한 색을 찍어도 원래 잡히던 것이 사라지면 안 된다. polarity 와
    달리 UI 에 내놓을 수 있는 이유가 이것이다.
    """
    img = _plate()
    base = detect_blobs(img, plate_type="petri")
    for colour in [(255, 0, 0), (0, 255, 0), (10, 10, 240)]:
        got = detect_blobs(img, plate_type="petri",
                           target_color=colour, color_boost=0.6)
        assert len(got) >= len(base), f"{colour} 에서 검출이 줄었다"
