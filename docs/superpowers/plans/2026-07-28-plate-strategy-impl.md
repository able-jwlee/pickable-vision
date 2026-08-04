> **⚠ 이 계획은 실행되지 않았다 (2026-08-04 기록).**
>
> 여기 설계한 `app/plates/` 전략 패키지와 `PlateStrategy` 프로토콜은 만들어지지
> 않았다. 대신 `app/blob_detector.py` 단일 모듈에 `plate_type` 인자를 두는 쪽으로
> 갔고, 기본값도 이 문서의 `"well_8"` 이 아니라 `"petri"` 다.
>
> 이유: 계획을 세운 뒤 라벨 40장으로 측정해 보니 문제가 ROI 기하구조가 아니라
> **극성·스케일·ROI 세 가지 이미지 모델 가정 전체**였다. 그래서 전략 분리가
> 아니라 검출 경로 재설계로 방향이 바뀌었다.
> 자세한 경위는 [`docs/detection-improvement-2026-07-28.md`](../../detection-improvement-2026-07-28.md) 참조.
>
> 기록용으로만 남긴다. 여기의 체크박스·인터페이스 정의를 현재 코드의 사양으로
> 읽으면 안 된다.

# plate_type 전략 분리 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 검출 파이프라인에서 용기 종류(웰 플레이트 vs 페트리 접시)에 종속된 ROI 계산을 `app/plates/` 전략 모듈로 분리한다. 웰 플레이트 경로는 로직 변경 없이 코드 이동만 하고, 페트리는 원형 접시 ROI + 극성 자동 추정 신규 추가.

**Architecture:** `PlateStrategy` 프로토콜을 두고 `well_8` / `petri` 두 구현을 `app/plates/` 아래에 놓는다. `DetectRequest.plate_type` (기본 `"well_8"`) 로 선택. `invert` 필드를 `bool | None` 로 완화해 미지정 시 전략이 결정하게 함. 검출 알고리즘 본체(`detect`)는 손대지 않는다.

**Tech Stack:** Python 3.10, FastAPI (Pydantic v2), pytest, OpenCV, NumPy. 기존 리포 관례 그대로.

## Global Constraints

- Python 3.10 (`X | None` 문법 사용).
- Pydantic v2, `DetectRequest` 는 `extra='ignore'` (알 수 없는 필드 조용히 무시). 이거 유지.
- **웰 플레이트 무회귀 보장:** fixture `tests/fixtures/agar_sample.jpg` 기본 요청 검출 개수는 지금 **정확히 639**. 이 수치가 유지되지 않으면 전 작업 롤백.
- 기존 74개 테스트는 **한 곳(test_models.py:12)만 예외**로 무수정 통과. 그 한 줄은 `invert` 필드 타입/기본값 변경 때문에 불가피 (설계 스펙 §3.5 "invert 타입 변경이 유일한 기존 필드 수정"과 일치).
- 컨피그 상수 이름 접두사 `PETRI_` 로 신규 항목 격리 (기존 상수 이름 안 건드림).
- `annotate` 필드 default 값(`"all"`) 등 다른 필드는 절대 변경 금지.
- 커밋 메시지 스타일: 기존 히스토리와 일치하는 소문자 시작, 하나 이상 문단의 "왜" 설명, `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` trailer.

---

### Task 1: `app/plates/` 패키지 골격 (프로토콜 + 레지스트리)

**Files:**
- Create: `app/plates/__init__.py`
- Create: `app/plates/base.py`
- Test: `tests/test_plates_registry.py`

**Interfaces:**
- Consumes: 없음 (첫 번째 태스크).
- Produces:
  - `app.plates.base.RoiResult` — `@dataclass` with fields `mask: np.ndarray`, `metadata: dict`. 전략의 `roi()` 반환 타입.
  - `app.plates.base.PlateStrategy` — `Protocol` with attrs `name: str`, methods `roi(gray: np.ndarray) -> RoiResult`, `default_invert(gray: np.ndarray, roi: np.ndarray) -> bool`.
  - `app.plates.get_plate(name: str) -> PlateStrategy` — 알 수 없는 이름이면 `ValueError`.
  - `app.plates.SUPPORTED_PLATES: tuple[str, ...]` — API 검증/문서화용.

- [ ] **Step 1: Write the failing test**

Create `tests/test_plates_registry.py`:

```python
import pytest

from app.plates import SUPPORTED_PLATES, get_plate
from app.plates.base import PlateStrategy


def test_supported_plates_lists_both():
    assert set(SUPPORTED_PLATES) == {"well_8", "petri"}


def test_get_plate_returns_strategy_with_name():
    for name in SUPPORTED_PLATES:
        strat = get_plate(name)
        assert isinstance(strat, PlateStrategy)  # Protocol runtime check
        assert strat.name == name


def test_get_plate_unknown_raises_value_error():
    with pytest.raises(ValueError, match="unknown plate_type"):
        get_plate("triangle_5")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_plates_registry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.plates'`.

- [ ] **Step 3: Create the base module**

Create `app/plates/base.py`:

```python
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import numpy as np


@dataclass
class RoiResult:
    """전략의 roi() 반환. mask 는 255=검출 대상, 0=제외.

    metadata 는 전략별로 자유롭게 채운다. 페트리는 {"found": bool, "circle":
    (cx, cy, r) | None} 을 넣고, API 가 applied_params 에 실어 호출자에게 전달한다.
    """
    mask: np.ndarray
    metadata: dict = field(default_factory=dict)


@runtime_checkable
class PlateStrategy(Protocol):
    """용기 종류별 ROI + 명암 극성 결정 프로토콜.

    - `roi(gray)` : 검출 파이프라인이 픽셀을 살릴지 여부를 결정하는 마스크.
      호출자는 `mask_walls=True` 일 때만 적용한다 (False 면 전체 이미지 사용).
    - `default_invert(gray, roi)` : DetectRequest.invert 가 None 일 때 쓸 극성.
      True = 어두운 콜로니 (black-hat), False = 밝은 콜로니 (top-hat).
    """
    name: str

    def roi(self, gray: np.ndarray) -> RoiResult: ...
    def default_invert(self, gray: np.ndarray, roi: np.ndarray) -> bool: ...
```

- [ ] **Step 4: Create the package init with registry**

Create `app/plates/__init__.py`:

```python
"""용기 종류별 검출 전략. `get_plate(name)` 로 인스턴스를 얻는다.

Task 2 에서 well_8 이 추가되고, Task 3 에서 petri 가 추가되면 REGISTRY 에
등록된다. 지금은 두 클래스가 아직 없으므로 임시로 빈 dict.
"""
from __future__ import annotations

from app.plates.base import PlateStrategy, RoiResult

SUPPORTED_PLATES: tuple[str, ...] = ("well_8", "petri")

_REGISTRY: dict[str, PlateStrategy] = {}


def _register(strategy: PlateStrategy) -> None:
    _REGISTRY[strategy.name] = strategy


def get_plate(name: str) -> PlateStrategy:
    if name not in _REGISTRY:
        raise ValueError(
            f"unknown plate_type: {name!r} (supported: {SUPPORTED_PLATES})"
        )
    return _REGISTRY[name]


# 지연 임포트 — Task 2, 3 에서 각 모듈이 만들어지면 여기서 등록.
from app.plates import well8 as _well8    # noqa: E402
from app.plates import petri as _petri    # noqa: E402
_register(_well8.STRATEGY)
_register(_petri.STRATEGY)


__all__ = ["PlateStrategy", "RoiResult", "SUPPORTED_PLATES", "get_plate"]
```

