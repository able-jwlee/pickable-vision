# React 프론트엔드 연동 가이드

> 대상: PICKABLE 오퍼레이터 UI를 React로 만드는 개발자.
> 서버는 `vision/` (FastAPI, 기본 `http://localhost:7780`).
> 실제 API와 통신하는 목업은 [operator-ui.html](mockup/operator-ui.html) — 순수 HTML/JS 단일 파일.
> 4축 화면 구성(§6·§8~10)의 참고 구현은
> [operator-ui-4axis.html](mockup/operator-ui-4axis.html) — 정적 목업, "개발자 노트"에
> 컨트롤 ↔ 필드 매핑이 있다.

---

## 0. 30초 요약

```
docs/openapi.json         → 파라미터 스키마 (폼·타입을 여기서 생성할 것)
GET  /image?path=...      → 원본 이미지 (배경, 브라우저 캐시됨)
POST /detect              → 좌표 JSON (3.9KB)
```

프론트는 **좌표를 받아 원본 이미지 위에 오버레이를 그린다.** 서버가 그려준
이미지를 받지 않는다 — 그러면 확대해도 마커가 뭉개지고 응답이 67배 커진다.

**하지 말 것 세 가지:**

1. `return_image: true` — 260KB base64. 좌표는 3.9KB다.
2. 감도 매핑식을 JS에 복제 — 이번 개발 중 **세 번 어긋났다** (§3).
3. `image_path` 를 운용 경로로 사용 — 서버와 파일시스템을 공유할 때만 동작한다 (§4).

---

## 1. 왜 좌표만 받는가

한 번 측정한 값이다 (sample/ 4000px급 이미지, 콜로니 약 300개):

| 방식 | 응답 크기 | 확대 | 재검출 비용 |
|---|---|---|---|
| `return_image: true` | 260 KB | 픽셀 뭉개짐 | 매번 260KB |
| **좌표 + `GET /image`** | **3.9 KB** | **벡터, 무한** | **3.9KB** (이미지는 캐시) |

67배 차이. 그리고 감도를 조절해 재검출할 때마다 이 차이가 반복된다.

`return_image` 는 좌표를 렌더링할 수 없는 클라이언트(예: 노트북, 슬랙 봇)를 위해
남겨둔 것이지 웹 UI용이 아니다.

---

## 2. 기본 흐름

```tsx
// 1) 배경 — <img> 로 그냥 띄운다. 브라우저가 캐시한다.
const imgUrl = `${API}/image?path=${encodeURIComponent(relPath)}`

// 2) 검출 — 좌표만 온다
const res = await fetch(`${API}/detect`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ image_path: relPath, sensitivity: 50 }),
})
const { width, height, count, colonies, applied_params } = await res.json()
```

응답:

```jsonc
{
  "width": 4032, "height": 3024, "count": 287,
  "colonies": [
    { "id": 1, "x": 320.5, "y": 210.0, "radius": 12.3,
      "circularity": 0.91, "score": 0.83, "pickable": true }
  ],
  "applied_params": { "min_t": 20.0, "candidate_source": "union", ... }
}
```

**좌표는 항상 원본 픽셀 기준이다** — `work_size` 로 축소해 처리하더라도 서버가
되돌려준다. 프론트는 표시 크기에만 맞추면 된다.

### 오버레이

```tsx
// 표시 크기 / 원본 크기 = 스케일
<svg viewBox={`0 0 ${width} ${height}`} style={{ position:'absolute', inset:0 }}>
  {colonies.map(c => (
    <rect key={c.id}
      x={c.x - c.radius} y={c.y - c.radius}
      width={c.radius * 2} height={c.radius * 2}
      fill="none" stroke={c.pickable ? '#22c55e' : '#ef4444'}
      strokeWidth={2} vectorEffect="non-scaling-stroke" />
  ))}
</svg>
```

`viewBox` 를 원본 크기로 두면 **좌표 변환이 필요 없다.** 확대·축소는 컨테이너
CSS가 처리하고, `vector-effect="non-scaling-stroke"` 가 선 두께를 유지한다.

**마커는 사각형을 쓴다.** 콜로니가 원형이라 원을 그리면 윤곽선과 겹쳐 구분이
어렵다 — 직선 테두리가 한천 텍스처 위에서 훨씬 잘 보인다 (목업에서 확인된 사항).

**성능**: 샘플 최대 298개, SVG로 충분하다. 다만 렌더러를 컴포넌트 하나로 격리해
두면 나중에 Canvas로 바꿀 때 그 파일만 고치면 된다.

