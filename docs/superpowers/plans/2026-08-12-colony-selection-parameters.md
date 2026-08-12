# 콜로니 선별 파라미터 4축 노출 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `POST /detect` 에 중첩 검출 정보(`parent_id`)와 제외 옵션(`exclude_nested`), 색 게이트(`min_rel_sat`), 색 축 적용 여부(`has_chroma`)를 추가해 오퍼레이터가 크기·모양·색상·분리 네 축을 조절할 수 있게 한다.

**Architecture:** 검출 알고리즘(`detect_blobs`)과 NMS 는 건드리지 않는다. 중첩 판정은 `app/nesting.py` 의 순수 함수 하나로 분리하고, `app/api.py` 의 `_detect_and_score` 가 검출 결과를 받은 뒤 후처리로 호출한다. 기본값을 그대로 두면 지금과 완전히 동일한 결과가 나오는 되돌림 경로를 유지한다.

**Tech Stack:** Python 3.10 · FastAPI · Pydantic v2 · OpenCV · NumPy · pytest

## Global Constraints

- 설계 근거는 `docs/superpowers/specs/2026-08-12-colony-selection-parameters-design.md` 다. 수치를 바꾸지 말 것.
- **기본값 변경 금지.** 이번 작업은 노출만 한다. `exclude_nested` 기본 `False`, `min_rel_sat` 기본 `config.BLOB_MIN_REL_SAT`(1.5) 유지.
- `detect_blobs` 의 **반환 형식은 바꾸지 않는다** — `(x, y, radius, circularity)` 리스트. `detector.detect` 와 호환돼야 한다.
- `app/models.py` 의 필드 `description` 은 **프론트엔드용**이다. `/openapi.json` 에 그대로 실려 폼 라벨이 된다. 짧고 조작적으로 쓰고, 근거는 `app/config.py` 주석에 남긴다.
- `models.py` 를 고치는 **모든** 작업은 같은 커밋에서 `.venv\Scripts\python scripts/export_openapi.py` 로 `docs/openapi.json` 을 재생성해야 한다. `tests/test_openapi_spec.py::test_checked_in_spec_matches_code` 가 이를 강제한다.
- 신규 요청 필드에는 반드시 `description` 을 넣는다. `test_every_request_field_is_documented` 가 빈 description 을 잡는다.
- 테스트는 저장소 루트(`vision/`)에서 실행한다. 명령은 `.venv\Scripts\python -m pytest ...`.
- `sample/` 이미지는 저장소에 없을 수 있다. 샘플이 필요한 테스트는 기존 패턴대로 `pytest.mark.skipif` 로 건너뛴다.
- 주석과 문서는 한국어로 쓴다(기존 코드베이스 관행).

---

### Task 1: 중첩 판정 순수 함수

**Files:**
- Create: `app/nesting.py`
- Test: `tests/test_nesting.py`

**Interfaces:**
- Consumes: 없음 (순수 함수, 의존성은 표준 `math` 뿐)
- Produces:
  - `circle_overlap(x1: float, y1: float, r1: float, x2: float, y2: float, r2: float) -> float` — 두 원의 교집합 면적
  - `find_parents(geom: list[dict], overlap: float) -> list[int | None]` — `geom[i]` 를 감싸는 부모의 **0-기반 인덱스**, 없으면 `None`. `geom` 의 각 항목은 `{"x": float, "y": float, "radius": float}` 를 갖는다(다른 키는 무시).

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_nesting.py`:

```python
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
```

- [ ] **Step 2: 실패를 확인한다**

Run: `.venv\Scripts\python -m pytest tests/test_nesting.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.nesting'`

- [ ] **Step 3: 최소 구현을 쓴다**

`app/nesting.py`:

```python
"""검출 안에 들어간 검출을 찾는다.

**왜 별 모듈인가.** `detect_blobs` 의 NMS 는 중심 거리만 본다 — 억제 반경이
`max(r) * BLOB_NMS_FRAC` 이라, 큰 검출 안에 있어도 중심이 그 반경 밖이면
살아남는다. 포함 관계를 검사하지 않기 때문이다. 그 검사를 NMS 안에 넣지 않고
후처리로 분리한 이유는, 검출 경로를 건드리지 않으면 옵션을 끈 상태에서 기존
결과가 **바이트 단위로 동일**하다는 것을 보장할 수 있기 때문이다.

**왜 면적 겹침인가.** 실측(라벨 39장)에서 중첩 검출은 콜로니 윤곽선에 걸쳐
있는 경우가 흔해서, "완전히 포함" 기준으로는 놓친다. 문턱별 성적은
`config.BLOB_NESTED_OVERLAP` 주석에 있다.
"""
from __future__ import annotations

import math


def circle_overlap(
    x1: float, y1: float, r1: float, x2: float, y2: float, r2: float
) -> float:
    """두 원의 교집합 면적 (해석해).

    렌즈 모양 교집합은 두 원형 세그먼트의 합이다. 몬테카를로나 마스크 렌더링을
    쓰지 않는 이유는 검출 수가 수백 개면 쌍이 수만 개가 되기 때문이다.
    """
    d = math.hypot(x1 - x2, y1 - y2)
    if d >= r1 + r2:
        return 0.0
    if d <= abs(r1 - r2):
        # 한쪽이 다른 쪽을 완전히 품는다 — 작은 원 면적이 곧 교집합이다.
        return math.pi * min(r1, r2) ** 2
    a1 = math.acos((d * d + r1 * r1 - r2 * r2) / (2 * d * r1))
    a2 = math.acos((d * d + r2 * r2 - r1 * r1) / (2 * d * r2))
    return (r1 * r1 * (a1 - math.sin(2 * a1) / 2)
            + r2 * r2 * (a2 - math.sin(2 * a2) / 2))


def find_parents(geom: list[dict], overlap: float) -> list[int | None]:
    """각 검출을 감싸는 부모의 인덱스. 없으면 None.

    부모의 조건은 두 가지다.
      1. 반지름이 **더 크다** (같으면 어느 쪽이 부모인지 정할 수 없어 제외)
      2. 자기 면적의 `overlap` 배 이상을 덮는다

    여러 개가 조건을 만족하면 **가장 작은 것**(직속 부모)을 고른다. 그래야
    A ⊃ B ⊃ C 에서 C 의 부모가 A 가 아니라 B 가 된다.
    """
    out: list[int | None] = [None] * len(geom)
    for i, c in enumerate(geom):
        r = float(c["radius"])
        area = math.pi * r * r
        if area <= 0:
            continue
        best: int | None = None
        best_r: float | None = None
        for j, o in enumerate(geom):
            if j == i:
                continue
            ro = float(o["radius"])
            if ro <= r:
                continue
            shared = circle_overlap(
                float(c["x"]), float(c["y"]), r,
                float(o["x"]), float(o["y"]), ro,
            )
            if shared / area < overlap:
                continue
            if best_r is None or ro < best_r:
                best, best_r = j, ro
        out[i] = best
    return out
```