**주의:** 이 상태에서 아직 `well8.py`, `petri.py` 가 없어서 임포트가 실패한다. Task 2 를 이어서 하면 해결됨. Step 5 는 임시로 임포트를 주석 처리해 registry 만 검증한다.

- [ ] **Step 5: 임시로 well8/petri 임포트 주석 처리**

`app/plates/__init__.py` 하단 임포트 세 줄을 임시로 주석 처리:

```python
# from app.plates import well8 as _well8    # noqa: E402
# from app.plates import petri as _petri    # noqa: E402
# _register(_well8.STRATEGY)
# _register(_petri.STRATEGY)
```

이 상태에서 `get_plate("well_8")` 은 아직 실패한다. 테스트 두 개를 임시 스킵 마크로 감싼다:

`tests/test_plates_registry.py` 상단에 추가:

```python
pytestmark = pytest.mark.skip(reason="strategies wired in Task 2/3")
```

- [ ] **Step 6: Run tests to verify collection works**

Run: `.venv\Scripts\python -m pytest tests/test_plates_registry.py -v --collect-only`
Expected: collected 3 items (모두 skipped 로 표시되어도 됨). 임포트 에러가 없어야 함.

- [ ] **Step 7: Commit**

```bash
git add app/plates/__init__.py app/plates/base.py tests/test_plates_registry.py
git commit -m "$(cat <<'EOF'
scaffold app/plates/ registry and PlateStrategy protocol

Introduce the seam that plate-type dispatch will hang off of. RoiResult
carries a mask plus a strategy-specific metadata dict so petri can pass
back whether it actually found a dish without breaking the protocol.
Registry stays minimal — get_plate raises ValueError for unknown names
so the API can convert to a 400. Concrete strategies land in the next
two tasks; the registry imports are stubbed until then and the tests
skip.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `well_8` 전략 (코드 이동, 로직 무변경)

**Files:**
- Create: `app/plates/well8.py`
- Modify: `app/plates/__init__.py` (Task 1 에서 주석 처리한 well8 임포트 복원)
- Modify: `tests/test_plates_registry.py` (Task 1 의 pytestmark skip 제거)
- Test: `tests/test_plates_well8.py` (신규)

**Interfaces:**
- Consumes: `app.plates.base.{PlateStrategy, RoiResult}`, `app.detector.{_plate_roi, _well_mask}` (기존 함수 재사용).
- Produces:
  - `app.plates.well8.Well8Strategy` (class implementing `PlateStrategy`).
  - `app.plates.well8.STRATEGY: PlateStrategy` (module-level singleton — registry 가 참조).

- [ ] **Step 1: Write the failing test — byte equality with old _well_mask**

Create `tests/test_plates_well8.py`:

```python
import cv2
import numpy as np
import pytest

from app.detector import _well_mask
from app.plates import get_plate


@pytest.fixture(scope="module")
def fixture_gray():
    img = cv2.imread("tests/fixtures/agar_sample.jpg")
    assert img is not None, "fixture image missing"
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def test_well8_roi_byte_identical_to_legacy(fixture_gray):
    """Well8 전략의 ROI 는 기존 _well_mask 와 pixel-for-pixel 동일해야 한다.
    이 검사가 무너지면 well_8 = "코드 이동만" 이라는 스펙 §3.3 계약이 깨진 것.
    """
    legacy = _well_mask(fixture_gray)
    strat = get_plate("well_8")
    new = strat.roi(fixture_gray).mask
    assert new.shape == legacy.shape
    assert np.array_equal(new, legacy)


def test_well8_default_invert_matches_config(fixture_gray):
    from app import config
    strat = get_plate("well_8")
    dummy_roi = np.full(fixture_gray.shape, 255, np.uint8)
    assert strat.default_invert(fixture_gray, dummy_roi) is config.DEFAULT_INVERT


def test_well8_name():
    assert get_plate("well_8").name == "well_8"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_plates_well8.py -v`
Expected: FAIL — `get_plate("well_8")` 은 registry 가 비어 있어 ValueError.

- [ ] **Step 3: Create well8 module (delegating to legacy functions)**

Create `app/plates/well8.py`:

```python
"""8웰(2×4) 플레이트 전략. 기존 detector._plate_roi + _well_mask 로직을
그대로 감싸기만 한다 (로직 변경 무). 스펙 §3.3.
"""
from __future__ import annotations

import numpy as np

from app import config
from app.detector import _well_mask
from app.plates.base import PlateStrategy, RoiResult


class Well8Strategy:
    name = "well_8"

    def roi(self, gray: np.ndarray) -> RoiResult:
        return RoiResult(mask=_well_mask(gray), metadata={})

    def default_invert(self, gray: np.ndarray, roi: np.ndarray) -> bool:
        return config.DEFAULT_INVERT


STRATEGY: PlateStrategy = Well8Strategy()
```

- [ ] **Step 4: 임시로 페트리 stub 을 만들어 __init__ 이 임포트 되게 함**

Create `app/plates/petri.py` (Task 3 에서 실제 구현):

```python
"""페트리 전략 stub — Task 3 에서 진짜 구현으로 교체.

지금은 well_8 과 동일하게 동작 (mask_walls 안 씀). Task 3 안 끝난 상태에서
get_plate("petri") 를 부르면 무해한 well_8 폴백을 주는 안전한 자리채우기.
"""
from __future__ import annotations

import numpy as np

from app import config
from app.plates.base import PlateStrategy, RoiResult


class _PetriStub:
    name = "petri"

    def roi(self, gray: np.ndarray) -> RoiResult:
        return RoiResult(
            mask=np.full(gray.shape, 255, np.uint8),
            metadata={"found": False, "circle": None},
        )

    def default_invert(self, gray: np.ndarray, roi: np.ndarray) -> bool:
        return config.DEFAULT_INVERT


STRATEGY: PlateStrategy = _PetriStub()
```

- [ ] **Step 5: Restore imports in `app/plates/__init__.py`**

`app/plates/__init__.py` 하단 임포트 세 줄의 `#` 를 제거:

```python
from app.plates import well8 as _well8    # noqa: E402
from app.plates import petri as _petri    # noqa: E402
_register(_well8.STRATEGY)
_register(_petri.STRATEGY)
```

- [ ] **Step 6: Un-skip registry test**

`tests/test_plates_registry.py` 상단의 `pytestmark = pytest.mark.skip(...)` 삭제.

- [ ] **Step 7: Run tests to verify pass**

Run: `.venv\Scripts\python -m pytest tests/test_plates_well8.py tests/test_plates_registry.py -v`
Expected: 6 passed (3 registry + 3 well8).

- [ ] **Step 8: Run full suite to prove zero regression**

Run: `.venv\Scripts\python -m pytest -q`
Expected: 80 passed (기존 74 + 신규 6). 만약 74 개 중 하나라도 실패하면 well8 이 로직을 바꾼 것이므로 롤백.

