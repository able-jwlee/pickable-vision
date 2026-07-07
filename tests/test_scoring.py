from app.scoring import score_colonies


def _c(x, y, r):
    return {"x": x, "y": y, "radius": r}


def test_isolated_adequate_colonies_pickable():
    cols = [_c(50, 50, 8), _c(500, 500, 8)]  # 멀리 떨어짐 + 적당한 크기
    res = score_colonies(cols)
    assert all(r["pickable"] for r in res)


def test_single_colony_pickable():
    res = score_colonies([_c(100, 100, 8)])
    assert res[0]["pickable"] is True


def test_clustered_colonies_not_pickable():
    cols = [_c(100, 100, 8), _c(105, 100, 8)]  # 5px 간격 → 너무 붙음
    res = score_colonies(cols)
    assert not any(r["pickable"] for r in res)


def test_tiny_speck_not_pickable():
    cols = [_c(50, 50, 1), _c(500, 500, 8)]  # 첫번째는 너무 작음
    res = score_colonies(cols)
    assert res[0]["pickable"] is False


def test_oversized_blob_not_pickable():
    cols = [_c(50, 50, 40), _c(500, 500, 8)]  # 첫번째는 너무 큼(병합 추정)
    res = score_colonies(cols)
    assert res[0]["pickable"] is False


def test_score_within_unit_range():
    for r in score_colonies([_c(50, 50, 8), _c(60, 55, 3), _c(500, 500, 8)]):
        assert 0.0 <= r["score"] <= 1.0


def test_empty_input():
    assert score_colonies([]) == []


def test_top_n_limits_pickable():
    # 4개 모두 고립·적당 크기지만 top_n=2면 점수 상위 2개만 pickable
    cols = [_c(50, 50, 8), _c(300, 50, 8), _c(50, 300, 8), _c(300, 300, 8)]
    res = score_colonies(cols, top_n=2)
    assert sum(1 for r in res if r["pickable"]) == 2