- [ ] **Step 4: 통과를 확인한다**

Run: `.venv\Scripts\python -m pytest tests/test_nesting.py -v`
Expected: PASS (10 passed)

- [ ] **Step 5: 커밋**

```bash
git add app/nesting.py tests/test_nesting.py
git commit -m "검출 안의 검출을 찾는 순수 함수 추가"
```

---

### Task 2: 응답에 `parent_id` 노출

**Files:**
- Modify: `app/config.py` (`BLOB_NMS_FRAC` 아래에 `BLOB_NESTED_OVERLAP` 추가)
- Modify: `app/models.py:408-432` (`Colony` 에 `parent_id`)
- Modify: `app/api.py:121-179` (`_detect_and_score`)
- Modify: `docs/openapi.json` (재생성)
- Test: `tests/test_nested_api.py`

**Interfaces:**
- Consumes: `app.nesting.find_parents(geom, overlap) -> list[int | None]` (Task 1)
- Produces: `Colony.parent_id: int | None` — 자기를 감싸는 검출의 `id`(1-기반). 없으면 `null`. `config.BLOB_NESTED_OVERLAP: float`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_nested_api.py`:

```python
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
```

- [ ] **Step 2: 실패를 확인한다**

Run: `.venv\Scripts\python -m pytest tests/test_nested_api.py -v`
Expected: FAIL — `test_every_colony_has_parent_id_field` 에서 `assert "parent_id" in c` 실패, `test_nested_overlap_constant_is_the_measured_choice` 에서 `AttributeError: module 'app.config' has no attribute 'BLOB_NESTED_OVERLAP'`

- [ ] **Step 3: config 상수를 추가한다**

`app/config.py` 의 `BLOB_NMS_FRAC = 0.65` 줄 **바로 아래**에 넣는다:

```python
BLOB_NESTED_OVERLAP = 0.8      # 자기 면적의 이 비율 이상이 더 큰 검출 안에 들어가면
                               # "중첩 검출"로 보고 parent_id 를 붙인다.
                               # NMS 는 중심 거리만 보므로(위 BLOB_NMS_FRAC) 큰 검출
                               # 안에 있어도 중심이 억제 반경 밖이면 살아남는다.
                               #
                               # **기본으로 지우지 않는다.** 실측(39장) 문턱별
                               # 억제 성적 — 어느 문턱에서도 F1 이 내려간다:
                               #   문턱  억제 그중정답  정밀도  재현율   F1   ΔF1
                               #   0.5    47    28    82.8%  74.2%  78.3 -0.53
                               #   0.6    39    21    82.9%  74.5%  78.5 -0.31
                               #   0.7    36    20    82.8%  74.6%  78.5 -0.32
                               #   0.8    30    16    82.7%  74.8%  78.6 -0.23
                               #   0.9    27    15    82.6%  74.9%  78.6 -0.24
                               #   1.0    17     8    82.5%  75.2%  78.7 -0.07
                               # (기준선 82.2%/75.7%/78.80)
                               #
                               # 억제 대상의 절반 이상이 정답이기 때문이다. 완전
                               # 포함 19개를 눈으로 확인하니 세 종류가 섞여 있었다:
                               #   A 부모가 정답, 자식은 오검출(콜로니 내부 링에
                               #     LoG 반응) — 지워야 함
                               #   B 자식이 진짜 작은 콜로니인데 부모 반지름
                               #     과대추정으로 삼킴 (자식 r=16→정답 r=14 /
                               #     부모 r=90→정답 r=64) — 지우면 손해
                               #   C 부모가 큰 오검출이고 자식이 유일한 정답
                               #     (부모 r=249 미매칭) — 통째로 놓침
                               # 반지름 비가 A 0.16~0.31, B 0.16~0.18 로 겹쳐
                               # **기하학으로 A/B/C 를 구별할 수 없다.** 그래서
                               # 0.8 은 "지울지 말지"가 아니라 "무엇을 중첩으로
                               # 부를지"의 기준이고, 지우기는 exclude_nested 로
                               # 호출자가 선택한다.
                               #
                               # (기각) 반지름 클리핑 — 이웃 중심까지의 거리로
                               # 반지름을 제한하는 안. 유형 A 에서 오검출 자식이
                               # 정상 부모를 파괴한다: 부모 r=133(정답 116) 이
                               # 거리 92 의 자식 r=33 때문에 59 로 줄어든다.
```

- [ ] **Step 4: `Colony` 에 필드를 추가한다**

`app/models.py` 의 `Colony` 클래스에서 `pickable` 필드 **뒤에** 추가한다:

```python
    parent_id: int | None = Field(
        None,
        description=(
            "이 검출을 감싸는 더 큰 검출의 `id`. 없으면 `null`. "
            "면적의 80% 이상이 그 검출 안에 들어갈 때 붙는다. "
            "**콜로니 내부 구조에 반응한 중복일 수도, 큰 콜로니 옆의 진짜 작은 "
            "콜로니일 수도 있다** — 실측에서 반반이라 서버는 지우지 않는다. "
            "지우려면 `exclude_nested` 를 쓴다."
        ),
    )