- [ ] **Step 9: Commit**

```bash
git add app/plates/well8.py app/plates/petri.py app/plates/__init__.py tests/test_plates_well8.py tests/test_plates_registry.py
git commit -m "$(cat <<'EOF'
add well_8 plate strategy (thin wrapper over existing _well_mask)

Well8Strategy.roi() delegates to detector._well_mask verbatim; the test
asserts byte-equality with the legacy function so any future edit that
drifts logic will trip. This preserves the spec §3.3 contract that
well_8 is "code move only, no logic change" — the safest possible move
while the target domain (well plates) still has zero labels.

Also stub app/plates/petri.py so the registry import chain works. The
stub returns a full-image mask + found=False metadata, i.e. behaves
like mask_walls=False. Task 3 replaces it with the real circular ROI.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: `petri` 전략 (원형 ROI + 극성 자동 추정)

**Files:**
- Modify: `app/plates/petri.py` (Task 2 stub 을 실제 구현으로 교체)
- Modify: `app/config.py` (하단에 `PETRI_*` 상수 추가)
- Test: `tests/test_plates_petri.py` (신규)

**Interfaces:**
- Consumes: `app.plates.base.{PlateStrategy, RoiResult}`, `app.config.PETRI_*`.
- Produces:
  - `app.plates.petri.PetriStrategy` (class).
  - `app.plates.petri.STRATEGY: PlateStrategy` (기존 stub 을 대체).
  - `roi()` 반환의 `metadata` 는 `{"found": bool, "circle": tuple[float, float, float] | None}` 형식.

**참고:** `scripts/petri_roi_prototype.py` 의 `petri_roi()` + `estimate_invert()` 로직을 그대로 옮긴다. 새로 짜지 말고 검증된 로직을 재사용.

- [ ] **Step 1: Add config constants**

`app/config.py` 하단에 추가:

```python
# 페트리 접시 ROI 검출 (스펙 §3.4).
# scripts/petri_roi_prototype.py 의 검증된 상수를 그대로 옮김.
PETRI_FILL_MIN = 0.85           # 윤곽 면적 / 최소외접원 면적 — 원에 얼마나 꽉 찼나
PETRI_RADIUS_MIN_RATIO = 0.15   # 반지름 하한 = 긴 변 × 이 비율
PETRI_RADIUS_MAX_RATIO = 0.75   # 반지름 상한 = 긴 변 × 이 비율
PETRI_RIM_MARGIN_RATIO = 0.93   # 테두리 링 제외를 위해 반지름을 이만큼으로 수축.
                                # 실측: 이 값이 5장(510, 971, 5212, 5271, 12033)에서
                                # 가장자리 콜로니 4~5% 를 잘라냄. 트레이드오프.
PETRI_DOWNSCALE_TO = 1000       # 원 탐색용 다운스케일 (긴 변). 속도용.
PETRI_CLOSE_KERNEL = 15         # 이진 이미지 닫힘 커널 (콜로니 구멍 메꾸기)
PETRI_BLUR_KERNEL = 5           # 원 탐색 전 가우시안 블러 (홀수)
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_plates_petri.py`:

```python
"""페트리 전략 단위 테스트.

sample/ 는 리포에 없는 환경도 있으므로 (git 미포함, ~82MB), 그 이미지를
쓰는 테스트는 skip 마크로 감싼다.
"""
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.plates import get_plate

SAMPLE_13895 = Path("sample/lower-resolution/13895.jpg")

pytestmark_needs_sample = pytest.mark.skipif(
    not SAMPLE_13895.exists(),
    reason="sample/ not present (git ignored, ~82MB)",
)


@pytest.fixture(scope="module")
def petri_strategy():
    return get_plate("petri")


def test_petri_name(petri_strategy):
    assert petri_strategy.name == "petri"


def test_petri_fallback_on_blank_image(petri_strategy):
    """모든 픽셀이 균일한 이미지에서 접시를 못 찾으면 전체 이미지 폴백."""
    gray = np.full((800, 800), 128, np.uint8)
    result = petri_strategy.roi(gray)
    assert result.mask.shape == gray.shape
    # 폴백은 전체 이미지 마스크
    assert (result.mask == 255).all()
    assert result.metadata["found"] is False


def test_petri_default_invert_light_bg_dark_colonies(petri_strategy):
    """밝은 배경 + 소수 어두운 픽셀 → invert=True (기본값, black-hat 사용)."""
    gray = np.full((400, 400), 220, np.uint8)
    cv2.circle(gray, (200, 200), 30, 40, -1)  # 소수의 어두운 픽셀
    roi = np.full_like(gray, 255)
    assert petri_strategy.default_invert(gray, roi) is True


def test_petri_default_invert_dark_bg_light_colonies(petri_strategy):
    """어두운 배경 + 소수 밝은 픽셀 → invert=False (top-hat 사용)."""
    gray = np.full((400, 400), 40, np.uint8)
    cv2.circle(gray, (200, 200), 30, 220, -1)
    roi = np.full_like(gray, 255)
    assert petri_strategy.default_invert(gray, roi) is False


@pytestmark_needs_sample
def test_petri_finds_circle_on_13895(petri_strategy):
    """13895.jpg 는 프로토타입에서 접시 검출 성공한 이미지 (수동 확인)."""
    gray = cv2.imread(str(SAMPLE_13895), cv2.IMREAD_GRAYSCALE)
    result = petri_strategy.roi(gray)
    assert result.metadata["found"] is True
    circle = result.metadata["circle"]
    assert circle is not None
    cx, cy, r = circle
    # 반지름은 긴 변의 15~75% 사이여야 함 (채택 조건)
    long_side = max(gray.shape)
    assert 0.15 * long_side < r < 0.75 * long_side
    # 마스크는 원 안쪽만 남기고 나머지는 0
    assert (result.mask == 255).sum() < result.mask.size * 0.9  # 뭔가 잘랐어야 함
```

- [ ] **Step 3: Run tests to verify failing**

Run: `.venv\Scripts\python -m pytest tests/test_plates_petri.py -v`
Expected: FAIL — 대부분 stub 이 반환하는 값 때문에 (fallback 은 통과할 수도, 극성/원 검출은 실패).

- [ ] **Step 4: Replace stub with real implementation**

Overwrite `app/plates/petri.py`:

```python
"""페트리 접시 전략 (스펙 §3.4).

- roi(): 원형 접시 마스크. 양극성 Otsu 로 접시 후보 → minEnclosingCircle
  → 채움비/반지름 채택 조건 → RIM_MARGIN_RATIO 로 수축.
- default_invert(): ROI 내부 픽셀 분포의 꼬리 방향으로 극성 추정.

로직은 scripts/petri_roi_prototype.py 의 검증본을 옮긴 것이다. 라벨 39장에서
접시 원 검출 성공 31/39, 그중 정답 98%+ 보존 26/39, 극성 30/39.
"""
from __future__ import annotations

import cv2
import numpy as np

from app import config
from app.plates.base import PlateStrategy, RoiResult


