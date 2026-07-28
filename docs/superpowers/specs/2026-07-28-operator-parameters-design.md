# 오퍼레이터용 검출 파라미터 설계

**작성일:** 2026-07-28
**대상 서비스:** PICKABLE Vision Server (`vision/`)
**목적:** 로봇 오퍼레이터가 이해할 수 있는 수준으로 콜로니 검출 파라미터를 재구성해, 매 플레이트마다 필요한 조정을 스스로 할 수 있게 한다.

---

## 1. 배경

현재 `POST /detect`는 `threshold_offset`, `min_area`, `tophat_kernel` 등 CV 원본 파라미터를 그대로 노출한다. `docs`(Swagger UI)에서 개발자가 튜닝하기엔 적합하지만, 로봇 오퍼레이터가 손대기엔 용어·범위·상호작용이 모두 낯설다.

오퍼레이터가 자주 겪는 상황은 다음 세 가지로 요약된다 (우선순위 순):

| 우선순위 | 시나리오 | 이 스펙에서 해결 |
|---|---|---|
| A | "빠진 콜로니가 있어" 재현율 조절 | ✅ 감도 슬라이더 |
| B | "이 콜로니는 너무 커서/작아서 안 집었으면" 크기 필터 | ✅ 최소·최대 크기 슬라이더 |
| D | "이건 벽에 붙은 얼룩이야" 경계 아티팩트 제외 | ✅ 벽 여백 슬라이더 |

## 2. 사용자와 범위

**대상 사용자:** 로봇 오퍼레이터. CV 배경 없음. 매일 다른 플레이트를 놓고 검출 결과를 확인·조정하는 사람.

**범위 안 (이 스펙):**
- `DetectRequest`에 오퍼레이터용 0~100 스케일 필드 4개 추가.
- 0~100 → CV 원본값 매핑 모듈 및 유닛 테스트.
- `DetectResponse`에 실제 적용된 raw 파라미터 되반환 (`applied_params`).
- 오퍼레이터 뷰 UI 목업 HTML (참조용, 프론트엔드 개발자가 실제 UI 구축 시 참고).

**범위 밖 (향후 단계):**
- 실제 프론트엔드 UI 구현.
- 파라미터 프리셋 저장/불러오기 (dense/sparse 등). 실사용 후 필요성 확인 후 별도 스펙.
- 라이브 프리뷰(파라미터 변경 시 자동 재검출). 이 스펙은 "Apply 버튼" 모델을 상정.
- 프론트엔드 인증·CORS 세부.

## 3. 경쟁사 리서치 요약

**공통 must-have knob** (QPix, PIXL, Pickolo, OpenCFU, ClonePix, ImageJ, CellProfiler 전반):
1. 감도(threshold) 2. min/max 크기 3. 원형도 4. 이웃 간격 5. ROI/경계

이 프로젝트만의 고유 knob: `split_touching`(watershed 토글), `pick_top_n`(랭킹 상한). 경쟁사 UI에서 명시적으로 노출하지 않는 knob이라, 오퍼레이터 UI에서 유지·강조할 가치 있음.

`min_circularity`(원형도)는 현재 config에서 검출용/피킹용 두 개로 이미 하드코드돼 있고 로봇 안전과 직결되므로 오퍼레이터에게 노출하지 않는다. 튜닝을 원할 경우 raw 필드로 계속 접근 가능.

## 4. 설계 결정

### 4.1 노출할 컨트롤 (7개)

**메인 5개**

| 컨트롤 | 타입 | 범위/기본값 | 내부 매핑 | 방향 |
|---|---|---|---|---|
| 감도 (Sensitivity) | 슬라이더 | 0–100 / 50 | `threshold_offset` | ↑ = 더 민감 |
| 최소 콜로니 크기 | 슬라이더 | 0–100 / 20 | `min_area` | ↑ = 더 엄격 |
| 최대 콜로니 크기 | 슬라이더 | 0–100 / 80 | `max_area` | ↑ = 더 관대 |
| 벽 여백 | 슬라이더 | 0–100 / 40 | `PICK_EDGE_MARGIN` | ↑ = 더 안쪽만 |
| 붙은 콜로니 나누기 | 토글 | ON | `split_touching` | — |

**보조 2개**

| 컨트롤 | 타입 | 기본값 | 내부 매핑 |
|---|---|---|---|
| 피킹 개수 | 숫자 또는 "전부" | 전부 | `pick_top_n` |
| 기본값으로 | 버튼 | — | 위 6개 리셋 |

