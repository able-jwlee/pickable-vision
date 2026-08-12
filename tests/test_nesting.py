"""중첩 검출 판정 — app/nesting.py.

경계값은 해석해로 계산해 확인한 것이다 (r_big=10, r_small=2 기준):
    중심거리 8.0 → 겹침비 1.0000 (완전 포함)
    중심거리 8.5 → 0.9209
    중심거리 9.0 → 0.7896
    중심거리 10.0 → 0.4788
    중심거리 12.0 → 0.0000 (접점)
"""
import math

import pytest

from app.nesting import circle_overlap, find_parents


def _c(x, y, r):
    return {"x": x, "y": y, "radius": r}


def test_overlap_identical_circles_is_full_area():
    assert circle_overlap(0, 0, 5, 0, 0, 5) == pytest.approx(math.pi * 25)


def test_overlap_disjoint_circles_is_zero():
    assert circle_overlap(0, 0, 10, 12, 0, 2) == pytest.approx(0.0)


def test_overlap_small_fully_inside_is_small_area():
    """작은 원이 큰 원 안에 완전히 들어가면 교집합 = 작은 원 면적."""
    assert circle_overlap(0, 0, 10, 8, 0, 2) == pytest.approx(math.pi * 4)


def test_overlap_partial_matches_analytic_value():
    ratio = circle_overlap(0, 0, 10, 9, 0, 2) / (math.pi * 4)
    assert ratio == pytest.approx(0.7896, abs=0.001)


def test_fully_contained_child_gets_parent():
    parents = find_parents([_c(0, 0, 10), _c(8, 0, 2)], 0.8)
    assert parents == [None, 0]


def test_threshold_boundary_is_respected():
    """겹침비 0.7896 은 문턱 0.8 에서는 중첩이 아니고 0.7 에서는 중첩이다."""
    geom = [_c(0, 0, 10), _c(9, 0, 2)]
    assert find_parents(geom, 0.8) == [None, None]
    assert find_parents(geom, 0.7) == [None, 0]


def test_equal_radius_circles_are_never_nested():
    """같은 크기는 포함 관계로 보지 않는다 — 어느 쪽이 부모인지 정할 수 없다."""
    assert find_parents([_c(0, 0, 5), _c(0, 0, 5)], 0.8) == [None, None]


def test_innermost_parent_is_chosen():
    """A ⊃ B ⊃ C 이면 C 의 부모는 가장 작은 B 다."""
    geom = [_c(0, 0, 40), _c(0, 0, 20), _c(0, 0, 4)]
    parents = find_parents(geom, 0.8)
    assert parents[2] == 1, "가장 작은 포함자(인덱스 1)가 부모여야 한다"
    assert parents[1] == 0
    assert parents[0] is None


def test_empty_input_returns_empty_list():
    assert find_parents([], 0.8) == []


def test_zero_radius_is_not_crashed_on():
    """반지름 0 은 면적이 0 이라 비율을 낼 수 없다 — 부모 없음으로 둔다."""
    assert find_parents([_c(0, 0, 10), _c(0, 0, 0)], 0.8) == [None, None]