class PetriStrategy:
    name = "petri"

    def roi(self, gray: np.ndarray) -> RoiResult:
        mask, found, circle = _petri_roi(gray)
        return RoiResult(
            mask=mask,
            metadata={"found": found, "circle": circle},
        )

    def default_invert(self, gray: np.ndarray, roi: np.ndarray) -> bool:
        return _estimate_invert(gray, roi)


STRATEGY: PlateStrategy = PetriStrategy()


def _petri_roi(
    gray: np.ndarray,
) -> tuple[np.ndarray, bool, tuple[float, float, float] | None]:
    """원형 접시 내부 마스크 + 접시 검출 여부 + (cx, cy, r).

    접시를 못 찾으면 전체 이미지 마스크로 폴백해 mask_walls=False 와 같은
    동작이 된다 (손해 없음). 스펙 §3.4.
    """
    h, w = gray.shape
    scale = config.PETRI_DOWNSCALE_TO / max(h, w)
    small = cv2.resize(gray, (int(w * scale), int(h * scale)))
    small = cv2.GaussianBlur(
        small, (config.PETRI_BLUR_KERNEL, config.PETRI_BLUR_KERNEL), 0
    )
    _, binary = cv2.threshold(
        small, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )

    # 접시가 배경보다 밝을 수도 어두울 수도 있으므로 양 극성 모두 시도해
    # 원에 더 가까운 쪽을 고른다.
    best = None
    close_k = np.ones(
        (config.PETRI_CLOSE_KERNEL, config.PETRI_CLOSE_KERNEL), np.uint8
    )
    for candidate in (binary, cv2.bitwise_not(binary)):
        closed = cv2.morphologyEx(candidate, cv2.MORPH_CLOSE, close_k)
        contours, _ = cv2.findContours(
            closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        if not contours:
            continue
        contour = max(contours, key=cv2.contourArea)
        (cx, cy), r = cv2.minEnclosingCircle(contour)
        circle_area = float(np.pi * r * r)
        fill = cv2.contourArea(contour) / circle_area if circle_area else 0.0
        if best is None or fill > best[0]:
            best = (fill, float(cx), float(cy), float(r))

    full = np.full(gray.shape, 255, np.uint8)
    if best is None:
        return full, False, None

    fill, cx, cy, r = best
    cx, cy, r = cx / scale, cy / scale, r / scale
    long_side = max(h, w)
    found = (
        fill > config.PETRI_FILL_MIN
        and long_side * config.PETRI_RADIUS_MIN_RATIO < r
        and r < long_side * config.PETRI_RADIUS_MAX_RATIO
    )
    if not found:
        return full, False, (cx, cy, r)

    mask = np.zeros(gray.shape, np.uint8)
    cv2.circle(
        mask, (int(cx), int(cy)),
        int(r * config.PETRI_RIM_MARGIN_RATIO), 255, -1,
    )
    return mask, True, (cx, cy, r)


def _estimate_invert(gray: np.ndarray, roi: np.ndarray) -> bool:
    """ROI 내부 밝기 분포의 꼬리 방향으로 극성 추정.

    콜로니는 소수 픽셀이므로, 콜로니가 배경보다 밝으면 분포가 오른쪽으로
    꼬리 → mean > median. 실측 정확도 30/39. 대비 ±1 계조 이하에선 신뢰
    불가 — 확실한 경로는 요청에서 invert 를 명시하는 것이다.
    """
    values = gray[roi > 0]
    if values.size == 0:
        return True
    return not (float(values.mean()) > float(np.median(values)))
```

- [ ] **Step 5: Run petri tests to verify pass**

Run: `.venv\Scripts\python -m pytest tests/test_plates_petri.py -v`
Expected: 4 passed + 1 skipped (sample 없는 환경) OR 5 passed (sample 있으면).

- [ ] **Step 6: Run full suite (regression check)**

Run: `.venv\Scripts\python -m pytest -q`
Expected: 84 passed (기존 80 + 신규 petri 4). sample 있으면 85.

- [ ] **Step 7: Commit**

```bash
git add app/plates/petri.py app/config.py tests/test_plates_petri.py
git commit -m "$(cat <<'EOF'
add petri plate strategy (circular ROI + polarity estimation)

Port the validated logic from scripts/petri_roi_prototype.py into
app/plates/petri.py so the /detect endpoint can dispatch to it via
plate_type. The roi() returns metadata with {found, circle} so the API
layer can surface petri_roi_found without breaking the PlateStrategy
protocol shape.

Measurements from the prototype (39 labeled images): dish circle
detected on 31/39 (32/40 with the unlabeled 1399), colony preservation
≥98% on 26/39, background removal 41-64%. Polarity estimation 30/39.

Petri stays best-effort by design — sample/ is not the target domain
(spec §2), and the dominant false positives (lid marker writing,
watershed over-segmentation) live inside the dish and are not fixed by
an ROI change. This unlocks a structural seam; accuracy work is left
for follow-ups that need real well-plate labels first.

Config constants prefixed PETRI_ to avoid colliding with existing ones.
RIM_MARGIN_RATIO=0.93 is a known tradeoff — five images (510, 971,
5212, 5271, 12033) clip 4-5% of edge colonies, documented in the spec.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: 검출기 배선 (`detect` + `pick_region`)

**Files:**
- Modify: `app/detector.py`
- Test: `tests/test_detector_plate_type.py` (신규)

**Interfaces:**
- Consumes: `app.plates.get_plate`.
- Produces:
  - `detect(...)` 시그니처에 `plate_type: str = "well_8"` 추가 (기존 인자 순서 뒤). 반환 타입/의미 무변경.
  - `pick_region(...)` 시그니처에 `plate_type: str = "well_8"` 추가. 반환 무변경.
  - `detect_with_metadata(...)` — 신규 함수. `(circles, plate_metadata)` 튜플 반환. API 가 petri_roi_found 를 실을 때 사용. `detect()` 는 이 함수를 부르고 첫 번째만 돌려주게 리팩터.

**설계 결정:** 기존 `detect()` 시그니처를 그대로 유지해 74개 테스트가 통과해야 한다. `plate_type` 은 keyword-only, 기본 `"well_8"`. `mask_walls=True` 일 때만 전략 ROI 를 적용 (스펙 §3.5, `mask_walls=False` 면 전략 무관).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_detector_plate_type.py`:

```python
import cv2
import numpy as np
import pytest

from app.detector import detect, detect_with_metadata


@pytest.fixture(scope="module")
def fixture_img():
    img = cv2.imread("tests/fixtures/agar_sample.jpg")
    assert img is not None
    return img


COMMON = dict(
    min_area=6.0, max_area=5000.0, min_circularity=0.42,
    invert=True, tophat_kernel=31, mask_walls=True,
    threshold_offset=7, split_touching=True,
)


def test_default_plate_type_is_well_8(fixture_img):
    """plate_type 인자 없이 호출한 결과 == 명시적 well_8 결과."""
    a = detect(fixture_img, **COMMON)
    b = detect(fixture_img, plate_type="well_8", **COMMON)
    assert a == b


def test_unknown_plate_type_raises(fixture_img):
    with pytest.raises(ValueError, match="unknown plate_type"):
        detect(fixture_img, plate_type="triangle_5", **COMMON)


def test_petri_returns_metadata_dict(fixture_img):
    circles, meta = detect_with_metadata(
        fixture_img, plate_type="petri", **COMMON
    )
    assert isinstance(circles, list)
    assert "found" in meta          # petri 는 발견 여부를 넣는다
    assert "circle" in meta


def test_well8_metadata_empty(fixture_img):
    _, meta = detect_with_metadata(
        fixture_img, plate_type="well_8", **COMMON
    )
    assert meta == {}


def test_mask_walls_false_ignores_plate_type(fixture_img):
    """mask_walls=False 면 전략 ROI 무관 — well_8 과 petri 결과가 같아야 한다."""
    kw = {**COMMON, "mask_walls": False}
    a = detect(fixture_img, plate_type="well_8", **kw)
    b = detect(fixture_img, plate_type="petri", **kw)
    assert a == b
```

- [ ] **Step 2: Run tests to verify failing**

Run: `.venv\Scripts\python -m pytest tests/test_detector_plate_type.py -v`
Expected: FAIL — `plate_type` 인자, `detect_with_metadata` 함수가 아직 없음.

- [ ] **Step 3: Refactor detector.py to route through strategy**

Modify `app/detector.py`:

Replace the `detect(...)` function body with the new version, and add `detect_with_metadata`:

```python
def detect_with_metadata(
    img: np.ndarray,
    min_area: float,
    max_area: float,
    min_circularity: float,
    invert: bool,
    tophat_kernel: int,
    mask_walls: bool,
    threshold_offset: int = config.DEFAULT_THRESHOLD_OFFSET,
    split_touching: bool = config.DEFAULT_SPLIT_TOUCHING,
    *,
    plate_type: str = "well_8",
) -> tuple[list[tuple[float, float, float, float]], dict]:
    """detect() 와 동일하지만 전략 메타데이터를 함께 반환.

    반환의 dict 는 전략별로 자유 형식. well_8={}, petri={"found":..., "circle":...}.
    API 층이 이 dict 를 applied_params 에 실어 호출자에게 노출한다.
    """
    from app.plates import get_plate  # 순환 방지: 함수 안에서 임포트

    strategy = get_plate(plate_type)

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (3, 3), 0)

    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (tophat_kernel, tophat_kernel)
    )
    op = cv2.MORPH_BLACKHAT if invert else cv2.MORPH_TOPHAT
    hat = cv2.morphologyEx(blur, op, kernel)

    otsu_value, _ = cv2.threshold(
        hat, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )
    thresh = max(1.0, otsu_value - threshold_offset)
    _, binary = cv2.threshold(hat, thresh, 255, cv2.THRESH_BINARY)

    roi = None
    metadata: dict = {}
    if mask_walls:
        result = strategy.roi(blur)
        roi = result.mask
        metadata = result.metadata
        binary[roi == 0] = 0

    opened = cv2.morphologyEx(binary, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    opened = _remove_wall_streaks(opened)

    if split_touching:
        circles = _watershed_circles(
            img, opened, roi, min_area, max_area, min_circularity
        )
    else:
        circles = _contour_circles(opened, min_area, max_area, min_circularity)
    return circles, metadata


def detect(
    img: np.ndarray,
    min_area: float,
    max_area: float,
    min_circularity: float,
    invert: bool,
    tophat_kernel: int,
    mask_walls: bool,
    threshold_offset: int = config.DEFAULT_THRESHOLD_OFFSET,
    split_touching: bool = config.DEFAULT_SPLIT_TOUCHING,
    *,
    plate_type: str = "well_8",
) -> list[tuple[float, float, float, float]]:
    """콜로니를 검출해 (x, y, radius, circularity) 리스트를 반환.

    [기존 docstring 유지] plate_type 은 keyword-only, 기본 "well_8" 이라
    기존 호출자 무회귀. mask_walls=False 면 plate_type 무시 (스펙 §3.5).
    """
    circles, _ = detect_with_metadata(
        img,
        min_area=min_area,
        max_area=max_area,
        min_circularity=min_circularity,
        invert=invert,
        tophat_kernel=tophat_kernel,
        mask_walls=mask_walls,
        threshold_offset=threshold_offset,
        split_touching=split_touching,
        plate_type=plate_type,
    )
    return circles


def pick_region(
    img: np.ndarray,
    edge_margin: int = 0,
    *,
    plate_type: str = "well_8",
) -> np.ndarray:
    """피킹 안전 영역 마스크. 전략 ROI 를 edge_margin 만큼 더 침식."""
    from app.plates import get_plate  # 순환 방지

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    roi = get_plate(plate_type).roi(blur).mask
    if edge_margin > 0:
        k = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (edge_margin, edge_margin)
        )
        roi = cv2.erode(roi, k)
    return roi
