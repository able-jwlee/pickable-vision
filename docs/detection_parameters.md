# 검출 파라미터 레퍼런스 (내부용)

> `POST /detect` 요청 파라미터를 **노출 수준·UI 컨트롤·실측 근거**로 정리한 문서.
> 대상은 개발자. 프론트엔드 연동 방법은 [react-integration.md](react-integration.md).
>
> **정본은 코드다.** 기본값·범위는 [`app/config.py`](../app/config.py),
> 스키마·검증은 [`app/models.py`](../app/models.py), 동작은
> [`app/blob_detector.py`](../app/blob_detector.py).
> 기계가 읽을 정본은 **`/openapi.json`** — 프론트 폼은 이 문서가 아니라 거기서 생성할 것.

---

## 0. 핵심 요약

- 오퍼레이터가 실제로 만지는 건 **`sensitivity` 하나**다. 나머지 기본값은 전부
  sample/ 라벨 39장(정답 1,886개) 실측 최적이라 건드릴 이유가 거의 없다.
- 기본 성적: **재현율 75.7% / 정밀도 82.2% / F1 78.8**
- 파라미터 성격 4종 → UI도 이대로 나눈다:
  1. **오퍼레이터 노브** — 항상 노출
  2. **알고리즘 파라미터** — "고급" 접힘. 기본값이 실측 최적
  3. **출력·선별** — 검출이 아니라 결과 가공
  4. **코드 전용** — 요청으로 노출 안 됨

> **한 축을 바꾸면 의존하는 축의 캘리브레이션이 무효가 된다.** 실제로 겪은 쌍:
> `work_size` ↔ 크기 창, 반지름 ↔ NMS, 반지름 ↔ `split_area_ratio`,
> `candidate_source` ↔ 모양 게이트. 하나만 바꿔 측정하면 잘못된 결론이 나온다.

---

## 1. 오퍼레이터 노브 — 항상 노출

| 파라미터 | 기본값 | 범위 | 효과 | UI |
|---|---|---|---|---|
| `sensitivity` | `50` | `0~100` | **유일한 상시 노브.** ↑ = 흐린 콜로니까지 잡음(재현율↑ 정밀도↓) | Slider |
| `polarity` | `"auto"` | auto / both / bright / dark | 콜로니가 한천보다 밝은지 어두운지 | Select |
| `plate_type` | `"petri"` | petri / well8 | 원형 접시 / 4×2 몰딩 8웰 | Select |

### `sensitivity` 실측 곡선

`min_t`(면적가중 t-통계량 하한)로 매핑된다. 낮을수록 민감.

| sensitivity | min_t | 정밀도 | 재현율 | F1 |
|---|---|---|---|---|
| 43 | 30 | 89.0% | 70.9% | 78.9 |
| 46 | 25 | 86.7% | 73.3% | **79.4** |
| **50** | **20** | **82.2%** | **75.7%** | 78.8 |
| 81 | 15 | 73.5% | 77.3% | 75.3 |

기본을 F1 최고점(46)이 아니라 50으로 둔 것은 **재현율 우선** 요구 때문이다 —
놓친 콜로니는 사람이 되살릴 수 없지만, 오검출은 승인 화면에서 뺄 수 있다.

> 매핑은 선형이 아니다. 감도 50 아래는 한 칸이 min_t 1.4, 위는 0.16 씩 움직인다.
> 그래서 50 미만에서는 슬라이더를 조금만 내려도 결과가 크게 바뀐다.

### `polarity` — `auto` 를 유지할 것

접시별 자동 판정이 39장에서 **판정 정확도 100%** 이고, 양극성 병합(`both`)보다
모든 운영점에서 재현율이 3%p 이상 높다. 틀린 극성 분기는 기여 없이 오검출만 더했다.

`both` 는 자동 판정이 틀리는 접시가 발견됐을 때의 되돌림 경로다.

---

## 2. 알고리즘 파라미터 — "고급" 접힘

**기본값이 이미 실측 최적이다.** 노출은 하되 접어둔다.