```

- [ ] **Step 5: `_detect_and_score` 에서 채운다**

`app/api.py` 의 `_detect_and_score` 에서 `geom` 을 만든 뒤 `parents` 를 구하고, 마지막 `Colony(...)` 생성에 넘긴다. 파일 상단 import 에 `from app.nesting import find_parents` 를 추가한다.

```python
    geom = [
        {"x": x, "y": y, "radius": r, "circularity": c}
        for x, y, r, c in circles
    ]
    # 중첩 판정은 검출 경로 밖에서 한다 — NMS 를 건드리지 않아야 옵션을 끈
    # 상태에서 기존 결과가 그대로 나온다는 것을 보장할 수 있다.
    parents = find_parents(geom, config.BLOB_NESTED_OVERLAP)
```

그리고 반환부를 바꾼다:

```python
    return [
        Colony(
            id=i + 1,
            x=x,
            y=y,
            radius=r,
            circularity=c,
            score=scores[i]["score"],
            pickable=scores[i]["pickable"],
            # find_parents 는 0-기반 인덱스를 주고 id 는 1-기반이다.
            parent_id=None if parents[i] is None else parents[i] + 1,
        )
        for i, (x, y, r, c) in enumerate(circles)
    ]
```

- [ ] **Step 6: 테스트가 통과하는지 확인한다**

Run: `.venv\Scripts\python -m pytest tests/test_nested_api.py tests/test_detect_endpoint.py -v`
Expected: PASS

- [ ] **Step 7: OpenAPI 스펙을 재생성한다**

`models.py` 를 고쳤으므로 체크인된 스펙이 낡았다.

Run: `.venv\Scripts\python scripts/export_openapi.py`
Run: `.venv\Scripts\python -m pytest tests/test_openapi_spec.py -v`
Expected: PASS (`test_checked_in_spec_matches_code` 포함)

- [ ] **Step 8: 커밋**

```bash
git add app/config.py app/models.py app/api.py docs/openapi.json tests/test_nested_api.py
git commit -m "API: 검출 안의 검출을 parent_id 로 알려줌"
```

---

### Task 3: `exclude_nested` 요청 파라미터

**Files:**
- Modify: `app/models.py` (`DetectRequest` 에 `exclude_nested`)
- Modify: `app/api.py` (`_resolve_params` · `_detect_and_score`)
- Modify: `docs/openapi.json` (재생성)
- Test: `tests/test_nested_api.py` (Task 2 파일에 추가)

**Interfaces:**
- Consumes: `Colony.parent_id` (Task 2), `applied_params` dict (기존 `_resolve_params`)
- Produces: 요청 필드 `exclude_nested: bool = False`, `applied_params["exclude_nested"]`

- [ ] **Step 1: 실패하는 테스트를 추가한다**

`tests/test_nested_api.py` 끝에 붙인다:

```python
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
```

- [ ] **Step 2: 실패를 확인한다**

Run: `.venv\Scripts\python -m pytest tests/test_nested_api.py -v -k exclude`
Expected: FAIL — `applied_params` 에 `exclude_nested` 가 없어 `KeyError`

- [ ] **Step 3: 요청 필드를 추가한다**

`app/models.py` 의 `DetectRequest` 에서 `split_area_ratio` 필드 **뒤에** 넣는다 (분리 축 파라미터와 함께 두는 것이 읽기 쉽다):

```python
    # 중첩 검출 제외. **기본 끔** — 실측상 어느 문턱에서도 F1 이 내려간다
    # (0.8 에서 ΔF1 -0.23). 억제 대상의 절반 이상이 정답이기 때문이다.
    # 특정 접시에서 눈에 거슬릴 때 켜는 비상구이지 조정 knob 이 아니다.
    exclude_nested: bool = Field(
        False,
        description=(
            "`parent_id` 가 붙은 검출을 `colonies` 에서 빼고 `count` 도 줄인다. "
            "**기본 끔** — 실측 39장에서 F1 이 0.23 내려간다(제외 대상 30개 중 "
            "16개가 정답). 같은 콜로니를 두 번 집는 것을 막고 싶을 때만 켠다. "
            "켜면 남는 검출의 `parent_id` 는 모두 `null` 이고 `id` 는 1부터 "
            "다시 매겨진다."
        ),
    )
```

- [ ] **Step 4: `_resolve_params` 에 넣는다**

`app/api.py` 의 `_resolve_params` 반환 dict 에서 `"split_area_ratio": req.split_area_ratio,` 아래에 추가한다:

```python
        "exclude_nested": req.exclude_nested,
```

- [ ] **Step 5: `_detect_and_score` 에서 걸러낸다**

`_detect_and_score` 의 반환부를 바꾼다. **점수 계산은 걸러내기 전 전체 집합에서 한다** — 고립도(가장 가까운 이웃까지의 거리)가 이웃 수에 의존하므로, 걸러낸 뒤 계산하면 같은 콜로니의 점수가 옵션에 따라 달라진다.

```python
    colonies = [
        Colony(
            id=i + 1,
            x=x,
            y=y,
            radius=r,
            circularity=c,
            score=scores[i]["score"],
            pickable=scores[i]["pickable"],
            parent_id=None if parents[i] is None else parents[i] + 1,
        )
        for i, (x, y, r, c) in enumerate(circles)
    ]
    if not resolved["exclude_nested"]:
        return colonies
    # 걸러낸 대상이 parent_id 를 가진 검출 전부이므로 남는 것은 모두 null 이다
    # (A ⊃ B ⊃ C 면 B·C 가 함께 빠지고 A 만 남는다). 따라서 id 를 다시 매겨도
    # parent_id 가 끊어지지 않는다.
    kept = [c for c in colonies if c.parent_id is None]
    for n, colony in enumerate(kept, start=1):
        colony.id = n
    return kept