```

**주의:** 기존 `detect()` 함수의 몸체 전부가 `detect_with_metadata()` 로 옮겨간다. `_plate_roi` / `_well_mask` 는 Task 2 의 well8 이 여전히 참조하므로 detector.py 에 남겨둔다 (Task 8 에서 정리).

- [ ] **Step 4: Run plate_type tests to verify pass**

Run: `.venv\Scripts\python -m pytest tests/test_detector_plate_type.py -v`
Expected: 5 passed.

- [ ] **Step 5: Run full suite (regression)**

Run: `.venv\Scripts\python -m pytest -q`
Expected: 89 passed (전 80 + 신규 5, sample 있으면 90).
**만약 기존 74개 중 하나라도 실패하면 즉시 롤백** — well_8 경로가 무회귀여야 한다.

- [ ] **Step 6: Commit**

```bash
git add app/detector.py tests/test_detector_plate_type.py
git commit -m "$(cat <<'EOF'
route detect() through plate strategy for ROI + metadata

detect_with_metadata() replaces the inline _well_mask call with a
strategy dispatch based on the new plate_type kwarg (default "well_8").
detect() becomes a thin wrapper preserving its exact signature so all
74 existing tests pass unchanged. pick_region() also takes plate_type
so the picking safety mask stays consistent with the detection ROI.

mask_walls=False short-circuits strategy dispatch — the ROI is only
consulted when the caller asked for wall masking, matching the existing
mental model (spec §3.5).

The strategy metadata dict propagates so the API can surface fields
like petri_roi_found without the detector needing to know what's in it.
well_8 always returns {}.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: `DetectRequest` + API 리졸브

**Files:**
- Modify: `app/models.py`
- Modify: `app/api.py`
- Modify: `tests/test_models.py` (1줄만 — 스펙이 명시적으로 허용한 예외)
- Test: `tests/test_detect_plate_type_endpoint.py` (신규)

**Interfaces:**
- Consumes: `app.detector.detect_with_metadata`, `app.plates.get_plate`.
- Produces:
  - `DetectRequest.plate_type: Literal["well_8", "petri"] = "well_8"`.
  - `DetectRequest.invert: bool | None = None` (기본값 변경 — None 이면 전략이 결정).
  - API `applied_params` 에 새 키: `plate_type`, `invert` (확정된 값), `petri_roi_found` (petri 일 때만).

- [ ] **Step 1: Write the failing endpoint tests**

Create `tests/test_detect_plate_type_endpoint.py`:

