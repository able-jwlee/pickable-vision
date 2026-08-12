"""오퍼레이터용 0~100 스케일 → 내부 파라미터 매핑.

top-hat 경로를 제거하면서 그쪽 전용이던 세 매핑(sensitivity_to_offset,
min_size_to_area, max_size_to_area)도 함께 사라졌다. 남은 둘만 검증한다.

방향성을 테스트로 고정하는 이유: 뒤집히면 오퍼레이터 UI 슬라이더가 반대로
동작하는데 눈으로는 알아채기 어렵다.
"""
import pytest

from app import config
from app.param_mapping import edge_to_margin_px, sensitivity_to_min_t


def test_sensitivity_anchor_matches_server_default():
    """감도 50 은 서버 기본값(config.BLOB_MIN_T)과 같아야 한다.

    상수를 하드코딩하지 않고 관계를 검사한다. 기본값을 옮길 때 앵커를 같이
    옮기는 것을 잊으면, sensitivity 를 보내는 클라이언트와 보내지 않는
    클라이언트가 서로 다른 감도로 동작한다.
    """
    assert sensitivity_to_min_t(50) == pytest.approx(config.BLOB_MIN_T)


def test_sensitivity_direction_higher_means_more_sensitive():
    """감도를 올리면 t 문턱이 내려간다 (= 흐린 콜로니까지 잡는다)."""
    assert sensitivity_to_min_t(0) > sensitivity_to_min_t(50)
    assert sensitivity_to_min_t(50) > sensitivity_to_min_t(100)


def test_sensitivity_extremes_stay_in_measured_range():
    """양 끝이 실측한 곡선 범위 안에 있어야 한다 (t=90 ~ t=12)."""
    assert sensitivity_to_min_t(0) == pytest.approx(90.0)
    assert sensitivity_to_min_t(100) == pytest.approx(12.0)


def test_edge_margin_anchor_and_direction():
    """여백 0 은 제한 없음, 올릴수록 안쪽으로 더 줄인다."""
    assert edge_to_margin_px(0) == 0
    assert edge_to_margin_px(100) > edge_to_margin_px(50) > edge_to_margin_px(0)


@pytest.mark.parametrize("fn", [edge_to_margin_px])
def test_monotonic_increasing(fn):
    vals = [fn(v) for v in range(0, 101, 10)]
    assert vals == sorted(vals), f"{fn.__name__} 이 단조증가가 아니다: {vals}"


def test_sensitivity_monotonic_decreasing():
    """감도만 방향이 반대다 — 올릴수록 문턱이 내려간다."""
    vals = [sensitivity_to_min_t(v) for v in range(0, 101, 10)]
    assert vals == sorted(vals, reverse=True), f"단조감소가 아니다: {vals}"