| 파라미터 | 기본값 | 효과 | 실측 |
|---|---|---|---|
| `candidate_source` | `"union"` | LoG ∪ 이진화 | 전 구간에서 LoG 단독보다 **+2.9~3.5%p** |
| `threshold_levels` | `24` | 이진화 레벨 수 | 12/24/36 → 67.9/70.8/71.3%. 24에서 포화 |
| `work_size` | `1280` | 처리 해상도(최대변) | 콜로니당 픽셀 수가 t-통계량을 좌우 |
| `min_solidity` | `0.75` | 면적 ÷ convex hull | 0.75 아래로는 결과 불변(포화) |
| `min_roundness` | `0.55` | 면적 ÷ 최소외접원 | **완화 권장 안 함** ↓ |
| `min_circularity` | `0.0` (끔) | 둘레 기반 4πA/P² | 경계 거칠기에 과민 → 껐다 |
| `min_fill` | `0.45` | bounding box 채움율 | 0.60으로 올리면 고정밀 구간 +1.4~2.1%p |
| `watershed_split` | `true` | 붙은 콜로니 분리 | **끄면 나빠지기만 한다** |
| `split_area_ratio` | `1.5` | 병합 판정 배수 | 낮출수록 적극 분리 |
| `colour_credit` | `1.0` (끔) | 색이 뚜렷하면 감도 완화 | 이미지 종류별로 최적이 갈림 ↓ |
| `min_diam_frac` / `max_diam_frac` | `0.0` (끔) | 크기 창 ÷ 접시 지름 | 실측 분포 1.2~45%, 중앙값 7% |
| `adaptive_scale` | `false` | 1차 검출로 해상도 재조정 | 비용 2배, F1은 오히려 하락 |

### 주의가 필요한 세 개

**`min_roundness` — 완화하지 말 것.** 직관과 반대로, 모양 게이트를 푸는 것보다
**감도를 내리는 쪽이 같은 정밀도에서 더 많이 맞힌다.**

정밀도 82.8% 로 맞춰 비교하면:

| 방법 | 정밀도 | 재현율 |
|---|---|---|
| 둥글기 0.45 + t30 | 82.8% | 72.5% |
| **둥글기 0.55 + t≈19 (기본값 유지)** | 82.8% | **74.7%** |

**+2.2%p.** 둥글기를 푸는 건 곡선을 올리는 게 아니라 **곡선 위를 나쁜 방향으로
미끄러지는 것**이다. 전 구간에서 그렇다 — 0.45 곡선은 0.55 곡선 아래에 있고,
0.35·0.25 는 더 아래다.

**`min_circularity` — 껐다 (2026-08-07).** 둘레 기반이라 경계 거칠기에 극도로
민감하다. 합집합 후보의 이진화 성분은 둘레가 거칠어서 부당하게 버려졌다.
끄자 같은 감도에서 재현율 74.4 → 75.7%. 모양 판정은 면적 기반 `min_roundness` 가 맡는다.

**`colour_credit` — 용도에 따라 갈린다.** 2배로 주면 `vague` 그룹은 F1 26.1→40.9로
살아나지만 `lower-res` 는 77.6→61.6으로 무너진다. 전역 기본값으로 삼을 수 없다.

### `candidate_source` — 용도별 선택

| 값 | 언제 |
|---|---|
| `"union"` (기본) | 재현율 우선 — 피킹 |
| `"threshold"` | 정밀도 93% 이상 구간에서 합집합보다 낫다 (94%에서 67.3% 대 62.9%) — **계수(CFU) 용도** |
| `"log"` | 구동작 |

두 방식이 **서로 다른 것을 본다.** LoG는 흐리고 경계가 불분명한 것을, 이진화는
경계가 뚜렷하고 크기가 제각각인 것을 잡는다. 그래서 합집합이 이긴다.

---

## 3. 출력·선별 — 검출이 아니라 결과 가공

| 파라미터 | 기본값 | 효과 | UI |
|---|---|---|---|
| `pick_top_n` | `null` | 피킹 후보 중 상위 N개만 (96핀 → 96) | Number (선택) |
| `mask_walls` | `true` | 경계 안쪽만 피킹 인정 | Switch (고급) |
| `edge_margin` | `null` | 0~100 → 안전 여백(px) | Slider (고급) |
| `pick_radius_min/max` | `null` | 피킹 반지름 대역(**원본 px**) | 카메라 바꾸면 재조정 |
| `annotate` | `"all"` | 표시 모드. all=전체 빨강 / pick=대상만 초록 | Toggle |

`score`·`pickable` 은 **랭킹과 안전 판정**이지 검출 품질이 아니다. JSON은 어느
모드에서든 전부 반환된다.

---

## 4. 노출하지 말 것

개발·디버깅용. 프로덕션 UI에 넣지 않는다.