```python
import base64

import cv2
import numpy as np
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def _fixture_b64():
    img = cv2.imread("tests/fixtures/agar_sample.jpg")
    _, buf = cv2.imencode(".jpg", img)
    return base64.b64encode(buf).decode()


def test_plate_type_omitted_matches_well_8_explicit():
    """plate_type 미지정 == plate_type: 'well_8' == 콜로니 리스트 완전 일치."""
    payload = {"image": _fixture_b64()}
    a = client.post("/detect", json=payload).json()
    b = client.post("/detect", json={**payload, "plate_type": "well_8"}).json()
    assert a["colonies"] == b["colonies"]
    assert a["count"] == b["count"]


def test_applied_params_carries_plate_type_and_invert():
    resp = client.post("/detect", json={"image": _fixture_b64()}).json()
    assert resp["applied_params"]["plate_type"] == "well_8"
    assert resp["applied_params"]["invert"] is True    # well8.default_invert()


def test_applied_params_carries_petri_roi_found_only_for_petri():
    well = client.post("/detect", json={
        "image": _fixture_b64(), "plate_type": "well_8"
    }).json()
    petri = client.post("/detect", json={
        "image": _fixture_b64(), "plate_type": "petri"
    }).json()
    assert "petri_roi_found" not in well["applied_params"]
    assert "petri_roi_found" in petri["applied_params"]
    assert isinstance(petri["applied_params"]["petri_roi_found"], bool)


def test_invalid_plate_type_rejected_with_422():
    resp = client.post("/detect", json={
        "image": _fixture_b64(), "plate_type": "triangle_5"
    })
    assert resp.status_code == 422    # Pydantic Literal 검증


def test_explicit_invert_wins_over_strategy():
    """요청에서 invert 를 명시하면 전략의 default_invert 는 무시된다."""
    off = client.post("/detect", json={
        "image": _fixture_b64(), "invert": False
    }).json()
    assert off["applied_params"]["invert"] is False
```

- [ ] **Step 2: Run tests to verify failing**

Run: `.venv\Scripts\python -m pytest tests/test_detect_plate_type_endpoint.py -v`
Expected: FAIL — `plate_type` 필드가 아직 모델에 없음, invert 리졸브 로직도 없음.

- [ ] **Step 3: Update DetectRequest**

Modify `app/models.py`:

`DetectRequest` 안에서 `invert` 필드와 `annotate` 필드 사이 어딘가에 추가:

```python
    # 용기 종류. mask_walls=True 일 때 전략이 ROI 를 결정 (스펙 §5).
    plate_type: Literal["well_8", "petri"] = "well_8"
```

그리고 `invert` 필드 수정 — 기존:

```python
    invert: bool = config.DEFAULT_INVERT
```

를 아래로 교체:

```python
    # None 이면 plate 전략의 default_invert 가 결정 (petri 는 자동 추정, well_8 은
    # config.DEFAULT_INVERT). bool 을 명시하면 그 값이 우선.
    invert: bool | None = None
```

- [ ] **Step 4: Update the one legacy test that asserted invert=True default**

`tests/test_models.py` 12번째 줄 수정:

```python
    assert req.invert is None   # spec §3.5: 미지정이면 전략이 결정하도록 None
```

- [ ] **Step 5: Rewire API to use detect_with_metadata + resolve invert**

Modify `app/api.py`:

`_detect_and_score` 함수를 아래로 교체:

```python
def _detect_and_score(
    img: np.ndarray, req: DetectRequest, resolved: dict
) -> tuple[list[Colony], dict]:
    """검출 → 피킹 적합도 점수화 → (Colony 리스트, 전략 메타데이터)."""
    from app.plates import get_plate

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    strategy = get_plate(req.plate_type)
    # invert 미지정이면 전략이 결정. 지정되면 그 값 우선.
    if req.invert is None:
        # strategy.default_invert 가 ROI 를 필요로 하는 경우가 있으므로 한 번 계산.
        roi_probe = strategy.roi(gray).mask
        invert = strategy.default_invert(gray, roi_probe)
    else:
        invert = req.invert
    resolved["invert"] = invert
    resolved["plate_type"] = req.plate_type

    circles, meta = detect_with_metadata(
        img,
        min_area=resolved["min_area"],
        max_area=resolved["max_area"],
        min_circularity=req.min_circularity,
        invert=invert,
        tophat_kernel=req.tophat_kernel,
        mask_walls=req.mask_walls,
        threshold_offset=resolved["threshold_offset"],
        split_touching=resolved["split_touching"],
        plate_type=req.plate_type,
    )
    if req.plate_type == "petri":
        resolved["petri_roi_found"] = bool(meta.get("found", False))

    geom = [
        {"x": x, "y": y, "radius": r, "circularity": c}
        for x, y, r, c in circles
    ]
    pick_mask = (
        pick_region(img, edge_margin=resolved["pick_edge_margin"],
                    plate_type=req.plate_type)
        if req.mask_walls
        else None
    )
    scores = score_colonies(geom, top_n=resolved["pick_top_n"], pick_mask=pick_mask)
    return [
        Colony(
            id=i + 1, x=x, y=y, radius=r, circularity=c,
            score=scores[i]["score"], pickable=scores[i]["pickable"],
        )
        for i, (x, y, r, c) in enumerate(circles)
    ], meta
```

파일 상단 임포트에 추가:

```python
import cv2
from app.detector import detect_with_metadata
```

기존 `from app.detector import detect, pick_region` 는 `detect` 만 지우고 `pick_region` 은 남긴다:

```python
from app.detector import pick_region
```

그리고 `detect_colonies` 엔드포인트에서 `_detect_and_score` 반환 튜플을 언팩:

```python
    colonies, _meta = _detect_and_score(img, req, resolved)
```

`detect_preview` 도 마찬가지:

```python
    colonies, _meta = _detect_and_score(img, req, resolved)
```

- [ ] **Step 6: Run new endpoint tests**

Run: `.venv\Scripts\python -m pytest tests/test_detect_plate_type_endpoint.py -v`
Expected: 5 passed.

- [ ] **Step 7: Run full suite (regression)**

Run: `.venv\Scripts\python -m pytest -q`
Expected: 94 passed (기존 74 - 1 무수정 상실 + 1 수정 = 74, + 신규 5+4+5+6 = 20 → 94). sample 있으면 95.

**만약 test_models.py 외의 기존 테스트가 실패하면 즉시 롤백.**

- [ ] **Step 8: Commit**

