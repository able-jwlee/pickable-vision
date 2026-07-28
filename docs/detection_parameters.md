# 검출 파라미터 레퍼런스 (내부용)

> `POST /detect` 요청 파라미터를 **그룹·노출 수준·UI 컨트롤**로 정리한 문서.
> 대상은 개발자(나중에 `ui/`에 컨트롤을 붙일 때 참고). 유저에게 그대로 공유하는 문서는 아님.
>
> 출처(단일 진실): 기본값·범위는 [`vision/app/config.py`](../app/config.py),
> 요청 스키마·검증은 [`vision/app/models.py`](../app/models.py),
> 파이프라인 동작은 [`vision/app/detector.py`](../app/detector.py).
> **이 문서와 코드가 어긋나면 코드가 맞다.** 값을 바꾸면 이 표도 같이 고칠 것.

---

## 0. 핵심 요약 (TL;DR)

- 실사용에서 유저가 만지는 건 사실상 **`threshold_offset` 하나**. 나머지는 대부분 셋업당 1회 고정.
- 파라미터는 성격이 4종류로 갈린다 → UI도 이 그룹대로 나눠야 한다:
  1. **검출 노브** — 자주 조절, 앞에 크게 노출
  2. **셋업 파라미터** — 이미징 환경 의존, "고급" 접힘 영역
  3. **출력·선별** — 검출 자체가 아니라 결과 가공
  4. **코드 전용(숨김)** — 요청으로 노출 안 됨, `config.py`에서만

---

## 1. 검출 노브 — 자주 조절 (UI 전면 노출)

검출 "조건"을 실제로 바꾸는 값들. UI에서 제일 눈에 띄게.

| 파라미터 | 기본값 | 범위(검증) | 방향 / 효과 | UI 컨트롤 제안 |
|---|---|---|---|---|
| `threshold_offset` | `7` | `-50 ~ +50` (권장 sweet spot **-4 ~ +10**) | **민감도 메인 노브.** ↑(양수) = 임계값↓ = 흐린/작은 콜로니까지 더 잡음(노이즈↑). ↓(음수) = 엄격. 기본 +7은 "plate를 반듯하게 꽉 채워 촬영" 전제에서 흐린 콜로니 재현율을 최대화한 튜닝값. +8↑부터 노이즈, +10↑에서 임계값 바닥 | **Slider** (범위 -10~+10 노출, step 1). 실시간 preview와 묶으면 최고 |
| `min_area` | `6.0` | `≥ 0`, `< max_area` | 이 넓이(px²) 미만 컷 → 작은 speck 제거 | Number input 또는 슬라이더 |
| `max_area` | `5000.0` | `> 0`, `> min_area` | 이 넓이 초과 컷 → 병합된 큰 덩어리 제거 | Number input |
| `min_circularity` | `0.42` | `0.0 ~ 1.0` | 원형도 하한. 낮추면 찌그러진 모양도 통과 | Slider (0~1, step 0.05) |
| `split_touching` | `true` (**on**) | bool | 붙은 콜로니를 watershed로 분리. 밀집 구간 재현율↑, 과분할 위험 | **Switch** |

> **부호 주의:** `threshold_offset`는 detector에서 `thresh = otsu - offset`로 쓰인다
> ([detector.py](../app/detector.py) 참고). 즉 **올릴수록 더 민감**. UI 카피도 이 방향으로.

---

## 2. 셋업 파라미터 — 환경 의존, 평소 고정 (UI "고급" 접힘)

이미징 하드웨어/plate 종류가 정해지면 거의 안 바뀐다. 초보 유저에게 노출하면 오히려 망가뜨림 → 접힌 "고급 설정"에.

| 파라미터 | 기본값 | 방향 / 효과 | UI 컨트롤 제안 |
|---|---|---|---|
| `invert` | `true` | 콜로니가 배경보다 어두우면 `true`(black top-hat). 조명/plate에 따라 1회 결정 | Switch (고급) |
| `tophat_kernel` | `31` | top-hat 구조요소 크기(px). 콜로니보다 커야 함. `≥ 3` 검증 | Number input (고급) |
| `mask_walls` | `true` | 8웰(2×4) 격자 안쪽으로만 검출 제한. plate 구조 바뀔 때만 | Switch (고급) |

---

## 3. 출력·선별 — 검출이 아니라 결과 가공

| 파라미터 | 기본값 | 효과 | UI 컨트롤 제안 |
|---|---|---|---|
| `pick_top_n` | `null` | 피킹 후보 중 점수 상위 N개만 남김 (예: 96핀 → 96) | Number input (선택). 핀 수와 연동하면 자동 채움 |
| `annotate` | `"all"` | 표시 모드. `"all"`=검출 전체 빨강(카운트/분석), `"pick"`=피킹 대상(pickable)만 초록(로봇이 실제 집을 안전 후보만). JSON 값은 두 모드 동일 | **Toggle** "검출 전체 / 피킹 대상만". 운영 화면은 `"pick"` 기본 권장 |
| `save_annotated` | `false` | 검출 표시 이미지를 `vision/output/`에 저장 (로컬 디버그용) | 개발/디버그 토글. 프로덕션 UI에선 숨김 후보 |
| `image` / `image_path` | — | 입력 소스(base64 / 로컬 경로). 둘 중 하나 필수 | UI에선 카메라 캡처가 자동 채움 → 노출 안 함 |