---

## 3. 파라미터는 서버에서 받아올 것

**이번 개발 중 UI 표시와 서버 실제값이 세 번 어긋났다.** 원인은 항상 같다 —
JS가 매핑식을 복제해뒀고, 서버 쪽만 고쳤다.

```js
// operator-ui.html — app/param_mapping.py 를 손으로 베낀 것. 하지 말 것.
function sensitivityToMinT(v) {
  if (v <= 50) return 90.0 - (v / 50) * 70.0
  return 20.0 - ((v - 50) / 50) * 8.0
}
```

마지막 사고: 감도 50에서 **UI는 25.0, 서버는 20.0** 을 썼다. 오퍼레이터가 보는
숫자가 틀렸다는 뜻이다.

### 대신 이렇게

**보낼 때는 추상값만:**

```jsonc
{ "image_path": "...", "sensitivity": 50 }   // min_t 를 계산하지 않는다
```

**표시할 때는 응답의 `applied_params`:**

```tsx
// 서버가 실제로 쓴 값. 정의상 어긋날 수 없다.
<span>감도 {sensitivity} → t={applied_params.min_t}</span>
```

**폼 자체는 OpenAPI 스펙에서 생성:**

스펙은 [docs/openapi.json](openapi.json) 에 체크인돼 있다 (서버의
`/openapi.json` 과 같은 내용이고, 서버를 띄우지 않아도 쓸 수 있다).

```
components.schemas.DetectRequest.properties.min_solidity
  → { type: 'number', minimum: 0, maximum: 1, default: 0.75,
      description: '면적 ÷ convex hull 면적 하한. 오목한 얼룩·긁힘을 배제한다...' }
components.schemas.DetectRequest.properties.candidate_source
  → { enum: ['union','log','threshold'], default: 'union',
      description: 'union = LoG ∪ 다중레벨 이진화(기본, 재현율 우선)...' }
```

범위·기본값·enum·설명이 전부 들어 있다. 33개 필드 모두 설명이 붙어 있으므로
**폼 라벨과 툴팁을 여기서 그대로 뽑아 쓰면 된다.**

```bash
npx openapi-typescript vision/docs/openapi.json -o src/api/schema.d.ts
```

설명이 JSDoc 으로 들어가 에디터 툴팁에 그대로 뜬다:

```ts
/** @description 감도 (오퍼레이터용 0~100). 높을수록 흐린 콜로니까지 잡는다.
 *  실측: 43 → 89.0%/70.9%, 46 → 86.7%/73.3%, 50 → 82.2%/75.7%(기본) ... */
sensitivity?: number | null;
```

서버가 필드를 바꾸면 **빌드가 깨져서** 알려준다.

> **스펙 파일은 손으로 고치지 말 것.** 코드에서 생성한다:
> ```bash
> .venv/Scripts/python scripts/export_openapi.py
> ```
> 파일이 코드와 어긋나면 `pytest` 가 실패한다
> ([tests/test_openapi_spec.py](../tests/test_openapi_spec.py)) — 이 프로젝트가
> 같은 종류의 드리프트를 네 번 겪어서 넣은 장치다.

---

## 4. 운용 전에 반드시 바꿔야 하는 것

지금 API는 **같은 PC에서 개발할 때를 전제로** 만들어져 있다.

### 4.1 `image_path` 는 운용에서 못 쓴다

서버와 클라이언트가 파일시스템을 공유해야 동작한다. 실제 운용에선 카메라로
찍은 이미지를 올려야 하고, 현재 남은 방법은 base64(`image` 필드)뿐이다.

그런데 그러면 이렇게 된다:

```
원본 4000px JPEG 1.6MB  →  base64 2.2MB
감도를 5번 조정 = 11MB 업로드 (같은 이미지를)
```

**감도 조정은 이 워크플로의 핵심 동작이다.** 정밀도가 82%라 오퍼레이터는
결과를 보고 반드시 조절한다. 그때마다 2.2MB를 다시 올리면 응답이 3.9KB인
의미가 사라진다.

### 4.2 그래서: 업로드 한 번, 검출 여러 번

```
POST /images            이미지 업로드 → { id, width, height }
GET  /images/{id}       배경 표시 (캐시됨)
POST /detect            { image_id, sensitivity } → 좌표만
                        ↑ 감도를 바꿔도 이미지는 다시 안 올라감
```

`DetectRequest` 에 `image_id` 를 추가하고 서버에 TTL 임시 저장소를 두면 된다.
**이게 운용 전 유일한 구조 변경이고**, 나머지는 지금 API를 그대로 쓴다.