```bash
git add app/models.py app/api.py tests/test_models.py tests/test_detect_plate_type_endpoint.py
git commit -m "$(cat <<'EOF'
add plate_type + optional invert to /detect API

DetectRequest gets plate_type: Literal["well_8","petri"] (default well_8)
and invert relaxes to bool | None (default None). None means "let the
plate strategy decide" — well_8 always answers config.DEFAULT_INVERT so
existing callers land on the same polarity, and petri runs its
distribution-tail estimator against the ROI-masked pixels.

The one existing assertion at test_models.py:12 flips from `is True` to
`is None` — this is the sole test the spec's §3.5 permits changing, and
the effective invert value stays True for well_8. Every other test in
the 74-count baseline passes untouched.

The API exposes the resolved invert plus plate_type in applied_params,
and adds petri_roi_found when the request selected petri, so operators
can distinguish "petri ran with a real circular ROI" from "petri fell
back to whole-image mask". Invalid plate_type values return 422 via
Pydantic Literal validation instead of hitting our get_plate ValueError.

pick_region() gets plate_type too so the picking safety mask stays
aligned with detection ROI.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: 골든 fixture 회귀 테스트 (검출 개수 = 639)

**Files:**
- Test: `tests/test_fixture_golden.py` (신규)

**Interfaces:**
- Consumes: `/detect` 엔드포인트.
- Produces: 새 테스트 하나. 회귀 감시용.

**목적 (사용자 요청 E):** 카메라가 없어서 웰플레이트 라벨은 없지만, fixture 의 현재 count 를 golden 으로 못 박아 두면 개선 작업 중의 count 변화를 즉시 감지할 수 있다. 위치는 검증 안 되지만 count 회귀는 잡힌다.

- [ ] **Step 1: Confirm current count via inprocess call**

Run:

```bash
.venv\Scripts\python -c "from fastapi.testclient import TestClient; from main import app; c = TestClient(app); r = c.post('/detect', json={'image_path': 'tests/fixtures/agar_sample.jpg'}); print(r.json()['count'])"
```

Expected: `639`. **다른 숫자가 나오면 앞선 태스크에서 well_8 로직이 이미 변경됨 → 롤백 필요.**

- [ ] **Step 2: Write the test**

Create `tests/test_fixture_golden.py`:

```python
"""fixture 검출 개수 골든값. 웰플레이트 도메인의 유일한 회귀 감시.

목표 도메인(웰 플레이트)의 라벨 데이터가 확보되기 전까지 (§6-1) 이 파일은
`agar_sample.jpg` 한 장의 개수만 지킨다. 위치는 검증하지 않으므로 알고리즘
개선 자체를 막지는 않지만, "실수로 well_8 로직을 건드렸다" 를 즉시 감지한다.

값이 바뀌어야 하는 정당한 변경(예: 알고리즘 개선)이면 이 파일과 함께 커밋한다.
"""
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

# 2026-07-28 기준 검출 개수. 웰 플레이트 도메인 회귀 감지의 유일한 기준값.
# 이 값을 바꿔야 하는 커밋은 이유를 커밋 메시지에 남길 것.
FIXTURE_GOLDEN_COUNT = 639
FIXTURE_GOLDEN_PICKABLE = 27