**슬라이더 방향 규칙:** 슬라이더마다 방향이 다르기 때문에 각 슬라이더 아래에 "← 엄격 / 관대 →" 캡션을 표시한다.

### 4.2 0~100 → CV 원본 매핑

기본값(50/20/80/40)이 **현재 서버 default 요청과 동일한 검출 결과**를 내도록 앵커링.

**감도**
```
value 0    → threshold_offset = -3   (매우 엄격)
value 50   → threshold_offset = +7   (현재 default, sweet spot)
value 100  → threshold_offset = +15  (매우 민감)
```
- 0~50: linear `-3 → +7`
- 50~100: linear `+7 → +15`

**최소 콜로니 크기** (값↑ = 엄격)
```
value 0    → r_min = 1px       (min_area ≈ 3)
value 20   → r_min ≈ 1.4px     (min_area ≈ 6 — 현재 default)
value 100  → r_min = 10px      (min_area ≈ 314)
```
- 매핑: `r_min = 1 + (value/100)² · 9` (비선형)
- `min_area = π · r_min²`

**최대 콜로니 크기** (값↑ = 관대)
```
value 0    → r_max = 10px      (max_area ≈ 314)
value 75   → r_max = 40px      (max_area ≈ 5027 — 현재 default 5000에 앵커)
value 100  → r_max = 50px      (max_area ≈ 7854)
```
- 매핑: `r_max = 10 + (value/100) · 40` (linear)
- `max_area = π · r_max²`

**벽 여백** (값↑ = 안쪽만)
```
value 0    → edge_margin = 0px
value 40   → edge_margin = 60px    (현재 default)
value 100  → edge_margin = 150px
```
- 매핑: `edge_margin = value · 1.5` (linear)

**붙은 콜로니 나누기 · 피킹 개수:** 매핑 없이 그대로 전달.

### 4.3 API 계약

**`DetectRequest` 확장:**

```python
class DetectRequest(BaseModel):
    # ... 기존 raw 필드 모두 유지 (backwards compat) ...

    sensitivity: int | None = Field(None, ge=0, le=100)
    min_size:    int | None = Field(None, ge=0, le=100)
    max_size:    int | None = Field(None, ge=0, le=100)
    edge_margin: int | None = Field(None, ge=0, le=100)
```

**우선순위 로직 (`app/api.py`):**
- 새 필드가 `None`이 아니면 → 매핑 함수로 raw 값 계산 → 대응하는 raw 필드 덮어씀.
- 새 필드가 `None`이면 → 기존 raw 필드 그대로 사용.

**매핑 모듈:** `app/param_mapping.py` 신설.
- 순수 함수 4개: `sensitivity_to_offset`, `min_size_to_area`, `max_size_to_area`, `edge_to_margin`.
- 유닛 테스트 용이. 프론트엔드가 참조 구현을 원할 경우 그대로 포팅 가능.

**`DetectResponse` 확장:**

```python
class DetectResponse(BaseModel):
    # ... 기존 필드 ...
    applied_params: dict  # 실제 검출에 쓴 raw 값들
```

- `applied_params` 예: `{"threshold_offset": 7, "min_area": 6.0, "max_area": 5000.0, "edge_margin": 60, "split_touching": True, "pick_top_n": None}`.
- 오퍼레이터가 "이 조합이 좋았어"를 기록하거나, 지원팀이 이슈를 재현할 때 사용.

**Preview 엔드포인트 (`POST /detect/preview`):** 같은 요청 모델을 쓰므로 자동으로 새 필드 지원.

### 4.4 UI 참조 (목업)

프론트엔드 구현은 별개 프로젝트에서 진행되므로, 이 서버 저장소에는 정적 HTML 목업만 둔다.

**위치:** `docs/mockup/operator-ui.html`

**구성:**
- 좌측: 검출 결과 이미지 (annotated preview)
- 상단 통계 바: 총 검출 수, 피킹 후보 수
- 우측 컨트롤 패널: 슬라이더 5개 + 토글 + 피킹 개수 입력 + 리셋/적용 버튼
- 각 슬라이더 아래에 방향 캡션 ("← 엄격 / 관대 →" 등)
- Apply 버튼식 (라이브 프리뷰 아님)

목업은 자바스크립트 상호작용을 최소화하고 시각 배치만 보여준다. 프론트엔드 개발자는 이 HTML을 실제 프레임워크(React/Vue 등)로 재구현한다.