```

- [ ] **Step 6: 통과를 확인한다**

Run: `.venv\Scripts\python -m pytest tests/test_nested_api.py -v`
Expected: PASS

- [ ] **Step 7: OpenAPI 스펙 재생성 + 전체 테스트**

Run: `.venv\Scripts\python scripts/export_openapi.py`
Run: `.venv\Scripts\python -m pytest -q`
Expected: 전부 PASS

- [ ] **Step 8: 커밋**

```bash
git add app/models.py app/api.py docs/openapi.json tests/test_nested_api.py
git commit -m "API: exclude_nested 로 중첩 검출을 결과에서 뺄 수 있게 함"
```

---

### Task 4: `min_rel_sat` — 색 게이트 노출

**Files:**
- Modify: `app/config.py:125-128` (`BLOB_MIN_REL_SAT` 주석에 측정 곡선 추가)
- Modify: `app/models.py` (`DetectRequest` 에 `min_rel_sat`)
- Modify: `app/api.py` (`_resolve_params` · `_detect_and_score`)
- Modify: `docs/openapi.json` (재생성)
- Test: `tests/test_colour_axis.py`

**Interfaces:**
- Consumes: `detect_blobs(..., min_rel_sat=...)` — `app/blob_detector.py:748` 에 이미 있는 인자
- Produces: 요청 필드 `min_rel_sat: float | None`, `applied_params["min_rel_sat"]`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_colour_axis.py`:

```python
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
```

- [ ] **Step 2: 실패를 확인한다**

Run: `.venv\Scripts\python -m pytest tests/test_colour_axis.py -v`
Expected: FAIL — `applied_params` 에 `min_rel_sat` 없음(`KeyError`), 그리고 `min_rel_sat` 이 알 수 없는 필드라 무시되어 방향성 테스트도 실패

- [ ] **Step 3: 요청 필드를 추가한다**

`app/models.py` 의 `DetectRequest` 에서 `colour_credit` 필드 **뒤에** 넣는다 (색 축을 함께 둔다):

```python
    # 색 게이트 본체. 잉크·데브리는 -0.1~+1.7, 콜로니는 7~57 로 판별력이 크다.
    # 실측(39장): 0 → 77.5%/76.2%, 1.5 → 82.2%/75.7%(기본), 3.0 → 84.0%/74.7%,
    #   6.0 → 88.2%/69.2%, 12.0 → 93.0%/60.8% (정밀도/재현율)
    # 3.0 이 전역 F1 최고(79.03 대 78.80)지만 기본값 변경은 별건으로 다룬다.
    min_rel_sat: float | None = Field(
        None,
        ge=0.0,
        le=60.0,
        description=(
            "색 차이 요구 — |내부채도 − 주변채도| 하한. 0 = 끔. "
            "인쇄 글씨·데브리는 이 값이 0 근처(−0.1~1.7)이고 콜로니는 7~57 이라 "
            "**오검출을 걷어내는 가장 강한 레버**다. "
            "실측: 0 → 77.5%/76.2%, **1.5 → 82.2%/75.7%(기본)**, "
            "3.0 → 84.0%/74.7%, 6.0 → 88.2%/69.2%, 12.0 → 93.0%/60.8% "
            "(정밀도/재현율). 생략하면 서버 기본값. "
            "무채색 이미지에서는 서버가 색 축을 끄므로 이 값이 무시된다 — "
            "응답 `applied_params.has_chroma` 로 확인할 것."
        ),
    )
```

- [ ] **Step 4: `_resolve_params` 에 넣는다**

`app/api.py` 의 `_resolve_params` 에서 `"colour_credit": req.colour_credit,` 아래에 추가한다:

```python
        "min_rel_sat": (config.BLOB_MIN_REL_SAT if req.min_rel_sat is None
                        else req.min_rel_sat),
```

- [ ] **Step 5: `detect_blobs` 호출에 전달한다**

`app/api.py` 의 `_detect_and_score` 안 `detect_blobs(...)` 호출에서 `colour_credit=resolved["colour_credit"],` 아래에 추가한다:

```python
        min_rel_sat=resolved["min_rel_sat"],
```

- [ ] **Step 6: config 주석에 측정 곡선을 남긴다**

`app/config.py` 의 `BLOB_MIN_REL_SAT = 1.5` 주석 블록 끝에 이어 붙인다:

```python
                               # 실측 재측정 (2026-08-12, 현재 설정 기준):
                               #    0   정밀도 77.48% / 재현율 76.2% / F1 76.86
                               #    0.75      79.34% /      76.1% /    77.71
                               #    1.5       82.20% /      75.7% /    78.80  ← 현재
                               #    3.0       83.96% /      74.7% /    79.03  ← 전역 최고
                               #    6.0       88.18% /      69.2% /    77.54
                               #   12.0       93.02% /      60.8% /    73.51
                               # 그룹별 F1 — **최적이 그룹마다 갈린다**:
                               #            lower bright  dark vague
                               #    1.5      83.2   80.7  83.7  61.6
                               #    3.0      83.9   80.4  84.3  62.4   ← lower 최고
                               #    6.0      75.1   79.6  86.5  64.2   ← dark·vague 최고
                               #   12.0      54.0   80.2  84.9  61.7
                               # bright 는 전 구간 ~80 으로 이 축에 둔감하다.
                               # 3.0 이 전역 F1 최고이므로 기본값 상향 후보다 —
                               # 다만 기본값 변경은 별건으로 다룬다(2026-08-12).
                               # 그래서 이 축은 DetectRequest.min_rel_sat 으로
                               # 호출자에게 노출한다.
```

- [ ] **Step 7: 통과를 확인한다**

Run: `.venv\Scripts\python -m pytest tests/test_colour_axis.py -v`
Expected: PASS

- [ ] **Step 8: OpenAPI 스펙 재생성 + 전체 테스트**

Run: `.venv\Scripts\python scripts/export_openapi.py`
Run: `.venv\Scripts\python -m pytest -q`
Expected: 전부 PASS

- [ ] **Step 9: 커밋**

```bash
git add app/config.py app/models.py app/api.py docs/openapi.json tests/test_colour_axis.py
git commit -m "API: 색 게이트(min_rel_sat)를 요청 파라미터로 노출"
```

---

### Task 5: `has_chroma` — 색 축이 실제로 적용됐는지 알려주기

**Files:**
- Modify: `app/blob_detector.py:744-782` (`detect_blobs` 시그니처에 `stats` 추가), `:816-855` (재귀 호출 2곳에 전달), `:878-881` (값 기록)
- Modify: `app/api.py` (`_detect_and_score` 에서 받아 `applied_params` 에 담기)
- Test: `tests/test_colour_axis.py` (Task 4 파일에 추가), `tests/test_blob_detector.py` (단위)

