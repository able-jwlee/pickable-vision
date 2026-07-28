# Operator Parameters Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add operator-friendly 0~100 scale parameters (`sensitivity`, `min_size`, `max_size`, `edge_margin`) to `POST /detect` and `POST /detect/preview`, backed by pure mapping functions and reported back in the response as `applied_params`.

**Architecture:** New optional abstract fields on `DetectRequest`. When any of them is set, the corresponding raw parameter (`threshold_offset`, `min_area`, `max_area`, or `config.PICK_EDGE_MARGIN`) is overridden by the mapping function output. All backwards-compatible: existing raw-field clients keep working byte-for-byte. `DetectResponse` gains an `applied_params` dict so callers can see the exact values used.

**Tech Stack:** FastAPI 0.115, Pydantic v2, pytest, existing venv (`.venv/Scripts/python.exe` on Windows).

## Global Constraints

- **Spec source of truth:** `docs/superpowers/specs/2026-07-28-operator-parameters-design.md` — mapping tables in §4.2 are authoritative.
- **No new package dependencies.** Only stdlib + existing `requirements.txt`.
- **Backwards compatibility is mandatory.** Every existing test in `tests/` must pass without modification. Existing default request (no new fields) must produce a byte-identical colony list to today.
- **Python version:** whatever the current venv uses (3.10+). Use `X | None` union syntax already established in `app/models.py`.
- **Test runner:** `.venv/Scripts/python -m pytest -v` (Windows path — WSL users can use `.venv/Scripts/python.exe -m pytest -v`).
- **Commit style:** short imperative, no scope prefix. Match `60a877c init` style — one line, lowercase, no trailing period.

---

## File Structure

**New files:**
- `app/param_mapping.py` — Four pure functions mapping 0~100 → raw CV values. Anchor points at slider=default match the current server defaults (see §4.2 of spec).
- `tests/test_param_mapping.py` — Unit tests: anchor values, extremes, monotonicity.

**Modified files:**
- `app/models.py` — Add 4 optional `int` fields (`sensitivity`, `min_size`, `max_size`, `edge_margin`) to `DetectRequest`. Add `applied_params: dict` to `DetectResponse`.
- `app/api.py` — Add helper `_resolve_params(req)` returning the raw values actually used. Update both `detect_colonies` and `detect_preview` to (a) call resolver, (b) pass resolved values to `detect()` / `pick_region()`, (c) include `applied_params` in the response.
- `tests/test_detect_endpoint.py` — Add regression, priority, and direction tests. Do NOT modify existing tests.
- `README.md` — Add one paragraph + example JSON for the new fields.
- `docs/detection_parameters.md` — Add "오퍼레이터용 0~100 스케일 필드" section with mapping table and reference to the mockup HTML.

**Untouched:**
- `app/detector.py`, `app/scoring.py`, `app/annotate.py`, `app/image_io.py`, `app/config.py`. All existing behavior preserved.
- `docs/mockup/operator-ui.html` — already sends the payload the server will accept once this plan is implemented; no changes needed.

---

## Task 1: Create `app/param_mapping.py` with unit tests

**Files:**
- Create: `app/param_mapping.py`
- Create: `tests/test_param_mapping.py`

**Interfaces:**
- Consumes: `math.pi` from stdlib. No project imports.
- Produces (used by Task 4):
  - `sensitivity_to_offset(v: int) -> int`
  - `min_size_to_area(v: int) -> float`
  - `max_size_to_area(v: int) -> float`
  - `edge_to_margin_px(v: int) -> int`

- [ ] **Step 1: Write the failing test**

Create `tests/test_param_mapping.py`:

```python
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
    # max_size=80 should give ~max_area=5000 (current DEFAULT_MAX_AREA)
    assert max_size_to_area(80) == pytest.approx(5000.0, rel=0.15)


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_param_mapping.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.param_mapping'`

- [ ] **Step 3: Write minimal implementation**

Create `app/param_mapping.py`:

```python
"""오퍼레이터용 0~100 스케일 → CV 원본값 매핑.

각 함수는 슬라이더 값(0~100)을 받아 검출기 내부 파라미터로 변환한다.
스펙 §4.2 매핑 표의 앵커값을 만족하도록 설계됨.
"""
import math


def sensitivity_to_offset(v: int) -> int:
    """감도 0~100 → threshold_offset. 50이 현재 default(+7)에 앵커.

    0~50 구간 linear: -3 → +7
    50~100 구간 linear: +7 → +15
    """
    if v <= 50:
        return round(-3 + (v / 50) * 10)
    return round(7 + ((v - 50) / 50) * 8)


def min_size_to_area(v: int) -> float:
    """최소 크기 0~100 → min_area. 20이 현재 default(≈6)에 앵커.

    r_min = 1 + (v/100)² · 9  (비선형 — 슬라이더 앞부분에서 세밀 조정)
    min_area = π · r_min²
    """
    r = 1 + (v / 100) ** 2 * 9
    return math.pi * r * r


def max_size_to_area(v: int) -> float:
    """최대 크기 0~100 → max_area. 80이 현재 default(≈5000)에 앵커.

    r_max = 10 + (v/100) · 40  (linear)
    max_area = π · r_max²
    """
    r = 10 + (v / 100) * 40
    return math.pi * r * r


def edge_to_margin_px(v: int) -> int:
    """벽 여백 0~100 → 픽셀. 40이 현재 default(60px)에 앵커.

    edge_margin = v · 1.5  (linear, 0~150px)
    """
    return round(v * 1.5)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_param_mapping.py -v`
Expected: PASS (10+ tests, all green)

- [ ] **Step 5: Commit**

```bash
git add app/param_mapping.py tests/test_param_mapping.py
git commit -m "add operator param mapping module"
```

---

## Task 2: Add abstract fields to `DetectRequest`

**Files:**
- Modify: `app/models.py` (add 4 fields to `DetectRequest` class)
- Modify: `tests/test_models.py` (add validation tests)

**Interfaces:**
- Consumes: nothing new.
- Produces (used by Task 4):
  - `DetectRequest.sensitivity: int | None`
  - `DetectRequest.min_size: int | None`
  - `DetectRequest.max_size: int | None`
  - `DetectRequest.edge_margin: int | None`
  - All default to `None`. Range `[0, 100]` enforced by Pydantic.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_models.py` (append after existing tests):

```python
from pydantic import ValidationError

from app.models import DetectRequest


def test_detect_request_accepts_abstract_fields():
    req = DetectRequest(
        image="Zm9v",  # base64 dummy
        sensitivity=50,
        min_size=20,
        max_size=80,
        edge_margin=40,
    )
    assert req.sensitivity == 50
    assert req.min_size == 20
    assert req.max_size == 80
    assert req.edge_margin == 40


def test_detect_request_abstract_fields_default_to_none():
    req = DetectRequest(image="Zm9v")
    assert req.sensitivity is None
    assert req.min_size is None
    assert req.max_size is None
    assert req.edge_margin is None


def test_detect_request_rejects_out_of_range_abstract_field():
    with pytest.raises(ValidationError):
        DetectRequest(image="Zm9v", sensitivity=101)
    with pytest.raises(ValidationError):
        DetectRequest(image="Zm9v", min_size=-1)
```

If `pytest` is not already imported at the top of `tests/test_models.py`, add `import pytest`.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_models.py -v -k abstract`
Expected: FAIL — `DetectRequest.sensitivity` doesn't exist.

- [ ] **Step 3: Write minimal implementation**

Edit `app/models.py`. Add the 4 fields inside `class DetectRequest`, immediately after `annotate: Literal["all", "pick"] = "all"` and before the `@field_validator`:

```python
    # 오퍼레이터용 0~100 추상 스케일 (스펙 §4.2). 있으면 대응하는 raw 필드보다 우선.
    # None이면 기존 raw 필드(threshold_offset, min_area, max_area) 또는 config default를 사용.
    sensitivity: int | None = Field(None, ge=0, le=100)
    min_size:    int | None = Field(None, ge=0, le=100)
    max_size:    int | None = Field(None, ge=0, le=100)
    edge_margin: int | None = Field(None, ge=0, le=100)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_models.py -v`
