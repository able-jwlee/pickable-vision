"""중첩 검출의 API 계약 — parent_id 와 exclude_nested.

parent_id 는 파라미터 없이 항상 계산된다. 응답에 필드만 늘어나므로 검출
성적에는 영향이 없고, 프론트가 중첩 검출을 구분할 수 있게 된다.

**샘플을 14581.jpg 로 고정한 이유.** 기본 문턱(0.8)에서 중첩 검출이 나오는
접시여야 단정이 공허해지지 않는다. 실측(2026-08-12) 중첩 개수:
    13895 0 · 13938 1 · 14130 0 · 14380 1 · 14410 0
    14512 3 · **14581 6** · 14618 0 · 14627 2 · 14684 1
lower-resolution 의 첫 파일(13895)은 0개라 쓸 수 없다.

검출이 무거워(115개) 매 테스트마다 재검출하면 느리므로 모듈 스코프 fixture 로
두 응답(기본 / exclude_nested=True)만 받아 공유한다.
"""
import os

import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

SAMPLE = "sample/lower-resolution/14581.jpg"
pytestmark = pytest.mark.skipif(
    not os.path.exists(SAMPLE),
    reason=f"{SAMPLE} 이 없으면 건너뜀 (sample/ 은 저장소에 커밋되지 않음)",
)


def _detect(**kw):
    resp = client.post("/detect", json={"image_path": SAMPLE, **kw})
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.fixture(scope="module")
def base():
    return _detect()


def test_every_colony_has_parent_id_field(base):
    for c in base["colonies"]:
        assert "parent_id" in c


def test_sample_actually_has_nested_detections(base):
    """이 파일의 다른 단정들이 공허해지지 않게 지키는 가드.

    검출기가 바뀌어 이 접시에서 중첩이 사라지면, 아래 테스트들은 아무것도
    검증하지 않으면서 통과한다. 그때 이 테스트가 먼저 실패해 알려준다.
    """
    nested = [c for c in base["colonies"] if c["parent_id"] is not None]
    assert nested, (
        f"{SAMPLE} 에 중첩 검출이 없다 — 실측 시점에는 6개였다. "
        "검출기가 바뀌었다면 중첩이 나오는 다른 샘플로 교체할 것."
    )


def test_parent_id_points_at_a_larger_colony(base):
    """부모는 반드시 더 큰 검출이어야 한다. 뒤집히면 UI 가 엉뚱한 것을 묶는다."""
    by_id = {c["id"]: c for c in base["colonies"]}
    nested = [c for c in base["colonies"] if c["parent_id"] is not None]
    assert nested, "가드 테스트가 먼저 실패해야 한다"
    for c in nested:
        parent = by_id[c["parent_id"]]
        assert parent["radius"] > c["radius"], (
            f"id={c['id']} r={c['radius']} 의 부모 r={parent['radius']} 가 더 작다"
        )


def test_parent_id_never_references_itself(base):
    for c in base["colonies"]:
        assert c["parent_id"] != c["id"]


def test_parent_ids_are_valid_ids(base):
    ids = {c["id"] for c in base["colonies"]}
    for c in base["colonies"]:
        if c["parent_id"] is not None:
            assert c["parent_id"] in ids


def test_nested_overlap_constant_is_the_measured_choice():
    """0.8 은 실측으로 고른 값이다 (곡선은 config 주석 참조).

    조용히 옮기면 어느 검출이 중첩으로 분류되는지가 달라지므로 상수로 묶는다.
    """
    from app import config
    assert config.BLOB_NESTED_OVERLAP == 0.8


@pytest.fixture(scope="module")
def cut():
    return _detect(exclude_nested=True)


def test_exclude_nested_default_is_off(base):
    assert base["applied_params"]["exclude_nested"] is False


def test_exclude_nested_removes_nested_and_shrinks_count(base, cut):
    nested = sum(1 for c in base["colonies"] if c["parent_id"] is not None)
    assert nested > 0, "가드 테스트가 먼저 실패해야 한다"
    assert cut["count"] == base["count"] - nested
    assert len(cut["colonies"]) == cut["count"]


def test_exclude_nested_leaves_no_dangling_parent_id(cut):
    """걸러낸 대상이 parent_id 를 가진 검출 전부이므로 남는 것은 모두 null 이다."""
    for c in cut["colonies"]:
        assert c["parent_id"] is None


def test_exclude_nested_renumbers_ids_from_one(cut):
    assert [c["id"] for c in cut["colonies"]] == list(
        range(1, len(cut["colonies"]) + 1))


def test_exclude_nested_preserves_scores_of_surviving_colonies(base, cut):
    """점수는 걸러내기 **전** 전체 집합에서 계산해야 한다.

    고립도(가장 가까운 이웃까지의 거리)가 이웃 수에 의존하므로, 걸러낸 뒤
    계산하면 같은 콜로니의 score 가 옵션에 따라 달라진다. 그러면 pick_top_n
    랭킹이 옵션에 따라 흔들린다.
    """
    kept = {(round(c["x"], 3), round(c["y"], 3)): c
            for c in base["colonies"] if c["parent_id"] is None}
    assert kept, "비교할 검출이 없다"
    for c in cut["colonies"]:
        key = (round(c["x"], 3), round(c["y"], 3))
        assert key in kept, f"({c['x']}, {c['y']}) 가 기본 응답에 없다"
        assert c["score"] == pytest.approx(kept[key]["score"])
        assert c["pickable"] == kept[key]["pickable"]


def test_exclude_nested_off_is_identical_to_omitting_it(base):
    """되돌림 경로 — 기본값을 명시해도 생략한 것과 같아야 한다."""
    explicit = _detect(exclude_nested=False)
    assert explicit["count"] == base["count"]
    assert explicit["colonies"] == base["colonies"]
