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
    res = score_colonies(cols, min_separation=20.0)
    assert not any(r["pickable"] for r in res)


def test_tiny_speck_not_pickable_when_floor_given():
    cols = [_c(50, 50, 1), _c(500, 500, 8)]  # 첫번째는 너무 작음
    res = score_colonies(cols, radius_min=3.0)
    assert res[0]["pickable"] is False
    assert res[1]["pickable"] is True


def test_all_detections_pickable_by_default():
    """기본값에서는 검출된 것 전부가 피킹 대상이다.

    피킹 필터는 8웰 플레이트 기준 원본 픽셀 값이라 4000px 페트리 이미지에서는
    사실상 아무것도 걸러내지 못했다(실측 96.5% 통과, 원형도는 0개 탈락).
    구분이 있는 척하면서 실제로는 없었으므로 껐다 — config 주석 참조.
    """
    cols = [
        _c(100, 100, 8), _c(105, 100, 8),   # 붙은 쌍
        _c(50, 50, 1),                       # 아주 작음
        _c(500, 500, 40),                    # 아주 큼
    ]
    cols[0]["circularity"] = 0.2             # 찌그러짐
    res = score_colonies(cols)
    assert all(r["pickable"] for r in res)


def test_ranking_still_works_with_filters_off():
    """필터를 껐어도 score 랭킹은 유지된다 — pick_top_n 이 의미를 갖는다."""
    cols = [_c(100, 100, 8), _c(105, 100, 8), _c(900, 900, 8)]
    res = score_colonies(cols, top_n=1)
    picked = [i for i, r in enumerate(res) if r["pickable"]]
    assert len(picked) == 1
    # 고립된 것이 붙은 쌍보다 점수가 높아야 한다
    assert picked[0] == 2


def test_oversized_blob_not_pickable_when_cap_given():
    """상한을 주면 큰 blob(병합 추정)은 피킹 대상에서 제외된다.

    기본값은 상한 없음(config.PICK_RADIUS_MAX = 0)이다. 반지름 단위가 원본
    픽셀이라 해상도에 의존해서, 기본으로 상한을 두면 콜로니가 큰 접시에서
    피킹 대상이 전부 사라진다. 그래서 상한은 요청으로 명시할 때만 걸린다.
    """
    cols = [_c(50, 50, 40), _c(500, 500, 8)]
    res = score_colonies(cols, radius_max=20.0)
    assert res[0]["pickable"] is False
    assert res[1]["pickable"] is True


def test_no_upper_cap_by_default():
    """기본값에서는 큰 blob도 피킹 대상이 된다 (상한 없음)."""
    res = score_colonies([_c(50, 50, 40), _c(500, 500, 8)])
    assert res[0]["pickable"] is True


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
