import math

import pytest

from app.param_mapping import (
    edge_to_margin_px,
    max_size_to_area,
    min_size_to_area,
    sensitivity_to_offset,
)


# ---- Anchor values (spec §4.2) — defaults must round-trip to current server defaults ----

def test_sensitivity_default_matches_current_threshold_offset():
    assert sensitivity_to_offset(50) == 7


def test_sensitivity_extremes():
    assert sensitivity_to_offset(0) == -3
    assert sensitivity_to_offset(100) == 15


def test_min_size_default_matches_current_min_area():
    # min_size=20 should give ~min_area=6 (current DEFAULT_MIN_AREA)
    assert min_size_to_area(20) == pytest.approx(6.0, rel=0.10)


def test_min_size_extremes():
    # r_min at 0 = 1px → area = π
    assert min_size_to_area(0) == pytest.approx(math.pi, rel=0.01)
    # r_min at 100 = 10px → area = 100π
    assert min_size_to_area(100) == pytest.approx(math.pi * 100, rel=0.01)


def test_max_size_default_matches_current_max_area():
    # max_size=75 should give ~max_area=5000 (current DEFAULT_MAX_AREA)
    assert max_size_to_area(75) == pytest.approx(5000.0, rel=0.01)


def test_max_size_extremes():
    # r_max at 0 = 10px → area = 100π
    assert max_size_to_area(0) == pytest.approx(math.pi * 100, rel=0.01)
    # r_max at 100 = 50px → area = 2500π
    assert max_size_to_area(100) == pytest.approx(math.pi * 2500, rel=0.01)


def test_edge_default_matches_current_pick_edge_margin():
    from app import config
    assert edge_to_margin_px(40) == config.PICK_EDGE_MARGIN


def test_edge_extremes():
    assert edge_to_margin_px(0) == 0
    assert edge_to_margin_px(100) == 150


# ---- Monotonicity: direction must never reverse ----

@pytest.mark.parametrize("fn", [
    sensitivity_to_offset,
    min_size_to_area,
    max_size_to_area,
    edge_to_margin_px,
])
def test_mapping_is_monotonic_increasing(fn):
    prev = fn(0)
    for v in range(1, 101):
        cur = fn(v)
        assert cur >= prev, f"{fn.__name__} not monotonic at v={v}: {prev} → {cur}"
        prev = cur