**Interfaces:**
- Consumes: `detect_blobs` (기존)
- Produces: `detect_blobs(..., stats: dict | None = None)` — `stats` 를 주면 `stats["has_chroma"] = bool` 을 채운다. 반환값은 바뀌지 않는다. `applied_params["has_chroma"]`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_blob_detector.py` 끝에 추가한다:

`cv2` · `numpy as np` · `detect_blobs` 는 이 파일 맨 위에 이미 import 돼 있다. 다시 import 하지 말 것.

```python
def _monochrome_dish() -> np.ndarray:
    """완전 무채색 접시 — 세 채널이 같으면 HSV 채도가 0 이다.

    실측: 이 이미지의 ROI 채도 표준편차는 0.0 으로 BLOB_MONO_SAT_STD(2.0)
    아래이고, 검출은 1개 나온다(빈 리스트가 아니라서 반환 형식 단정이 유효하다).
    """
    grey = np.full((600, 600, 3), 120, np.uint8)
    cv2.circle(grey, (300, 300), 40, (170, 170, 170), -1)
    return grey


def test_detect_blobs_reports_has_chroma_without_changing_return():
    """stats 를 주면 색 축 적용 여부를 알려준다. 반환 형식은 그대로여야 한다.

    무채색 이미지(흑백 카메라·합성)에서는 blob_detector 가 색 게이트를 조용히
    끄는데, 지금은 호출자가 그것을 알 수 없다. 반환값에 끼워 넣으면
    detector.detect 와의 호환이 깨지므로 out-파라미터로 받는다.
    """
    stats: dict = {}
    out = detect_blobs(_monochrome_dish(), stats=stats)
    assert isinstance(out, list)
    assert out, "이 합성 접시에서는 최소 1개가 검출돼야 한다"
    for item in out:
        assert len(item) == 4, "반환은 (x, y, radius, circularity) 4-튜플이어야 한다"
    assert stats["has_chroma"] is False


def test_detect_blobs_stats_is_optional():
    """stats 를 주지 않아도 기존과 똑같이 동작해야 한다."""
    assert detect_blobs(_monochrome_dish()) == detect_blobs(_monochrome_dish())


def test_detect_blobs_reports_has_chroma_true_on_colour_dish():
    """색이 있는 접시에서는 True 여야 한다 — 늘 False 를 넣는 구현을 막는다."""
    stats: dict = {}
    detect_blobs(_dish(colony_bgr=(60, 200, 90), agar_bgr=(200, 190, 160)),
                 stats=stats)
    assert stats["has_chroma"] is True
```

`_dish` 는 이 파일에 이미 있는 헬퍼다(파일 맨 위 참조). `colony_bgr` · `agar_bgr` 을 주면 채도가 있는 합성 접시를 만든다.

`tests/test_colour_axis.py` 끝에 추가한다:

```python
def test_applied_params_reports_has_chroma():
    """UI 가 색 그룹을 잠글지 판단하는 값이다."""
    ap = _detect()["applied_params"]
    assert "has_chroma" in ap
    assert isinstance(ap["has_chroma"], bool)


def test_colour_sample_reports_chroma_true():
    """sample/ 의 컬러 접시는 색 축이 적용돼야 한다."""
    assert _detect()["applied_params"]["has_chroma"] is True
```

- [ ] **Step 2: 실패를 확인한다**

Run: `.venv\Scripts\python -m pytest tests/test_blob_detector.py -k has_chroma -v`
Expected: FAIL — `TypeError: detect_blobs() got an unexpected keyword argument 'stats'`

- [ ] **Step 3: `detect_blobs` 에 out-파라미터를 추가한다**

`app/blob_detector.py` 의 `detect_blobs` 시그니처 마지막 인자 `plate_type: str = "petri",` **뒤에** 추가한다:

```python
    # 호출자가 dict 를 주면 검출 중 알아낸 사실을 채워 준다. 반환값에 끼워 넣지
    # 않는 이유는 detector.detect 와 형식이 같아야 하기 때문이다(모듈 docstring).
    stats: dict | None = None,
```

`has_chroma` 를 계산하는 곳(`inside = sat_full[roi > 0]` 아래) 에서 기록한다:

```python
    inside = sat_full[roi > 0]
    has_chroma = (inside.size > 0
                  and float(inside.std()) >= config.BLOB_MONO_SAT_STD)
    sat = sat_full if has_chroma else None
    if stats is not None:
        # 무채색이면 색 게이트와 색 할인이 모두 무동작이 된다. 호출자가 그것을
        # 모르면 색 슬라이더를 움직여도 결과가 안 바뀌는 이유를 알 수 없다.
        stats["has_chroma"] = bool(has_chroma)
```

`adaptive_scale` 분기의 재귀 호출 **두 곳** 모두 `plate_type=plate_type,` 뒤에 `stats=stats,` 를 추가한다 (probe 호출과 재검출 호출).

- [ ] **Step 4: 통과를 확인한다**

Run: `.venv\Scripts\python -m pytest tests/test_blob_detector.py -v`
Expected: PASS

- [ ] **Step 5: `applied_params` 에 담는다**

`app/api.py` 의 `_detect_and_score` 에서 `detect_blobs` 호출을 `stats` 와 함께 하고, 결과를 `resolved` 에 넣는다. `resolved` 가 그대로 `applied_params` 가 되므로 이것만으로 응답에 실린다.

```python
    stats: dict = {}
    circles = detect_blobs(
        img,
        min_t=resolved["min_t"],
        ...
        min_rel_sat=resolved["min_rel_sat"],
        stats=stats,
    )
    # 무채색 이미지에서는 색 축이 무동작이다. UI 가 색 그룹을 잠그고 이유를
    # 표시할 수 있도록 판정 결과를 그대로 돌려준다.
    resolved["has_chroma"] = stats.get("has_chroma", True)
