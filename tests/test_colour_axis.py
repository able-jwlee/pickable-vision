"""색 축 파라미터 — min_rel_sat.

|내부채도 - 주변채도| 하한이다. 점자식 인쇄 잉크·데브리는 이 값이 -0.1~+1.7 이고
콜로니는 7~57 이라 판별력이 크다. blob_detector 는 처음부터 이 인자를 받았지만
DetectRequest 에 없어서 호출자가 쓸 수 없었다.
"""
import glob

import pytest
from fastapi.testclient import TestClient

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