### 4.3 보안

| 항목 | 지금 | 필요 |
|---|---|---|
| CORS | `allow_origins=["*"]` ([main.py:9](../main.py#L9)) | React 오리진만 |
| `GET /image` | 서버 실행 디렉터리 전체(이미지 확장자) | 업로드 저장소로 제한 |
| `image_path` | 경로 제약 없음 | 운용에선 차단 또는 개발 전용 플래그 |

`GET /image` 는 이미 디렉터리 탈출과 비이미지 확장자를 막고 있지만
([api.py:51-63](../app/api.py#L51-L63)), 여전히 서버 루트 아래 아무 이미지나
읽힌다. 외부 노출 전에 화이트리스트로 좁힐 것.

---

## 5. 승인 단계 — React를 만들 실질적 이유

현재 성적은 **재현율 75.7% / 정밀도 82.2%** 다. 뜻은:

- 검출 **5~6개 중 1개가 빈 한천** (오검출)
- 실제 콜로니 **4개 중 1개를 놓침**

**지금 목업은 이걸 고칠 방법이 없다.** 검출 결과가 그대로 로봇에 간다.

| 기능 | 왜 필요한가 |
|---|---|
| 마커 클릭 → 제외 | 오검출 18%를 사람이 뺀다 |
| 빈 곳 클릭 → 추가 | 놓친 24%를 사람이 넣는다 |
| 확대·이동 | 4000px에서 작은 콜로니를 눈으로 확인 |
| 최종 목록 → 로봇 | 검출 결과가 아니라 **승인된 목록**을 보낸다 |

로봇에 보내는 것은 `colonies` 가 아니라 오퍼레이터가 승인한 배열이어야 한다.
표시만 예쁘게 하는 거라면 목업으로 충분하다 — 승인 단계가 React를 만들 이유다.

```tsx
// 검출 결과는 읽기 전용 원본, 편집은 별도 상태로
const [detected, setDetected] = useState<Colony[]>([])
const [excluded, setExcluded] = useState<Set<number>>(new Set())
const [added, setAdded] = useState<Point[]>([])

const approved = [
  ...detected.filter(c => c.pickable && !excluded.has(c.id)),
  ...added,
]
```

재검출하면 `detected` 만 갈아끼우고 `excluded`/`added` 는 버린다 — id가 달라지기
때문이다. 감도를 바꾸면 편집 내용이 사라진다는 걸 UI에서 알려줘야 한다.

---

## 6. 파라미터 노출 수준

전체 목록과 실측 근거는
[detection_parameters.md § 선별 기준 네 축](detection_parameters.md#선별-기준-네-축)
— 파라미터를 **크기·모양·색상·분리** 네 축으로 묶고 **오퍼레이터**(항상 보임) ·
**접시별**(펼쳐서 조절) · **전문가**(UI 에 노출 안 함) 세 등급을 붙인 표가 정본이다.
아래는 그 UI 관점 요약이고, 실제 화면 구성은 §10, 동작하는 참고 구현은
[operator-ui-4axis.html](mockup/operator-ui-4axis.html)이다.

**항상 보이게 (오퍼레이터 노브)**

| 필드 | 컨트롤 | 비고 |
|---|---|---|
| `sensitivity` 0~100 | 슬라이더 | 유일하게 자주 쓰는 노브 |
| `plate_type` | 선택 | `petri` / `well8` |

**접시별 (펼쳐서 조절, 평소 건드릴 필요 없음)** — 크기 `min_diam_frac` ·
`max_diam_frac`, 모양 `min_roundness` · `min_solidity`, 색상 `min_rel_sat`,
분리 `split_area_ratio` · `watershed_split` · `exclude_nested`

기본값이 이미 sample/ 라벨 39장 실측 최적이다. **`min_roundness` 완화는 권하지 않는다** —
같은 정밀도(82.8%)라면 감도를 내리는 쪽이 더 많이 맞힌다 (74.7% 대 72.5%).

**전문가 (UI 에 노출 안 함)** — `polarity`(자동 판정 39/39 정확하지만 틀리면
검출이 붕괴한다 — 실측 `971.jpg` 98개→3개. 오퍼레이터가 원인을 되짚을 방법이
없어 노출하지 않고, 마진이 애매하면 자동으로 양극성 검출로 되돌아가 스스로
보호된다. `"both"` 는 개발자·지원용 되돌림 경로로 API 에는 남긴다),
`min_circularity`(기본 0, 기각), `min_fill`(계수
전용), `colour_credit`(현재 설정에서 전 그룹 손해 —
[detection_parameters.md § 2](detection_parameters.md#2-알고리즘-파라미터--고급-접힘)
참고), `work_size`,
`candidate_source`, `threshold_levels`, `adaptive_scale`, raw `min_t`. 서로
의존하는 축이라 오퍼레이터가 단독으로 바꾸면 캘리브레이션이 무효가 된다
([detection_parameters.md §0](detection_parameters.md#0-핵심-요약)).

**노출하지 말 것 (개발·디버깅용)** — `save_annotated`, `image_path`, `return_image`,
`annotated_image*`, `image_format`, `image_quality`, `marker`.

### 프리셋은 두지 않는다

4축 화면(§10 규칙 5)에서는 프리셋을 두지 않는다 — 축이 넷이면 프리셋과 축
조작이 중복이라서다. 기준선은 "균형 · 서버 기본값" 한 줄로 고정 표시한다.

아래는 단일 감도 슬라이더만 있던 구형 목업([operator-ui.html](mockup/operator-ui.html))의
참고용 값이다 (감도 값은 실측점에서 역산한 것). 4축 화면에는 적용하지 말 것:

| 프리셋 | `sensitivity` | 결과 |
|---|---|---|
| 기본 | 50 | 재현율 75.7% / 정밀도 82.2% |
| 덜 찾더라도 정확하게 | 43 | 재현율 70.9% / 정밀도 89.0% |
| 놓치지 않게 많이 찾기 | 81 | 재현율 77.3% / 정밀도 73.5% |

---

## 7. 에러 처리

| 상태 | 원인 | UI |
|---|---|---|
| 400 | 이미지 디코딩 실패, `image`·`image_path` 둘 다 없음 | 메시지 표시 |
| 403 | `/image` 경로가 서버 루트 밖 / 이미지 아님 | 설정 오류 |
| 404 | `/image` 파일 없음 | 경로 확인 |
| 422 | 파라미터 범위 위반 (Pydantic) | **폼에서 미리 막을 것** ← §3 |

검출은 4000px 이미지에서 **2초 정도** 걸린다. `AbortController` 로 취소 가능하게
하고, 감도 슬라이더는 디바운스할 것 — 안 그러면 드래그 한 번에 요청이 수십 개
날아간다.

```tsx
const ctrl = useRef<AbortController>()
async function detect(params) {
  ctrl.current?.abort()               // 이전 요청 취소
  ctrl.current = new AbortController()
  return fetch(url, { signal: ctrl.current.signal, ... })
}
```

---

## 8. 중첩 검출 — `parent_id`

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

## 9. 색 축이 적용됐는지 — `has_chroma`

`applied_params.has_chroma` 가 `false` 면 서버가 색 축을 끈 것이다
(흑백 카메라·합성 이미지 등 채도가 없는 입력). 그때 `min_rel_sat` 과
`colour_credit` 은 무동작이므로, **색상 그룹을 잠그고 이유를 표시해야 한다.**
그러지 않으면 사용자가 슬라이더를 움직여도 결과가 안 바뀌는 이유를 알 수 없다.

```tsx
<fieldset disabled={!applied.has_chroma}>
  {!applied.has_chroma && (
    <p>이 이미지는 채도가 없어 색 기준이 적용되지 않습니다.</p>
  )}
  {/* min_rel_sat 컨트롤 — polarity 는 오퍼레이터 UI 에 노출하지 않는다 */}
</fieldset>
```

## 10. 조절 화면 구성

네 축을 접이식 그룹으로 두고, 각 그룹이 접힌 상태에서도 현재 값 요약을
보여준다. 다섯 가지 규칙을 지킬 것. 동작하는 참고 구현은
[operator-ui-4axis.html](mockup/operator-ui-4axis.html)이고, 그 "개발자 노트"에
컨트롤 ↔ `POST /detect` 필드 매핑이 표로 정리돼 있다.

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

## 11. 관련 문서

- [README](../README.md) — 서버 실행, 엔드포인트 전체
- [detection_parameters.md](detection_parameters.md) — 파라미터별 실측 근거
- [detection-improvement-2026-07-28.md](detection-improvement-2026-07-28.md) — 알고리즘과 성능 이력
- [operator-ui.html](mockup/operator-ui.html) — 실제 API와 통신하는 목업 (참고 구현)
- [operator-ui-4axis.html](mockup/operator-ui-4axis.html) — 4축 화면 정적 목업 + 개발자 노트
