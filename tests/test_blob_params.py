"""blob 경로의 /detect 요청 파라미터 검증.

각 파라미터가 (1) 요청으로 전달되고 (2) applied_params 로 되반환되며
(3) 방향성이 상식과 일치하는지 확인한다. 방향성이 뒤집히면 오퍼레이터 UI의
슬라이더가 반대로 동작하므로 회귀로 잡아야 한다.
"""
import glob

import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

# 원형 petri 접시 샘플 (콜로니 라벨이 함께 있는 디렉터리)
SAMPLES = sorted(glob.glob("sample/lower-resolution/*.jpg"))
pytestmark = pytest.mark.skipif(
    not SAMPLES, reason="sample/ 이미지가 없으면 건너뜀 (저장소에 커밋되지 않음)"
)


def _detect(**kw):
    return client.post("/detect", json={"image_path": SAMPLES[0], **kw}).json()


def _count(**kw):
    return _detect(**kw)["count"]


def _pickable(**kw):
    return sum(1 for c in _detect(**kw)["colonies"] if c["pickable"])


def test_applied_params_echoes_blob_knobs():
    ap = _detect()["applied_params"]
    for key in ("plate_type", "min_t", "min_diam_frac",
                "max_diam_frac", "colour_credit", "work_size",
                "adaptive_scale", "pick_radius_min", "pick_radius_max",
                "min_solidity", "min_roundness"):
        assert key in ap, f"applied_params 에 {key} 누락"


def test_shape_gates_direction_looser_finds_more():
    """모양 게이트를 풀면 검출이 는다. 뒤집히면 UI 슬라이더가 거꾸로 동작한다."""
    assert _count(min_solidity=0.0) >= _count(min_solidity=0.95)
    assert _count(min_roundness=0.0) >= _count(min_roundness=0.90)


def test_solidity_default_is_the_measured_optimum():
    """기본 solidity 는 0.75.

    0.90 에서 내린 값이다. 39장 실측에서 같은 정밀도 기준 재현율이 모든
    운영점에서 1.5~2.4%p 올랐다(교환이 아니라 Pareto 곡선 자체의 상승).
    0.75 아래로는 결과가 동일해 포화점이기도 하다. 이 값이 조용히 되돌려지면
    재현율이 함께 내려가므로 상수로 고정한다.
    """
    from app import config
    assert config.BLOB_MIN_SOLIDITY == 0.75
    assert _detect()["applied_params"]["min_solidity"] == 0.75


def test_min_t_direction_lower_finds_more():
    """감도 knob: t 하한이 낮으면 더 많이 검출된다."""
    assert _count(min_t=15) > _count(min_t=60)


def test_sensitivity_anchor_matches_server_default():
    """감도 50 은 **서버 기본값과 같은 min_t** 로 매핑돼야 한다.

    상수를 하드코딩하지 않고 관계를 검사한다. 기본값을 옮길 때 앵커를 같이
    옮기는 것을 잊으면, sensitivity 를 보내는 클라이언트와 보내지 않는
    클라이언트가 서로 다른 감도로 동작하고 그 차이는 눈으로 알아채기 어렵다.
    이 테스트는 그 어긋남만 잡고, 값 자체의 선택은 막지 않는다.
    """
    from app import config

    default = config.BLOB_MIN_T
    assert _detect(sensitivity=50)["applied_params"]["min_t"] == pytest.approx(default)
    assert _detect()["applied_params"]["min_t"] == pytest.approx(default)
    # 방향성: 감도를 내리면 엄격해지고 올리면 민감해진다.
    assert _detect(sensitivity=0)["applied_params"]["min_t"] > default
    assert _detect(sensitivity=100)["applied_params"]["min_t"] < default


def test_raw_min_t_overrides_sensitivity():
    ap = _detect(sensitivity=100, min_t=42)["applied_params"]
    assert ap["min_t"] == pytest.approx(42.0)


def test_max_diam_frac_excludes_large_colonies():
    """상한 크기를 작게 두면 큰 콜로니가 빠져 검출 수가 줄어든다."""
    assert _count(max_diam_frac=0.05) < _count()


def test_min_diam_frac_excludes_small_colonies():
    assert _count(min_diam_frac=0.10) < _count()


def test_diam_frac_cap_is_resolution_independent():
    """크기 상한은 접시 지름 대비 비율이라 처리 해상도가 달라도 같은 물리 크기다.

    검출 **수**는 해상도에 따라 크게 달라지므로(민감도가 달라짐) 비교 대상이
    아니다. 확인할 것은 "허용된 최대 반지름"이 두 해상도에서 비슷한지다.
    작업 픽셀이나 원본 픽셀로 크기를 받으면 이 성질이 깨져 오퍼레이터가 쓸 수 없다.
    """
    def max_radius(work):
        cs = _detect(max_diam_frac=0.06, work_size=work)["colonies"]
        assert cs, f"work_size={work} 에서 검출 없음"
        return max(c["radius"] for c in cs)

    a, b = max_radius(1024), max_radius(1536)
    assert 0.7 < (a / b) < 1.4, f"물리 상한이 해상도에 따라 달라짐: {a:.1f} vs {b:.1f}"


def test_colour_credit_increases_detections():
    """색 할인을 켜면 t 요구치가 낮아져 더 많이 검출된다."""
    assert _count(colour_credit=3.0) > _count(colour_credit=1.0)


def test_colour_credit_default_is_off():
    assert _detect()["applied_params"]["colour_credit"] == pytest.approx(1.0)


def test_pick_radius_max_zero_means_no_upper_limit():
    """상한 0 = 제한 없음. 콜로니가 큰 접시에서 후보가 0이 되는 것을 풀 수 있다."""
    assert _pickable(pick_radius_max=0) >= _pickable()


def test_pick_radius_max_larger_allows_more_pickable():
    assert _pickable(pick_radius_max=60) >= _pickable(pick_radius_max=20)


def test_work_size_is_echoed_and_accepted():
    assert _detect(work_size=1536)["applied_params"]["work_size"] == 1536


def test_out_of_range_params_rejected():
    for bad in ({"min_t": 0.5}, {"min_t": 500}, {"min_diam_frac": 1.5},
                {"colour_credit": 0.5}, {"colour_credit": 99},
                {"work_size": 100}, {"work_size": 9999},
                {"plate_type": "nope"}):
        resp = client.post("/detect", json={"image_path": SAMPLES[0], **bad})
        assert resp.status_code == 422, f"{bad} 는 422여야 함"
