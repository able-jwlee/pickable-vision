# 오퍼레이터용 파라미터 기능 — 작업 요약

**작성일:** 2026-07-28
**브랜치:** `feature/operator-parameters` (7 커밋)
**베이스:** `main` (`36c9cba`)
**HEAD:** `e3cd527`
**상태:** 구현 완료 · 전체 브랜치 리뷰 통과 (APPROVED_WITH_MINOR) · 병합 전 2가지 정리 사항 대기

---

## 1. 무엇을 만들었나

로봇 오퍼레이터가 CV 내부 파라미터(threshold_offset, min_area 등)를 몰라도 콜로니 검출 감도·크기·경계를 조절할 수 있도록, **0~100 스케일 추상 파라미터** 4개를 `POST /detect` API에 추가했다.

기존 클라이언트는 그대로 raw 필드로 요청 가능(backwards compat). 오퍼레이터 UI(별도 프로젝트)는 4개 슬라이더만 다루면 됨.

**4개 추상 필드:**
- `sensitivity` (0~100) — 흐린 콜로니 재현율
- `min_size` (0~100) — 최소 크기 필터
- `max_size` (0~100) — 최대 크기 필터
- `edge_margin` (0~100) — 웰 벽 근처 안전 여백

---

## 2. 브레인스토밍에서 나온 설계 결정

| 항목 | 선택 | 대안 |
|---|---|---|
| 대상 사용자 | 로봇 오퍼레이터 (A) | 랩 엔지니어(B), 개발자(C) |
| 조절 목적 우선순위 | A(재현율) > B(크기) > D(아티팩트) | — |
| 파라미터 은유 | 도메인 직관형 ("감도") | 사진편집기 ("밝기/명암") |
| 슬라이더 스케일 | 0~100 추상 | CV 원본 단위 (px, offset) |
| 크기 필터 UI | min/max 슬라이더 2개 | dual-thumb range 하나 |
| `tophat_kernel` 노출 | 숨김 (하드코드) | "그림자 제거" 슬라이더 |
| 프리셋 | 미포함 | 3~4 프리셋 버튼 |
| 라이브 프리뷰 | Apply 버튼식 | 슬라이더 변경 시 자동 |
| API 배치 | 기존 요청에 필드 추가 | `/detect/simple` 신설 |

**경쟁사 리서치 (Pickolo, QPix, PIXL, OpenCFU, ClonePix, ImageJ, CellProfiler)** 결과, 공통 must-have knob 5개 확인: (1) 감도 (2) min/max 크기 (3) 원형도 (4) 이웃 간격 (5) ROI/경계. 이 프로젝트 고유 knob: `split_touching`, `pick_top_n` — UI에서 유지·강조.

---

## 3. 산출물

### 설계 문서
- **`docs/superpowers/specs/2026-07-28-operator-parameters-design.md`** — 스펙 (배경, 사용자, 컨트롤 목록, 매핑 표, API 계약, 검증 계획, 결정 로그)
- **`docs/superpowers/plans/2026-07-28-operator-parameters-backend.md`** — 구현 플랜 (7 tasks, TDD 사이클, 완전한 코드 블록)

### UI 목업
- **`docs/mockup/operator-ui.html`** — 정적 HTML + JS
  - 실제 API 서버 연동됨 (`POST /detect` 호출)
  - 슬라이더 5개 (감도, min/max 크기, 벽 여백) + 토글 (붙은 콜로니 나누기)
  - 이미지 위 SVG 오버레이:
    - 초록 점선 사각형 = 피킹 안전 여백
    - 노란/주황 원 = 최소/최대 크기 예시 (실 스케일)
    - 빨간 원 = 검출된 콜로니
    - 초록 굵은 원 = 피킹 후보
  - 파일 업로드 + 샘플 이미지 스위칭
  - 로딩 스피너, 에러 처리, 응답 통계

### 백엔드 코드 변경
- **신규:** `app/param_mapping.py` — 4개 pure 매핑 함수 + stdlib만 사용
- **신규:** `tests/test_param_mapping.py` — 앵커·극한·단조성 유닛 테스트 (12개)
- **수정:** `app/models.py` — `DetectRequest`에 추상 필드 4개, `DetectResponse`에 `applied_params`
- **수정:** `app/api.py` — `_resolve_params()` 헬퍼, 양쪽 엔드포인트에 배선
- **수정:** `tests/test_models.py` — 추상 필드 검증 (3개)
- **수정:** `tests/test_detect_endpoint.py` — 응답 구조, 우선순위, 방향성 테스트 (7개)
- **수정:** `README.md`, `docs/detection_parameters.md` — 새 필드 문서화

---

## 4. 매핑 표 (스펙 §4.2)

| 추상 필드 (0~100) | 덮어쓰는 raw | 기본값 → raw | 매핑 공식 |
|---|---|---|---|
| `sensitivity` | `threshold_offset` | 50 → +7 | 0~50: linear -3→+7 / 50~100: linear +7→+15 |
| `min_size` | `min_area` | 20 → ≈6 | `r_min = 1 + (v/100)² · 9`, `area = π·r²` |
| `max_size` | `max_area` | 75 → ≈5027 | `r_max = 10 + (v/100) · 40`, `area = π·r²` |
| `edge_margin` | `PICK_EDGE_MARGIN` | 40 → 60px | `margin = v · 1.5` |

---

## 5. 구현 진행 (7 tasks · SDD)

각 태스크는 fresh subagent가 TDD로 구현 → 리뷰 subagent 게이트 통과 → 커밋.