```

- [ ] **Step 6: 통과를 확인한다**

Run: `.venv\Scripts\python -m pytest tests/test_colour_axis.py -v`
Expected: PASS

- [ ] **Step 7: 전체 테스트**

`applied_params` 는 `DetectResponse.applied_params: dict` 라 스키마가 바뀌지 않는다. 그래도 스펙을 재생성해 확인한다.

Run: `.venv\Scripts\python scripts/export_openapi.py`
Run: `.venv\Scripts\python -m pytest -q`
Expected: 전부 PASS

- [ ] **Step 8: 커밋**

```bash
git add app/blob_detector.py app/api.py docs/openapi.json tests/test_blob_detector.py tests/test_colour_axis.py
git commit -m "API: 색 축이 실제로 적용됐는지 has_chroma 로 알려줌"
```

---

### Task 6: 분리 축 측정 곡선을 config 에 갱신

**Files:**
- Modify: `app/config.py:158-194` (`BLOB_WATERSHED_SPLIT` · `BLOB_SPLIT_AREA_RATIO`), `:208` (`BLOB_COLOUR_CREDIT_MAX`)
- Test: `tests/test_split_defaults.py`

**Interfaces:**
- Consumes: 없음 (상수와 주석만)
- Produces: 없음 (기본값은 그대로 유지)

이 작업은 **동작을 바꾸지 않는다.** 기존 주석의 곡선이 `candidate_source="union"` 도입 이전 기준이라 현재 설정에서 재측정한 값으로 갱신하고, 기본값이 조용히 옮겨지지 않게 테스트로 묶는다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_split_defaults.py`:

```python
"""분리·색 축 기본값을 실측 최적점에 고정한다.

두 값 모두 2026-08-12 에 현재 설정에서 재측정했다. 이전 곡선은
candidate_source="union" 도입 전 기준이라 무효였다. 기본값이 조용히
움직이면 성적이 내려가므로 상수로 묶는다.
"""
from app import config


def test_split_area_ratio_default_is_the_measured_optimum():
    """1.5 가 전역 F1 최고점이다 (78.80).

    실측: 0.8 → 78.29, 1.0 → 78.31, 1.2 → 78.58, **1.5 → 78.80**,
    2.0 → 77.90, 3.0 → 77.80, watershed 끔 → 77.87.
    양쪽으로 내려가는 진짜 봉우리다.
    """
    assert config.BLOB_SPLIT_AREA_RATIO == 1.5


def test_watershed_split_stays_on():
    """끄면 재현율이 75.7% → 71.1% 로 내려간다 (F1 78.80 → 77.87)."""
    assert config.BLOB_WATERSHED_SPLIT is True


def test_colour_credit_stays_off():
    """현재 설정에서는 켜면 네 그룹 전부 나빠진다.

    2배에서 정밀도 82.20% → 59.82%, F1 78.80 → 68.14.
    그룹별 F1: lower 83.2→67.3, bright 80.7→74.6, dark 83.7→70.0,
    vague 61.6→52.7. config 주석의 "vague 26.1→40.9" 는 union 도입 이전
    수치이며, 그 이득은 이미 후보 생성이 가져갔다.
    """
    assert config.BLOB_COLOUR_CREDIT_MAX == 1.0
```

- [ ] **Step 2: 실행해 현재 상태를 확인한다**

Run: `.venv\Scripts\python -m pytest tests/test_split_defaults.py -v`
Expected: PASS — 기본값이 이미 그 값이므로 통과한다. 이 테스트는 회귀 방어용이고, 통과하는 것이 정상이다.

- [ ] **Step 3: `BLOB_SPLIT_AREA_RATIO` 주석을 갱신한다**

`app/config.py` 의 `BLOB_SPLIT_AREA_RATIO = 1.5` 주석 블록 **맨 앞**에 다음을 추가한다 (기존 내용은 지우지 말고 그 아래에 "(아래는 union 도입 이전 측정이다)" 를 한 줄 넣어 구분한다):

```python
BLOB_SPLIT_AREA_RATIO = 1.5    # 자연 윤곽 면적이 후보 기대 면적(π r²)의 이 배를
                               # 넘으면 병합으로 보고 watershed 분리를 적용한다.
                               # 낮출수록 적극적으로 나눈다.
                               #
                               # 재측정 (2026-08-12, 현재 설정) — 1.5 가 봉우리다:
                               #   조건   정밀도  재현율    F1
                               #   0.8    80.50%  76.2%  78.29
                               #   1.0    80.66%  76.1%  78.31
                               #   1.2    81.18%  76.1%  78.58
                               #   1.5    82.20%  75.7%  78.80  ← 현재·최적
                               #   2.0    83.41%  73.1%  77.90
                               #   3.0    85.66%  71.3%  77.80
                               #   끔     86.07%  71.1%  77.87
                               #
                               # **그룹별 최적은 정반대 방향에 있다:**
                               #          lower bright  dark vague
                               #   0.8     83.0   80.9  82.1  59.9  ← bright 최고
                               #   1.5     83.2   80.7  83.7  61.6  ← dark 최고
                               #   3.0     84.7   76.8  83.4  63.9
                               #   끔      85.2   76.9  83.1  63.9  ← lower·vague 최고
                               # 전역 최적 1.5 는 네 그룹 중 셋에서 틀린 값이고,
                               # 그 타협의 대가가 lower -2.0 · vague -2.3 F1 이다.
                               # 전역 기본값 하나로 수렴하지 않으므로 이 축은
                               # DetectRequest.split_area_ratio 로 노출해 접시마다
                               # 조절하게 한다.
                               #
                               # 분리를 더 파고들 가치는 제한적이다. 놓친 정답
                               # 459개 중 다른 검출의 원반 안에 있는 것은 78개
                               # (17.0%)뿐이고 나머지 381개는 아무 검출도 없는
                               # 곳에 있다 — 뭉친 게 아니라 아예 못 본 것이다.
                               # 분리를 완벽히 해내도 재현율 천장이 79.8%
                               # (현재 75.7%). vague 는 천장 자체가 58.4% 다.
                               # 그래서 오목점 분할 등 새 분리 알고리즘은
                               # 우선순위가 낮다.
                               #
                               # (아래는 union 도입 이전 측정이다 — 기준선이
                               #  정밀도 91~93% 대였다.)
```