Expected: PASS (all model tests, including 3 new ones)

- [ ] **Step 5: Confirm no regression**

Run: `.venv/Scripts/python -m pytest -v`
Expected: PASS (entire suite)

- [ ] **Step 6: Commit**

```bash
git add app/models.py tests/test_models.py
git commit -m "add operator 0-100 fields to DetectRequest"
```

---

## Task 3: Add `applied_params` to `DetectResponse`

**Files:**
- Modify: `app/models.py` (add field to `DetectResponse`)
- Modify: `app/api.py` (populate the field — with raw values only for now; mapping wired in Task 4)
- Modify: `tests/test_detect_endpoint.py` (add response-shape test)

**Interfaces:**
- Consumes: nothing new.
- Produces (used by Task 4):
  - `DetectResponse.applied_params: dict[str, object]` — dict with keys `threshold_offset`, `min_area`, `max_area`, `pick_edge_margin`, `split_touching`, `pick_top_n`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_detect_endpoint.py` (append):

```python
def test_detect_returns_applied_params():
    resp = client.post(
        "/detect",
        json={"image": _synthetic_b64(), "min_area": 50, "mask_walls": False},
    )
    body = resp.json()
    assert "applied_params" in body
    ap = body["applied_params"]
    # raw 필드 그대로 반영되는지 확인
    assert ap["min_area"] == 50
    # 요청에 없던 값은 서버 default가 담김
    assert "threshold_offset" in ap
    assert "max_area" in ap
    assert "pick_edge_margin" in ap
    assert "split_touching" in ap
    assert "pick_top_n" in ap
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_detect_endpoint.py::test_detect_returns_applied_params -v`
Expected: FAIL — `KeyError: 'applied_params'` or assertion error (field missing from response body).

- [ ] **Step 3: Add field to model**

Edit `app/models.py` — add to `DetectResponse`:

```python
class DetectResponse(BaseModel):
    width: int
    height: int
    count: int
    colonies: list[Colony]
    # save_annotated=true일 때 저장된 이미지 경로, 아니면 null
    annotated_path: str | None = None
    # 검출에 실제 적용된 raw 파라미터 dict (튜닝 재현·이슈 리포트용)
    applied_params: dict = {}