| 파라미터 | 이유 |
|---|---|
| `image_path` | 서버와 파일시스템을 공유할 때만 동작. 운용에선 차단 |
| `save_annotated` | 서버 디스크에 파일을 쓴다 |
| `return_image` | 260KB base64. 좌표(3.9KB)를 쓸 것 |
| `image_format` / `image_quality` / `image_max_width` / `marker` | `return_image` 부속 |

---

## 5. 코드 전용 — 요청으로 노출 안 됨

`config.py` 에만 있다. 알고리즘 내부라 UI에 넣지 말 것.

- **t-통계량 표본 영역**: `BLOB_INNER_FRAC`(0.80), `BLOB_OUTER_LO`(1.4), `BLOB_OUTER_HI`(2.8)
- **반지름 보정**: `BLOB_RADIUS_MODE`("max"), `BLOB_RADIUS_SCALE`(1.30)
- **극성 자동판정**: `BLOB_AUTO_POLARITY`(True), `BLOB_POLARITY_MIN_MARGIN`(0.05)
- **모양**: `BLOB_MAX_ASPECT`(2.0)
- **잡음·채도**: `BLOB_NOISE_FLOOR`(0.5), `BLOB_MONO_SAT_STD`(2.0), `BLOB_MIN_REL_SAT`(1.5)
- **웰 격자**: `WELL_ROWS`(2), `WELL_COLS`(4), `WELL_MARGIN`(40)
- **피킹 점수**: `PICK_W_ISOLATION`(0.7), `PICK_W_SIZE`(0.3), `PICK_ISOLATION_REF`(50.0)
- **그리기**: `OUTPUT_DIR`, `DRAW_*`, `DRAW_MARKER_PAD`(1.05)

> `DRAW_MARKER_PAD` 는 `BLOB_RADIUS_SCALE` 과 **함께 움직인다.** 한때 1.35(옛 0.71배
> 반지름 보정용)와 새 1.30배가 곱해져 마커가 35% 크게 그려졌다.

### 죽은 상수 (정리 대상)

top-hat 경로 제거 후 남은 미참조 상수. 어디서도 쓰이지 않는다:

```
DEFAULT_MIN_AREA  DEFAULT_MAX_AREA  DEFAULT_MIN_CIRCULARITY  DEFAULT_INVERT
DEFAULT_TOPHAT_KERNEL  DEFAULT_THRESHOLD_OFFSET  DEFAULT_SPLIT_TOUCHING
MENISCUS_MIN_LEN  MENISCUS_MIN_ASPECT  WATERSHED_MIN_DISTANCE  WATERSHED_SEED_MIN
```

---

## 6. 프리셋

목업([operator-ui.html](mockup/operator-ui.html))에 구현된 것. 감도 값은 실측점에서 역산했다.

| 프리셋 | `sensitivity` | min_t | 정밀도 | 재현율 |
|---|---|---|---|---|
| 기본 | 50 | 20 | 82.2% | 75.7% |
| 덜 찾더라도 정확하게 | 43 | 30 | 89.0% | 70.9% |
| 놓치지 않게 많이 찾기 | 81 | 15 | 73.5% | 77.3% |

---

## 7. 검증 규칙 — 폼에서 미리 막을 것

`models.py` 기준. 어긋나면 422가 뒤늦게 뜬다.

| 파라미터 | 제약 |
|---|---|
| `min_t` | `1.0 ≤ v ≤ 200.0` |
| `sensitivity` / `edge_margin` | `0 ≤ v ≤ 100` (int) |
| `work_size` | `384 ≤ v ≤ 2048` |
| `threshold_levels` | `2 ≤ v ≤ 64` |
| `min_solidity` / `min_roundness` / `min_circularity` / `min_fill` | `0.0 ≤ v ≤ 1.0` |
| `min_diam_frac` / `max_diam_frac` | `0.0 ≤ v ≤ 1.0` |
| `colour_credit` | `1.0 ≤ v ≤ 8.0` |
| `split_area_ratio` | `0.5 ≤ v ≤ 5.0` |
| (소스) | `image` 또는 `image_path` 중 하나 필수 |

**이 표를 손으로 옮기지 말 것.** `/openapi.json` 에 전부 들어 있고,
`openapi-typescript` 로 뽑으면 서버가 바뀔 때 빌드가 깨져서 알려준다.

---

## 8. 관련 문서

- [react-integration.md](react-integration.md) — 프론트엔드 연동
- [detection-improvement-2026-07-28.md](detection-improvement-2026-07-28.md) — 실측 이력과 기각한 시도들
- [app/config.py](../app/config.py) — 상수별 곡선과 기각 사유 (가장 상세)