- [ ] **Step 4: `BLOB_COLOUR_CREDIT_MAX` 주석을 갱신한다**

`app/config.py` 의 `BLOB_COLOUR_CREDIT_MAX = 1.0` 주석 블록 **맨 앞**에 추가한다:

```python
BLOB_COLOUR_CREDIT_MAX = 1.0   # 색 신호가 t 요구치를 낮춰주는 최대 배율. 1.0 = 끔.
                               #
                               # **재측정 (2026-08-12): 켜면 네 그룹 전부 나빠진다.**
                               #   2.0 → 정밀도 59.82% / 재현율 79.2% / F1 68.14
                               #   4.0 → 46.07% / 81.1% / 58.75
                               #   그룹별 F1 (기본 → 2.0):
                               #     lower 83.2→67.3  bright 80.7→74.6
                               #     dark  83.7→70.0  vague  61.6→52.7
                               # 아래 옛 주석의 "vague 26.1→40.9" 는
                               # candidate_source="union" 도입 **이전** 수치다.
                               # 그 이득은 이미 후보 생성이 가져갔고, 지금 이 축은
                               # 정밀도만 깎는다. 그래서 오퍼레이터 UI 에도
                               # 노출하지 않는다.
```

- [ ] **Step 5: `BLOB_WATERSHED_SPLIT` 주석에 재측정을 한 줄 추가한다**

`BLOB_WATERSHED_SPLIT = True` 주석 블록 끝에 붙인다:

```python
                               # 재측정 (2026-08-12, 현재 설정): 끄면
                               # 82.20%/75.7% → 86.07%/71.1%, F1 78.80 → 77.87.
                               # 정밀도는 오르지만 재현율을 4.6%p 잃는다.
                               # 단 lower·vague 그룹은 끄는 쪽이 F1 최고다
                               # (BLOB_SPLIT_AREA_RATIO 주석의 그룹별 표 참조).
```

- [ ] **Step 6: 전체 테스트**

Run: `.venv\Scripts\python -m pytest -q`
Expected: 전부 PASS

- [ ] **Step 7: 커밋**

```bash
git add app/config.py tests/test_split_defaults.py
git commit -m "분리·색 축 측정 곡선을 현재 설정 기준으로 갱신"
```

---

### Task 7: 문서 — 4축 분류와 프론트 연동 계약

**Files:**
- Modify: `docs/detection_parameters.md`
- Modify: `docs/react-integration.md`
- Modify: `README.md` (파라미터 목록이 있으면 4축 표기 반영)

**Interfaces:**
- Consumes: Task 2~5 의 신규 필드 (`parent_id` · `exclude_nested` · `min_rel_sat` · `has_chroma`)
- Produces: 없음 (문서)

- [ ] **Step 1: 현재 문서 구조를 읽는다**

Run: `.venv\Scripts\python -c "print(open('docs/detection_parameters.md', encoding='utf-8').read())"`
Run: `.venv\Scripts\python -c "print(open('docs/react-integration.md', encoding='utf-8').read())"`

기존 절 구성과 말투를 확인한다. 문서를 새로 쓰지 말고 **4축 분류 절을 추가하고 기존 표에 노출 등급 열을 더한다.**

- [ ] **Step 2: `docs/detection_parameters.md` 에 4축 절을 추가한다**

파라미터를 네 축으로 묶고 노출 등급을 붙인 표를 넣는다. 등급은 세 단계다 — `오퍼레이터`(항상 보임) · `접시별`(펼쳐서 조절) · `전문가`(UI 에 노출 안 함).

```markdown
## 선별 기준 네 축

오퍼레이터가 보는 화면은 이 네 축으로 묶는다. 감도(`sensitivity`)는 축에
넣지 않고 **마스터 knob** 으로 위에 둔다 — 네 축 전부에 영향을 주고, 매일
만지는 유일한 값이다.

| 축 | 파라미터 | 등급 | 비고 |
|---|---|---|---|
| (마스터) | `sensitivity` | 오퍼레이터 | `min_t` 로 매핑. raw 를 직접 보내지 말 것 |
| 크기 | `min_diam_frac` · `max_diam_frac` | 접시별 | 접시 지름 대비 비율이라 카메라·해상도 무관 |
| 모양 | `min_roundness` | 접시별 | 주된 모양 판정 |
| 모양 | `min_solidity` | 접시별 | 오목한 얼룩·긁힘 배제 |
| 모양 | `min_circularity` | 전문가 | 기본 0(기각) — 둘레 기반이라 경계 거칠기에 민감 |
| 모양 | `min_fill` | 전문가 | 계수(CFU) 용도 전용 |
| 색상 | `polarity` | 접시별 | 자동 판정이 실측 39/39 정확 |
| 색상 | `min_rel_sat` | 접시별 | 오검출을 걷어내는 가장 강한 레버 |
| 색상 | `colour_credit` | 전문가 | **현재 설정에서 전 그룹 손해** — 노출하지 않음 |
| 분리 | `split_area_ratio` | 접시별 | 그룹별 최적이 정반대 |
| 분리 | `watershed_split` | 접시별 | 분리 슬라이더 맨 끝 "나누지 않음" 으로 흡수 |
| 분리 | `exclude_nested` | 접시별 | 기본 끔 |
| (기타) | `work_size` · `candidate_source` · `threshold_levels` · `adaptive_scale` · raw `min_t` | 전문가 | `models.py` 가 "단독 변경 금지" 라고 명시한 축들 |
| (개발용) | `image_path` · `save_annotated` · `return_image` | 노출 금지 | 운영 UI 에서 제외 |

### 축을 건드리는 순서

실측상 효율이 좋은 순서는 **감도 → 크기 → 분리 → 색상 → 모양** 이다.
모양 축은 완화보다 감도를 내리는 쪽이 더 많이 맞힌다 — 같은 정밀도 82.8%
에서 재현율 74.7% 대 72.5%.
```

- [ ] **Step 3: `docs/react-integration.md` 에 신규 필드 사용법을 추가한다**