```

- [ ] **Step 4: Populate `applied_params` in api.py**

Edit `app/api.py`. Update `detect_colonies` to construct and pass `applied_params`. Replace the current function body starting with `def detect_colonies` with:

```python
@router.post("/detect", response_model=DetectResponse)
def detect_colonies(req: DetectRequest) -> DetectResponse:
    img = _load_image(req)
    height, width = img.shape[:2]
    colonies = _detect_and_score(img, req)

    annotated_path: str | None = None
    if req.save_annotated:
        annotated = draw_pick_targets(img, colonies, mode=req.annotate)
        saved = save_annotated(annotated, config.OUTPUT_DIR, _output_name(req))
        annotated_path = str(saved.resolve())

    return DetectResponse(
        width=width,
        height=height,
        count=len(colonies),
        colonies=colonies,
        annotated_path=annotated_path,
        applied_params={
            "threshold_offset": req.threshold_offset,
            "min_area": req.min_area,
            "max_area": req.max_area,
            "pick_edge_margin": config.PICK_EDGE_MARGIN,
            "split_touching": req.split_touching,
            "pick_top_n": req.pick_top_n,
        },
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_detect_endpoint.py -v`
Expected: PASS (all endpoint tests, including new one)

- [ ] **Step 6: Commit**

```bash
git add app/models.py app/api.py tests/test_detect_endpoint.py
git commit -m "return applied_params in detect response"
```

---

## Task 4: Wire abstract → raw mapping in `api.py`

**Files:**
- Modify: `app/api.py` (add `_resolve_params` helper, wire into both endpoints)
- Modify: `app/detector.py` — **no change** (still called with raw values).
- Modify: `tests/test_detect_endpoint.py` (add priority + regression tests)

**Interfaces:**
- Consumes:
  - `sensitivity_to_offset`, `min_size_to_area`, `max_size_to_area`, `edge_to_margin_px` from `app.param_mapping` (Task 1).
  - `DetectRequest` fields `sensitivity`, `min_size`, `max_size`, `edge_margin` (Task 2).
- Produces: no new public API. Internal helper `_resolve_params(req: DetectRequest) -> dict`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_detect_endpoint.py`:

```python
def test_abstract_sensitivity_overrides_threshold_offset():
    # sensitivity=100 → threshold_offset should be 15, ignoring raw field
    resp = client.post(
        "/detect",
        json={
            "image": _synthetic_b64(),
            "mask_walls": False,
            "threshold_offset": 0,   # should be OVERRIDDEN
            "sensitivity": 100,
        },
    )
    ap = resp.json()["applied_params"]
    assert ap["threshold_offset"] == 15


def test_abstract_min_size_overrides_min_area():
    resp = client.post(
        "/detect",
        json={
            "image": _synthetic_b64(),
            "mask_walls": False,
            "min_area": 999,          # should be OVERRIDDEN
            "min_size": 20,
        },
    )
    ap = resp.json()["applied_params"]
    # min_size=20 → min_area ≈ 5.81 (current default)
    assert abs(ap["min_area"] - 5.81) < 0.5


def test_abstract_edge_margin_overrides_config():
    resp = client.post(
        "/detect",
        json={
            "image": _synthetic_b64(),
            "mask_walls": True,
            "edge_margin": 100,       # → 150px
        },
    )
    ap = resp.json()["applied_params"]
    assert ap["pick_edge_margin"] == 150


def test_default_abstract_matches_raw_defaults():
    """새 필드 미지정 요청과 abstract default(50/20/80/40) 요청이 같은 결과."""
    raw = client.post(
        "/detect",
        json={"image": _synthetic_b64(), "min_area": 50, "mask_walls": False},
    ).json()
    abstract = client.post(
        "/detect",
        json={
            "image": _synthetic_b64(),
            "mask_walls": False,
            "sensitivity": 50,
            "max_size": 80,
            "edge_margin": 40,
            # min_size는 지정 안 함 — 기존 min_area=50과 비교
            "min_area": 50,
        },
    ).json()
    assert abstract["count"] == raw["count"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_detect_endpoint.py -v -k "abstract or default_abstract"`
Expected: FAIL — `applied_params["threshold_offset"]` is still 0 (raw not overridden yet).

- [ ] **Step 3: Add resolver + wire into endpoints**

Edit `app/api.py`. Add imports at top:

```python
from app.param_mapping import (
    edge_to_margin_px,
    max_size_to_area,
    min_size_to_area,
    sensitivity_to_offset,
)
```

Add helper right below `_load_image`:

```python
def _resolve_params(req: DetectRequest) -> dict:
    """추상 0~100 필드가 지정되면 raw로 매핑, 아니면 기존 raw/config 유지.

    반환 dict는 응답의 applied_params가 된다.
    """
    threshold_offset = (
        sensitivity_to_offset(req.sensitivity)
        if req.sensitivity is not None else req.threshold_offset
    )
    min_area = (
        min_size_to_area(req.min_size)
        if req.min_size is not None else req.min_area
    )
    max_area = (
        max_size_to_area(req.max_size)
        if req.max_size is not None else req.max_area
    )
    pick_edge_margin = (
        edge_to_margin_px(req.edge_margin)
        if req.edge_margin is not None else config.PICK_EDGE_MARGIN
    )
    return {
        "threshold_offset": threshold_offset,
        "min_area": min_area,
        "max_area": max_area,
        "pick_edge_margin": pick_edge_margin,
        "split_touching": req.split_touching,
        "pick_top_n": req.pick_top_n,
    }
```

Rewrite `_detect_and_score` to accept and use resolved values:

```python
def _detect_and_score(
    img: np.ndarray, req: DetectRequest, resolved: dict
) -> list[Colony]:
    """검출 → 피킹 적합도 점수화 → Colony 리스트."""
    circles = detect(
        img,
        min_area=resolved["min_area"],
        max_area=resolved["max_area"],
        min_circularity=req.min_circularity,
        invert=req.invert,
        tophat_kernel=req.tophat_kernel,
        mask_walls=req.mask_walls,
        threshold_offset=resolved["threshold_offset"],
        split_touching=resolved["split_touching"],
    )
    geom = [
        {"x": x, "y": y, "radius": r, "circularity": c}
        for x, y, r, c in circles
    ]
    pick_mask = (
        pick_region(img, edge_margin=resolved["pick_edge_margin"])
        if req.mask_walls
        else None
    )
    scores = score_colonies(geom, top_n=resolved["pick_top_n"], pick_mask=pick_mask)
    return [
        Colony(
            id=i + 1,
            x=x,
            y=y,
            radius=r,
            circularity=c,
            score=scores[i]["score"],
            pickable=scores[i]["pickable"],
        )
        for i, (x, y, r, c) in enumerate(circles)
    ]
```

Update both endpoints. Replace `detect_colonies`:

```python
@router.post("/detect", response_model=DetectResponse)
def detect_colonies(req: DetectRequest) -> DetectResponse:
    img = _load_image(req)
    height, width = img.shape[:2]
    resolved = _resolve_params(req)
    colonies = _detect_and_score(img, req, resolved)

    annotated_path: str | None = None
    if req.save_annotated:
        annotated = draw_pick_targets(img, colonies, mode=req.annotate)
        saved = save_annotated(annotated, config.OUTPUT_DIR, _output_name(req))
        annotated_path = str(saved.resolve())

    return DetectResponse(
        width=width,
        height=height,
        count=len(colonies),
        colonies=colonies,
        annotated_path=annotated_path,
        applied_params=resolved,
    )
```

Replace `detect_preview`:

```python
@router.post("/detect/preview", response_model=PreviewResponse)
def detect_preview(req: DetectRequest) -> PreviewResponse:
    img = _load_image(req)
    resolved = _resolve_params(req)
    colonies = _detect_and_score(img, req, resolved)
    annotated = draw_pick_targets(img, colonies, mode=req.annotate)
    if req.save_annotated:
        save_annotated(annotated, config.OUTPUT_DIR, _output_name(req))
    return PreviewResponse(count=len(colonies), image=encode_png_base64(annotated))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_detect_endpoint.py -v`
Expected: PASS (all endpoint tests, new priority tests included)

- [ ] **Step 5: Confirm the whole suite is green**

Run: `.venv/Scripts/python -m pytest -v`
Expected: PASS — including untouched `test_detector.py`, `test_scoring.py`, `test_real_image.py`, etc. Backwards compat verified.

- [ ] **Step 6: Commit**

```bash
git add app/api.py tests/test_detect_endpoint.py
git commit -m "map operator params through resolver"
```

---

## Task 5: Direction tests with the real fixture

**Files:**
- Modify: `tests/test_detect_endpoint.py` (add 3 direction tests using `agar_sample.jpg`)

**Interfaces:**
- Consumes: `applied_params`, abstract fields from Tasks 2–4.
- Produces: no new interfaces — proves the sliders' semantic direction under real image conditions.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_detect_endpoint.py`:

```python
SAMPLE_PATH = "tests/fixtures/agar_sample.jpg"


def _post_detect(**abstract):
    return client.post(
        "/detect",
        json={"image_path": SAMPLE_PATH, **abstract},
    ).json()


def test_sensitivity_direction_more_sensitive_finds_more():
    strict = _post_detect(sensitivity=0)["count"]
    permissive = _post_detect(sensitivity=100)["count"]
    assert permissive > strict, (
        f"expected permissive({permissive}) > strict({strict})"
    )


def test_min_size_direction_stricter_finds_fewer():
    permissive = _post_detect(min_size=0)["count"]
    strict = _post_detect(min_size=100)["count"]
    assert strict < permissive, (
        f"expected strict({strict}) < permissive({permissive})"
    )


def test_edge_margin_direction_larger_margin_reduces_pickable():
    def pickable(edge):
        colonies = _post_detect(edge_margin=edge)["colonies"]
        return sum(1 for c in colonies if c["pickable"])
    assert pickable(100) <= pickable(0), (
        "larger edge margin should not increase pickable count"
    )
```

- [ ] **Step 2: Run tests to verify they fail (or run — depending on random image outcome)**

Run: `.venv/Scripts/python -m pytest tests/test_detect_endpoint.py -v -k direction`
Expected: These tests will likely PASS if Task 4 was implemented correctly. If they FAIL, it means the mapping direction is inverted somewhere — investigate before proceeding.

- [ ] **Step 3: If any fail, diagnose and fix**

If `test_sensitivity_direction` fails: verify `sensitivity_to_offset` returns higher offset for higher input (higher offset = lower threshold = more sensitive per `detector.py:244`).
If `test_min_size_direction` fails: verify `min_size_to_area` monotonic increasing.
If `test_edge_margin_direction` fails: verify `edge_to_margin_px` monotonic; `pick_region` erosion increases with edge_margin.

- [ ] **Step 4: Full suite**

Run: `.venv/Scripts/python -m pytest -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_detect_endpoint.py
git commit -m "verify slider directions with real fixture"
```

---

## Task 6: Documentation updates

**Files:**
- Modify: `README.md` (add subsection under `POST /detect`)
- Modify: `docs/detection_parameters.md` (add operator UI section)

**Interfaces:** none — documentation only.

- [ ] **Step 1: Update `README.md`**

Locate the section that shows the `POST /detect` request JSON example. Add a new paragraph immediately after that JSON example (before the "이미지 입력 두 방식" bullets):

```markdown
### 오퍼레이터용 0~100 스케일 필드 (선택)

CV 원본 파라미터 대신 오퍼레이터가 이해하기 쉬운 0~100 슬라이더 값으로도 요청 가능하다. 지정된 필드는 대응하는 raw 필드보다 우선한다.

| 추상 필드 (0~100) | 덮어쓰는 raw 필드 | 기본값 → raw |
|---|---|---|
| `sensitivity` | `threshold_offset` | 50 → +7 |
| `min_size` | `min_area` | 20 → ≈6 |
| `max_size` | `max_area` | 80 → ≈5000 |
| `edge_margin` | 벽 여백(px) | 40 → 60 |

응답에는 실제 적용된 raw 값이 `applied_params`에 담겨 되반환된다.

예:
```jsonc
{ "image_path": "...", "sensitivity": 65, "min_size": 30, "edge_margin": 50 }
```

UI 목업(`docs/mockup/operator-ui.html`)에서 이 필드들을 실제로 어떻게 슬라이더로 노출하는지 볼 수 있다.
```

- [ ] **Step 2: Update `docs/detection_parameters.md`**

Append a new section at the end:

```markdown

## 오퍼레이터용 파라미터 (0~100 스케일)

로봇 오퍼레이터를 위해 CV 원본 파라미터의 사용성을 다듬은 4개 슬라이더 값. `POST /detect`/`POST /detect/preview`에 `sensitivity`, `min_size`, `max_size`, `edge_margin` (모두 `int`, 0~100, 선택) 필드로 전달한다.

지정된 필드는 대응 raw 필드를 덮어쓴다. 미지정이면 기존 raw 필드 또는 config 상수를 그대로 사용해 backwards compat이 유지된다. 매핑은 `app/param_mapping.py`에서 pure function으로 구현되어 있으며, 프론트엔드가 참조 구현이 필요하면 그대로 포팅할 수 있다.

응답의 `applied_params` dict에 실제 사용된 raw 값이 담긴다 — 튜닝 로그·재현·이슈 리포트 용도.

설계 근거·매핑 상세: `docs/superpowers/specs/2026-07-28-operator-parameters-design.md`.
```

- [ ] **Step 3: Verify tests still pass (docs shouldn't affect anything)**

Run: `.venv/Scripts/python -m pytest -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add README.md docs/detection_parameters.md
git commit -m "document operator 0-100 parameter fields"
```

---

## Task 7: End-to-end verification with mockup

**Files:** none modified. This is a manual smoke test with the mockup HTML.

**Interfaces:** none.

- [ ] **Step 1: Start the server**

```
cd C:\Users\user\Desktop\dev\2026\pickable\vision
.venv\Scripts\python main.py
```

Expected console output: `Uvicorn running on http://0.0.0.0:7780`.

- [ ] **Step 2: Open the mockup**

Open in browser:
```
C:\Users\user\Desktop\dev\2026\pickable\vision\docs\mockup\operator-ui.html
```

Sample image should load automatically.

- [ ] **Step 3: Verify baseline detection**

Click **[적용]**. Wait for spinner.
Expected: 콜로니 원이 이미지 위에 그려지고, 상단 통계 바에 개수 표시. 총 검출 수 = 약 639개, 피킹 후보 = 약 27개 (기본값 기준).

- [ ] **Step 4: Verify edge_margin actually filters now**

Move **벽 여백** 슬라이더를 100까지 올린 후 **[적용]** 다시 클릭.
Expected: 피킹 후보 수가 이전보다 줄어듦 (경계 근처 후보가 제외되어). 초록 점선 사각형도 안쪽으로 좁혀짐.

- [ ] **Step 5: Verify sensitivity direction**

**감도** 슬라이더 0 → **[적용]** → 총 검출 수 기록.
**감도** 슬라이더 100 → **[적용]** → 이전보다 총 검출 수가 늘어야 함.

- [ ] **Step 6: Update mockup label (optional cleanup)**

Now that edge_margin actually filters on the server, edit `docs/mockup/operator-ui.html` line with `<span class="name">벽 여백 (시각화만)</span>` and update payload builder to send `edge_margin` as the abstract field instead of relying on the visual-only note:

In the HTML, change:
```html
<span class="name">벽 여백 (시각화만)</span>
```
to:
```html
<span class="name">벽 여백</span>
```

In the JS `buildPayload()`, replace the payload construction with the abstract fields directly (server now supports them):
```javascript
function buildPayload() {
  const payload = {
    sensitivity:    +document.querySelector('[data-field="sensitivity"]').value,
    min_size:       +document.querySelector('[data-field="min_size"]').value,
    max_size:       +document.querySelector('[data-field="max_size"]').value,
    edge_margin:    +document.querySelector('[data-field="edge_margin"]').value,
    split_touching: el.splitTouching.checked,
    pick_top_n:     el.pickAll.checked ? null : +el.pickCount.value,
  };
  if (STATE.imageSource === 'sample') {
    payload.image_path = 'tests/fixtures/agar_sample.jpg';
  } else {
    payload.image = STATE.imageBase64;
  }
  return payload;
}
```

Remove the now-unused mapping functions from the JS if desired — leave them if they're still useful as a client-side reference, but note in a comment they're not called anymore.

- [ ] **Step 7: Reload the mockup, click [적용], verify results are the same as before**

Same total count as with client-side mapping (because both compute the same raw values).

- [ ] **Step 8: Commit mockup update**

```bash
git add docs/mockup/operator-ui.html
git commit -m "switch mockup to abstract fields end-to-end"
```

---

## Success Criteria

- All existing tests continue to pass with zero modification.
- New tests in `tests/test_param_mapping.py` (mapping anchors + monotonicity) pass.
- New tests in `tests/test_detect_endpoint.py` (applied_params, priority overrides, direction with real image) pass.
- `POST /detect` with no new fields produces byte-identical `colonies` list as before (implicit via regression test).
- `POST /detect` with `sensitivity=100, min_size=100, edge_margin=100` produces different count/pickable numbers vs. defaults, in the expected direction.
- `applied_params` in every `/detect` response reflects the actual raw values used.
- Mockup HTML sends abstract fields directly; edge_margin slider actually affects pickable count in the response.
- `README.md` and `docs/detection_parameters.md` describe the new fields.