| # | 태스크 | 커밋 | 모델(구현/리뷰) | 상태 |
|---|---|---|---|---|
| 1 | `param_mapping.py` + 유닛 테스트 | `ae6eb4b` | haiku/sonnet | ✅ Clean |
| 2 | `DetectRequest` 추상 필드 4개 | `b579072` | haiku/sonnet | ✅ Clean |
| 3 | `DetectResponse.applied_params` | `3dda586` | haiku/sonnet | ✅ Clean |
| 4 | `_resolve_params` + 엔드포인트 배선 | `90c321b` | sonnet/sonnet | ✅ PASS (1 nit) |
| 5 | 방향성 테스트 (실 샘플 이미지) | `1a89825` | sonnet/sonnet | ✅ Clean |
| 6 | README + docs 갱신 | `b6ab659` | haiku/haiku | ✅ Clean |
| 7 | 목업 abstract 필드로 스위칭 | `e3cd527` | sonnet/sonnet | ✅ Clean |

**최종 테스트 스위트:** 74/74 통과 (기존 51 + 신규 23) · 회귀 없음 · 출력 pristine.

---

## 6. 검증 결과 (End-to-End)

- **회귀 없음**: 기존 요청 없이 새 필드 미지정 시 서버 응답 완전 동일.
- **우선순위 동작**: 새 필드 + raw 필드 동시 전송 시, 새 필드가 이김. `applied_params`에 실제 사용값 반영.
- **방향성 정합**: 실제 샘플 이미지(`agar_sample.jpg`, 1350×910)로 확인
  - 감도↑ → 검출 수↑
  - 최소 크기↑ → 검출 수↓
  - 벽 여백↑ → 피킹 후보↓
- **live API 검증** (curl로 확인 완료):
  - `image_path=tests/fixtures/agar_sample.jpg` 요청 → 639 검출, 27 피킹 후보 (default 파라미터)
  - base64 업로드 payload → 동일 결과
  - CORS `Origin: null` 프리플라이트 200 OK

---

## 7. 최종 브랜치 리뷰 결과 (opus)

**Verdict: APPROVED_WITH_MINOR**

### 병합 전 처리 필요 (FIX_NOW × 2) — ✅ 둘 다 해소

**① `max_size` 앵커 정합성 (Important) — 해결 (옵션 B)**
- 문제: 스펙 §4.2가 `max_size=80 → area≈5000`이라 명시했으나 실제는 5541.8 (10.8% drift)
- **선택:** default 슬라이더값을 `80 → 75`로 변경. 매핑 공식은 그대로.
  - `r_max(75) = 10 + 0.75·40 = 40.0px` → `area = 5026.5` (raw default 5000 대비 **0.53%**)
- 반영 위치: `param_mapping.py` docstring, `tests/test_param_mapping.py` 앵커 테스트(rel 0.15 → 0.01),
  `tests/test_detect_endpoint.py` default 등가성 테스트, `README.md`, 스펙 §4.2/§5.1/§5.2,
  `docs/mockup/operator-ui.html` (슬라이더 value·표시값·리셋 default)

**② line-ending 잔여물 (Important) — 해결**
- `.gitattributes` 신설: `* text=auto` + `*.jpg/jpeg/png binary`.
- `git add --renormalize .` 결과 `tests/test_detect_endpoint.py`가 CRLF → LF로 정규화됨
  (180줄 전체 재작성. `--ignore-cr-at-eol` diff로 확인 시 실제 내용 변경은 위 ①의 2줄뿐).
- `tests/test_preview_endpoint.py`는 이미 LF여서 변화 없음.

### Backlog (병합 후 처리 가능)

- `applied_params: dict = {}` → `dict[str, object]` + `default_factory=dict`로 정리
- `applied_params`가 operator abstract 원본값(sensitivity 등)도 포함할지 검토
- `param_mapping.py`에 `__all__` 추가
- 필드 alignment whitespace 정리 (`min_size:    int | None`)
- `sensitivity_to_offset` 비엄격 단조 (v=49→50 flat, 스펙 허용)
- `test_default_abstract_matches_raw_defaults`가 count만 비교 → 전체 colony 리스트 equality로 강화
- `SAMPLE_PATH`, `_post_detect` 헬퍼 파일 상단으로 이동
- 스펙 §4.2 vs §4.3 comment 문구 discrepancy (docs 수정)

---

## 8. 사용법

### 서버 실행
```
cd C:\Users\user\Desktop\dev\2026\pickable\vision
.venv\Scripts\python main.py
# → http://localhost:7780
```

### 목업 확인
브라우저에서 열기:
```
C:\Users\user\Desktop\dev\2026\pickable\vision\docs\mockup\operator-ui.html
```
- 샘플 이미지 자동 로드 → [적용] 클릭 → 실제 검출 결과 SVG로 그려짐

### API 호출 예 (curl)
```bash
curl -X POST http://localhost:7780/detect \
  -H 'Content-Type: application/json' \
  -d '{
    "image_path": "tests/fixtures/agar_sample.jpg",
    "sensitivity": 65,
    "min_size": 30,
    "max_size": 75,
    "edge_margin": 50,
    "split_touching": true
  }'
# → 응답에 colonies[] 배열 + applied_params dict 포함
```

### 테스트
```
.venv\Scripts\python -m pytest -v
# → 74/74 passed
```

---

## 9. 다음 단계

FIX_NOW 2건 처리 완료 · 테스트 74/74 통과 · PR 생성으로 마무리.

**남은 일 (다음 사이클):** §7 Backlog Minor 8건. 기능 영향 없음.