**시각 오버레이 (목업에 포함):**
- 초록 점선 사각형 = 피킹 안전 여백 (벽 여백 슬라이더에 실시간 반응).
- 노란/주황 원 두 개 = 최소/최대 콜로니 크기 예시 (min/max 크기 슬라이더에 반응). 실제 검출 스케일 그대로 그려 오퍼레이터가 이미지 속 실제 콜로니와 크기 비교 가능.
- 감도 슬라이더는 서버 재검출이 필요하므로 오버레이 없이 값만 표시.

**후속 UI 아이디어 (향후 프론트엔드 구현 시):**
- 최소/최대 크기 참조 원을 **드래그로 위치 이동** 또는 **이미지 클릭으로 이동**할 수 있게 하면 오퍼레이터가 관심 있는 콜로니 바로 옆에 놓고 비교 가능. 목업에서는 고정 위치.
- 이미지 hover 시 근처 콜로니의 반지름 툴팁 (검출 응답 좌표와 클릭 픽셀 대조 필요).
- 최근 성공한 파라미터 조합 저장/불러오기 (플레이트 타입별 preset).

## 5. 검증 계획

### 5.1 매핑 함수 유닛 테스트 (`tests/test_param_mapping.py` 신설)

- **앵커 값** (default 유지):
  - `sensitivity_to_offset(50) == 7`
  - `min_size_to_area(20)`, `6.0` 대비 ±5% 이내
  - `max_size_to_area(75)`, `5000.0` 대비 ±1% 이내
  - `edge_to_margin(40) == 60`
- **극한값**: 0, 100 입력에서 예외 없이 반환.
- **단조성**: 각 매핑 함수는 단조 증가 또는 단조 감소여야 함 (방향 반전 방지).

### 5.2 엔드포인트 회귀 테스트 (`tests/test_detect_endpoint.py` 추가)

- **default 등가성**: 새 필드 미지정 요청과 `sensitivity=50, min_size=20, max_size=75, edge_margin=40, split_touching=True` 요청이 **완전히 동일한 콜로니 리스트**를 반환.
- **우선순위**: 새 필드와 raw 필드를 동시에 보내면 새 필드가 이긴다.
- **`applied_params` 존재 확인**: 응답에 raw 값 dict가 있고, 매핑 결과와 일치.

### 5.3 방향성 테스트 (`agar_sample.jpg` 사용)

샘플 이미지 하나로 slider 방향이 상식과 일치하는지 확인.
- `sensitivity=100` count > `sensitivity=0` count
- `min_size=100` count < `min_size=0` count
- `edge_margin=100` pickable count ≤ `edge_margin=0` pickable count

### 5.4 문서 반영

- `README.md`의 `/detect` 요청 예시에 새 필드를 짧게 소개.
- `docs/detection_parameters.md`에 오퍼레이터 뷰 섹션 추가 (목업 HTML로 링크).

## 6. 마이그레이션 / 롤아웃

- 기존 raw 필드를 유지하므로 **기존 클라이언트와 테스트 모두 무변경으로 계속 동작**한다.
- 서버 배포 후 프론트엔드 개발이 새 필드를 사용하기 시작.
- 오퍼레이터가 실사용 → 프리셋 요구가 나오면 별도 스펙으로 진행.

## 7. 결정 로그 (설계 중 논의된 대안)

| 항목 | 선택 | 대안 | 이유 |
|---|---|---|---|
| 대상 사용자 | 로봇 오퍼레이터 | 랩 엔지니어 / 개발자 | 실사용 매일 접점 |
| 파라미터 은유 | 도메인 직관형 ("감도") | 사진편집기 ("밝기/명암") | "밝기"가 "감도"와 자연 매핑되지 않아 혼동 위험 |
| 슬라이더 스케일 | 0~100 추상 | CV 원본 (px, offset) | 오퍼레이터가 CV 단위 이해 못함 |
| 크기 필터 UI | min/max 슬라이더 2개 | dual-thumb range 슬라이더 하나 | Approach A 채택 결과 |
| `tophat_kernel` 노출 | 숨김 (하드코드) | "그림자 제거" 슬라이더로 노출 | 8웰 하드웨어 특성상 매 튜닝 불필요 |
| 프리셋 | 미포함 | 3~4개 프리셋 버튼 | YAGNI. 실사용 후 필요 시 |
| 라이브 프리뷰 | Apply 버튼식 | 슬라이더 변경 시 자동 재검출 | 검출 100ms~1s 지연 있어 flicker 위험 |
| API 배치 | 기존 요청에 필드 추가 | `/detect/simple` 신설 | Backwards compat + 중복 로직 방지 |