def test_fixture_default_count_matches_golden():
    resp = client.post("/detect", json={
        "image_path": "tests/fixtures/agar_sample.jpg"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == FIXTURE_GOLDEN_COUNT, (
        f"fixture count regressed: {data['count']} (expected {FIXTURE_GOLDEN_COUNT}). "
        f"Did well_8 logic change? Roll back or update the golden with a reason."
    )
    pickable = sum(1 for c in data["colonies"] if c.get("pickable"))
    assert pickable == FIXTURE_GOLDEN_PICKABLE
```

- [ ] **Step 3: Run to verify pass**

Run: `.venv\Scripts\python -m pytest tests/test_fixture_golden.py -v`
Expected: 2 passed.

- [ ] **Step 4: Run full suite**

Run: `.venv\Scripts\python -m pytest -q`
Expected: 96 passed (94 + 2, sample 있으면 97).

- [ ] **Step 5: Commit**

```bash
git add tests/test_fixture_golden.py
git commit -m "$(cat <<'EOF'
freeze fixture detection count as regression golden (639, pickable 27)

Well plate is the target domain but has zero labels — bounding boxes on
tests/fixtures/agar_sample.jpg don't exist yet (camera not available,
tracked as HANDOFF §6-1). The one thing we can defend right now is the
detection count on that single image, so any accidental change to the
well_8 pipeline surfaces immediately.

This isn't an accuracy test — the count could be perfectly wrong and
still pass. It's a "did the code path change" alarm. Legitimate
algorithm improvements will update this golden with a reason in the
commit message.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: petri end-to-end 스모크 테스트 (sample/ 사용, 없으면 skip)

**Files:**
- Test: `tests/test_petri_smoke.py` (신규)

**Interfaces:** consumes `/detect`.

**목적:** 페트리 전략이 실제 이미지에서 (a) 접시를 찾고 (b) ROI 밖 검출이 사라지는지 확인. 정밀도/재현율 게이트는 걸지 않는다 (스펙 §4.3).

- [ ] **Step 1: Write tests**

Create `tests/test_petri_smoke.py`:

```python
"""페트리 전략 end-to-end 스모크. 정확도 목표는 없음 (스펙 §3.4.1).

체크만: (a) 알려진 이미지에서 ROI 를 찾는다, (b) petri 를 적용하면 ROI 밖
검출이 없거나 크게 줄어든다, (c) 알 수 없는 이미지에선 폴백해도 500 안 남.
"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

SAMPLE_13895 = Path("sample/lower-resolution/13895.jpg")
SAMPLE_349 = Path("sample/higher-resolution/bright/349.jpg")

pytestmark = pytest.mark.skipif(
    not SAMPLE_13895.exists(),
    reason="sample/ not present (git ignored, ~82MB)",
)


def test_petri_finds_dish_on_13895():
    resp = client.post("/detect", json={
        "image_path": str(SAMPLE_13895), "plate_type": "petri"
    })
    assert resp.status_code == 200
    assert resp.json()["applied_params"]["petri_roi_found"] is True


def test_petri_reduces_detections_vs_well8_on_349():
    """349.jpg 는 뚜껑 글씨가 많아 well_8 격자 밖에도 검출이 대량 발생.
    petri ROI 는 그중 접시 밖 부분을 잘라내므로 검출이 줄어야 한다.
    (정확도가 아니라 "ROI 가 실제로 잘라낸다" 는 스모크 체크.)
    """
    if not SAMPLE_349.exists():
        pytest.skip("349.jpg not present")
    payload = {"image_path": str(SAMPLE_349), "mask_walls": True}
    well = client.post("/detect", json={**payload, "plate_type": "well_8"}).json()
    petri = client.post("/detect", json={**payload, "plate_type": "petri"}).json()
    # petri 가 접시를 찾았을 때만 유의미한 감소를 기대. 못 찾으면 폴백 = well_8 과 유사.
    if petri["applied_params"]["petri_roi_found"]:
        assert petri["count"] <= well["count"]
```

- [ ] **Step 2: Run**

Run: `.venv\Scripts\python -m pytest tests/test_petri_smoke.py -v`
Expected: sample 있으면 2 passed. 없으면 2 skipped.

- [ ] **Step 3: Full suite**

Run: `.venv\Scripts\python -m pytest -q`
Expected: 98 passed 또는 skipped 포함.

- [ ] **Step 4: Commit**

```bash
git add tests/test_petri_smoke.py
git commit -m "$(cat <<'EOF'
add petri end-to-end smoke test against sample/ images

Not an accuracy gate — spec §3.4.1 explicitly declines one for petri
since sample/ isn't the target domain. These tests just verify the
plumbing works: /detect with plate_type=petri actually reaches the
strategy, the ROI runs, and detections outside the circle drop when a
dish is found. Skipped when sample/ isn't checked out (~82MB, git
ignored).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: 문서 갱신 + 죽은 코드 정리

**Files:**
- Modify: `README.md`
- Modify: `docs/detection_parameters.md`
- Modify: `docs/superpowers/HANDOFF-2026-07-28.md` (§5 상태 갱신)
- Modify: `app/detector.py` (`_plate_roi`, `_well_mask` 은 well8 이 여전히 참조 — **삭제하지 않음.** 대신 docstring 에 "app/plates/well8 에서 사용" 참조 추가)

- [ ] **Step 1: Add plate_type usage to README.md**

`README.md` 의 "요청 필드" 섹션(또는 유사 위치)에 추가:

```markdown
### `plate_type` — 용기 종류 (신규)

값 | 동작
---|---
`"well_8"` (기본) | 기존 4×2 웰 플레이트 격자 ROI
`"petri"` | 원형 페트리 접시 ROI. 접시 검출 실패 시 전체 이미지로 폴백

`plate_type` 을 지정하지 않은 요청은 기존과 100% 동일하게 동작합니다.
`invert` 를 함께 생략하면 전략이 명암 극성을 결정합니다 (well_8 은 항상
어두운 콜로니, petri 는 픽셀 분포로 자동 추정).

응답의 `applied_params` 에 `plate_type`, 확정된 `invert`, (petri 일 때)
`petri_roi_found` 가 실립니다.
```

- [ ] **Step 2: Update docs/detection_parameters.md**

`docs/detection_parameters.md` 상단에 새 섹션 추가 (기존 내용 보존):

```markdown
## `plate_type` (신규, 2026-07-28)

...(README와 같은 요약, 상세 스펙 링크: docs/superpowers/specs/2026-07-28-plate-strategy-design.md)
```

- [ ] **Step 3: Mark §5 as implemented in HANDOFF**

`docs/superpowers/HANDOFF-2026-07-28.md` §5 헤더에 `[구현 완료 2026-XX-XX]` 배지 추가하고, §5.4 성공 판정 아래에 실측 결과 요약:

```markdown
### 실측 결과

- 기존 74개 테스트: `test_models.py:12` 한 줄만 수정 (invert 기본값 None), 나머지 무수정 통과
- fixture 검출 개수 golden: 639 유지 (tests/test_fixture_golden.py)
- petri 접시 검출 성공률: sample/ 39장 중 31장 (프로토타입 실측 반영)
- 최종 테스트 개수: 98 (기존 74 + 신규 24)
```

- [ ] **Step 4: Add legacy-function note in detector.py**

`app/detector.py` 의 `_plate_roi`, `_well_mask` docstring 첫 줄 뒤에 각각 한 줄 추가:

```python
    """[기존 docstring 첫 문장]

    현재 이 함수는 app/plates/well8.py 의 Well8Strategy 가 감싼다. 직접
    호출은 배제하고 get_plate("well_8").roi() 를 통해 사용할 것.
    """
```

- [ ] **Step 5: Run full suite one more time**

Run: `.venv\Scripts\python -m pytest -q`
Expected: 98 passed (또는 sample 없으면 skip 포함).

- [ ] **Step 6: Commit**

```bash
git add README.md docs/detection_parameters.md docs/superpowers/HANDOFF-2026-07-28.md app/detector.py
git commit -m "$(cat <<'EOF'
document plate_type and mark strategy separation complete

README + docs/detection_parameters.md gain a plate_type section, and the
HANDOFF doc §5 flips from "approved, implementation not started" to
implemented with the measured results (74/74 legacy tests unchanged
save the one intentional line, fixture golden count 639 held, 98 total
tests pass).

_plate_roi and _well_mask stay in detector.py because well8.py delegates
to them — dropping them would be a real refactor with subtle risk on
the well plate path we can't measure yet. Docstrings now point at
Well8Strategy so future readers don't call them directly.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

**1. Spec coverage:** 스펙 §1~§7 순회.
- §2 목표/비목표 → Task 3, 7 이 페트리 정확도 목표 없음을 명시적으로 반영. ✓
- §3.1 분리 지점 → Task 2 (well_8 이동), Task 3 (petri 신규). ✓
- §3.2 모듈 구조 → Task 1~3 이 base/well8/petri/__init__ 정확히 생성. ✓
- §3.3 well_8 코드 이동만 → Task 2 Step 1 이 byte-equality 테스트로 강제. ✓
- §3.4 petri ROI → Task 3 이 프로토타입 로직 그대로 이동. ✓
- §3.4.1 페트리 예상 성능 → Task 3 커밋 메시지에 명시. ✓
- §3.5 API 변경 → Task 5. plate_type 필드, invert bool|None, petri_roi_found. ✓
- §3.6 데이터 흐름 → Task 4, 5 순서대로 배선. ✓
- §4.1 회귀 → Task 4 Step 5, Task 5 Step 7 이 명시적 롤백 조건. test_models.py:12 예외는 스펙 §3.5 이 허용. ✓
- §4.2 petri 동작 → Task 7 스모크. ✓
- §4.3 측정 수단 → 이미 `scripts/evaluate_labeled.py` 존재. Task 에 재검증 스텝은 굳이 안 넣음 (기존 도구 무변경).
- §5 목업 → 이미 이전 커밋에서 반영됨. 이 계획엔 목업 변경 없음. ✓
- §6/§7 결정 로그·후속 → 이 계획의 범위 아님. ✓

**2. Placeholder scan:** 없음. 모든 태스크가 실제 코드 블록으로 되어 있음.

**3. Type consistency:**
- `RoiResult(mask, metadata)` — Task 1 정의, Task 2/3/4 에서 일관 사용. ✓
- `detect_with_metadata(...) -> tuple[list, dict]` — Task 4 정의, Task 5 에서 사용. ✓
- `get_plate(str) -> PlateStrategy` — Task 1 정의, Task 2/3/4/5 에서 일관. ✓
- `plate_type: str = "well_8"` (detector), `Literal["well_8","petri"] = "well_8"` (모델) — 의도적 차이 (detector 는 유연, 모델은 엄격 검증). ✓

**4. 사용자 요청 (E: 골든 fixture) 커버:** Task 6 이 정확히 이 요구를 만족. ✓

---

## 총 산출물

| 신규 파일 | 라인 (개산) |
|---|---:|
| app/plates/__init__.py | ~30 |
| app/plates/base.py | ~35 |
| app/plates/well8.py | ~20 |
| app/plates/petri.py | ~90 |
| tests/test_plates_registry.py | ~25 |
| tests/test_plates_well8.py | ~35 |
| tests/test_plates_petri.py | ~65 |
| tests/test_detector_plate_type.py | ~50 |
| tests/test_detect_plate_type_endpoint.py | ~55 |
| tests/test_fixture_golden.py | ~30 |
| tests/test_petri_smoke.py | ~40 |

**수정 파일:** `app/config.py` (+7 상수), `app/detector.py` (detect 리팩터 + detect_with_metadata 신규), `app/models.py` (plate_type 추가 + invert 완화), `app/api.py` (_detect_and_score 리팩터), `tests/test_models.py` (1줄), `README.md`, `docs/detection_parameters.md`, `docs/superpowers/HANDOFF-2026-07-28.md`.

**최종 테스트 수:** 74 → **98** (신규 24).