```markdown
## 중첩 검출 — `parent_id`

`Colony.parent_id` 는 이 검출을 감싸는 더 큰 검출의 `id` 다(없으면 `null`).
파라미터 없이 항상 계산되므로 별도 요청이 필요 없다.

```ts
// 중첩 검출을 흐리게 표시하고 개수에서 뺀다
const nested = colonies.filter((c) => c.parent_id !== null)
const topLevel = colonies.filter((c) => c.parent_id === null)
```

서버에서 아예 빼려면 `exclude_nested: true` 를 보낸다. 그러면 `count` 가
줄고 남는 검출의 `parent_id` 는 모두 `null` 이며 `id` 는 1부터 다시 매겨진다.

**기본값은 꺼짐이다.** 실측에서 제외 대상 30개 중 16개가 정답이었다 —
큰 콜로니 옆의 진짜 작은 콜로니가 부모 반지름 과대추정으로 삼켜진 경우와,
부모가 오검출이고 자식이 유일한 정답인 경우가 섞여 있다. 자동으로 켜지
말고 오퍼레이터가 화면을 보고 켜게 할 것.

## 색 축이 적용됐는지 — `has_chroma`

`applied_params.has_chroma` 가 `false` 면 서버가 색 축을 끈 것이다
(흑백 카메라·합성 이미지 등 채도가 없는 입력). 그때 `min_rel_sat` 과
`colour_credit` 은 무동작이므로, **색상 그룹을 잠그고 이유를 표시해야 한다.**
그러지 않으면 사용자가 슬라이더를 움직여도 결과가 안 바뀌는 이유를 알 수 없다.

```tsx
<fieldset disabled={!applied.has_chroma}>
  {!applied.has_chroma && (
    <p>이 이미지는 채도가 없어 색 기준이 적용되지 않습니다.</p>
  )}
  {/* polarity, min_rel_sat 컨트롤 */}
</fieldset>
```

## 조절 화면 구성

네 축을 접이식 그룹으로 두고, 각 그룹이 접힌 상태에서도 현재 값 요약을
보여준다. 다섯 가지 규칙을 지킬 것.

1. **크기 축에 검출 지름 히스토그램**을 그리고 크기 창을 띠로 겹친다.
   `colonies` 의 `radius × 2 ÷ 접시 지름` 분포를 그리면 오퍼레이터가 숫자를
   추측하지 않고 분포를 보고 자를 수 있다.
2. **파라미터를 바꾸면 화면 결과가 낡는다.** 크기 축과 `exclude_nested` 는
   클라이언트에서 근사 미리보기가 가능하지만 나머지는 서버 재검출이 필요하다.
   오버레이를 흐리게 하고 "다시 검출" 을 강조할 것.
3. **기본값에서 벗어난 축에 표시를 붙이고** 되돌리기를 제공한다.
4. **`applied_params` 를 화면에 표시한다.** `sensitivity → min_t` 매핑을
   클라이언트에서 재계산하지 말 것 — 서버가 적용한 값이 그대로 온다.
5. 프리셋은 두지 않는다. 네 축이 있으면 중복이고, 기준선은
   "균형 · 서버 기본값" 한 줄로 고정 표시한다.
```

- [ ] **Step 4: 문서에 남은 낡은 서술을 고친다**

`docs/detection_parameters.md` 의 "잡음·채도" 줄에서 `BLOB_MIN_REL_SAT` 이
내부 상수로 소개돼 있다. 이제 요청 파라미터이므로 그 줄에서 빼고 위 4축 표를
가리키게 한다.

Run: `.venv\Scripts\python -m pytest -q`
Expected: 전부 PASS (문서만 고쳤으므로 영향 없음)

- [ ] **Step 5: 커밋**

```bash
git add docs/detection_parameters.md docs/react-integration.md README.md
git commit -m "docs: 선별 기준을 네 축으로 정리하고 프론트 연동 계약 추가"
```

---

## 이 계획에서 제외한 것

스펙의 "이 범위에서 제외하는 것" 을 그대로 따른다. 각각 별건이다.

| 항목 | 이유 |
|---|---|
| 반지름 클리핑 | 오검출 자식이 정상 부모의 반지름을 파괴 (기각) |
| 새 분리 알고리즘(오목점 분할 등) | 천장이 재현율 +4.1%p, 정밀도 리스크 큼 |
| `min_rel_sat` 기본값 3.0 상향 | 전역 F1 은 오르지만(78.80→79.03) 기본값 변경은 별건 |
| 유형 B 의 근본 원인 | `radius_mode="max"` 재설계가 필요 |
| 접시 종류 자동 판정 → 축 자동 설정 | 그룹 판정기를 새로 만드는 일 |
| React 프론트엔드 구현 | 이 저장소는 Python 검출 서버다. UI 계약은 Task 7 로 문서화하고, 화면은 목업으로 전달했다 |

## 자체 점검

**스펙 커버리지.** 설계 A(응답 확장) → Task 2·5. B(신규 파라미터) → Task 3·4.
C(config 상수) → Task 2. D(구현 위치) → Task 1~5. E(4축 UI) → Task 7 문서화
(구현은 프론트 저장소). 테스트 절의 8개 항목 → Task 1(단위 5개) · Task 2·3
(중첩 API) · Task 4(범위·방향성) · Task 5(무채색·applied_params) ·
Task 2~5 각 Step 의 OpenAPI 검증. 문서 절 → Task 6(config 주석) · Task 7.

**타입 일관성.** `find_parents` 는 Task 1에서 0-기반 인덱스를 반환하고 Task 2가
`+1` 로 `id` 에 맞춘다. `stats` 는 Task 5에서만 쓰이고 키는 `"has_chroma"` 하나다.
`applied_params` 키 이름(`exclude_nested` · `min_rel_sat` · `has_chroma`)이
테스트·구현·문서에서 모두 같다.

**주의할 결합.** `models.py` 를 고치는 Task 2·3·4 는 각각 그 작업 안에서
`scripts/export_openapi.py` 를 돌려야 한다. 미루면 `test_openapi_spec.py` 가
빨간 상태로 남아 다음 작업의 기준선이 흐려진다.