---

## 4. 코드 전용 (숨김) — 요청으로 노출 안 됨

`config.py`에만 있고 `DetectRequest`에 없다. 하드웨어·알고리즘 튜닝용이라 **UI에 넣지 말 것**. 바꿀 일이 생기면 코드 리뷰를 거쳐 config에서.

- ROI 마스크: `ROI_CLOSE_KERNEL`(35), `ROI_ERODE_KERNEL`(45 — 벽 오검출 방지용으로 상향). `_well_mask`가 격자 마스크 ∩ 침식 ROI를 반환해 바깥벽 제외
- 메니스커스 제거: `MENISCUS_MIN_LEN`(80), `MENISCUS_MIN_ASPECT`(4.0) — 벽면 agar 주름(길고 얇은 선형 성분)을 watershed 전에 제거. 콜로니/클러스터(compact)는 보존. `_remove_wall_streaks`
- 웰 격자: `WELL_ROWS`(2), `WELL_COLS`(4), `WELL_MARGIN`(40)
- watershed: `WATERSHED_MIN_DISTANCE`(5), `WATERSHED_SEED_MIN`(2.0)
- 피킹 점수/안전: `PICK_MIN_SEPARATION`, `PICK_ISOLATION_REF`, `PICK_RADIUS_MIN/MAX`, `PICK_W_ISOLATION`, `PICK_W_SIZE`
  - `PICK_MIN_CIRCULARITY`(0.55) — 피킹 대상 둥글기 하한(병합/균열/데브리 배제). 검출용(0.42)보다 엄격
  - `PICK_EDGE_MARGIN`(60) — 웰/plate 경계에서 이만큼 안쪽만 피킹 인정(벽 반점에 핀 찍기 방지)
  - 피킹 안전 3중 게이트 = 고립(분리거리) + 크기대역 + 둥글기 + 경계여백. 검출(빨강)은 그대로 두고 피킹 대상(pickable)만 좁힘
- 그리기: `OUTPUT_DIR`, `DRAW_*`, `MIN_DRAW_RADIUS`

---

## 5. 향후 UI 구현 메모

- **레이아웃:** ① 상단에 `threshold_offset` 슬라이더(+ live preview) → ② "필터"(area/circularity/split) → ③ Accordion "고급 설정"에 셋업 파라미터. shadcn `Slider`/`Switch`/`Accordion` 이미 설치돼 있음.
- **폼 검증:** 프론트 zod 스키마를 백엔드 검증과 **동일하게** 맞출 것 (아래 §6). 어긋나면 422가 뒤늦게 뜬다.
- **프리셋:** 자주 쓰는 조합(예: "민감/표준/엄격")을 버튼 프리셋으로 두면 유저가 개별 노브를 안 만져도 됨 — 사용성 최상.
- **live preview:** `POST /detect/preview`가 이미 있고([api.py:88](../app/api.py#L88)) 같은 `DetectRequest`를 받아 표시 이미지(`PreviewResponse.image`)를 돌려준다. 슬라이더 드래그 → 이 엔드포인트 호출 → 즉시 반영이 가장 직관적.
- **미노출 권장:** `save_annotated`(디버그), `image_path`(서버 파일시스템 공유 시에만 동작). 카메라 플로우에선 `image`(base64)만.

---

## 6. 검증 규칙 (프론트 zod와 일치시킬 것)

`models.py` 기준 현재 강제되는 제약:

| 파라미터 | 제약 |
|---|---|
| `min_circularity` | `0.0 ≤ v ≤ 1.0` |
| `tophat_kernel` | `v ≥ 3` |
| `threshold_offset` | `-50 ≤ v ≤ 50` |
| `min_area` | `v ≥ 0` |
| `max_area` | `v > 0` |
| (교차) | `min_area < max_area` |
| (소스) | `image` 또는 `image_path` 중 하나 필수 |

---

## 오퍼레이터용 파라미터 (0~100 스케일)

로봇 오퍼레이터를 위해 CV 원본 파라미터의 사용성을 다듬은 4개 슬라이더 값. `POST /detect`/`POST /detect/preview`에 `sensitivity`, `min_size`, `max_size`, `edge_margin` (모두 `int`, 0~100, 선택) 필드로 전달한다.

지정된 필드는 대응 raw 필드를 덮어쓴다. 미지정이면 기존 raw 필드 또는 config 상수를 그대로 사용해 backwards compat이 유지된다. 매핑은 `app/param_mapping.py`에서 pure function으로 구현되어 있으며, 프론트엔드가 참조 구현이 필요하면 그대로 포팅할 수 있다.

응답의 `applied_params` dict에 실제 사용된 raw 값이 담긴다 — 튜닝 로그·재현·이슈 리포트 용도.

설계 근거·매핑 상세: `docs/superpowers/specs/2026-07-28-operator-parameters-design.md`.
