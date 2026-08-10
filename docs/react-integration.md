# React 프론트엔드 연동 가이드

> 대상: PICKABLE 오퍼레이터 UI를 React로 만드는 개발자.
> 서버는 `vision/` (FastAPI, 기본 `http://localhost:7780`).
> 현재 동작하는 목업은 [operator-ui.html](mockup/operator-ui.html) — 순수 HTML/JS 단일 파일.

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

범위·기본값·enum·설명이 전부 들어 있다. 31개 필드 모두 설명이 붙어 있으므로
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

전체 목록과 실측 근거는 [detection_parameters.md](detection_parameters.md).
UI 관점 요약:

**항상 보이게 (오퍼레이터가 실제로 조절)**

| 필드 | 컨트롤 | 비고 |
|---|---|---|
| `sensitivity` 0~100 | 슬라이더 | 유일하게 자주 쓰는 노브 |
| `polarity` | 선택 | `auto` 가 39장에서 판정 정확도 100% — 기본값 유지 |
| `plate_type` | 선택 | `petri` / `well8` |

**접어두기 (평소 건드릴 필요 없음)** — `candidate_source`, `min_solidity`,
`min_roundness`, `work_size`, `watershed_split`, `min_fill`

기본값이 이미 sample/ 라벨 39장 실측 최적이다. **`min_roundness` 완화는 권하지 않는다** —
같은 정밀도(82.8%)라면 감도를 내리는 쪽이 더 많이 맞힌다 (74.7% 대 72.5%).

**노출하지 말 것** — `save_annotated`, `image_path`, `return_image`,
`annotated_image*`, `image_format`, `image_quality`, `marker`. 개발·디버깅용이다.

### 프리셋

목업에 있는 것을 그대로 쓰면 된다 (감도 값은 실측점에서 역산한 것):

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

## 8. 관련 문서

- [README](../README.md) — 서버 실행, 엔드포인트 전체
- [detection_parameters.md](detection_parameters.md) — 파라미터별 실측 근거
- [detection-improvement-2026-07-28.md](detection-improvement-2026-07-28.md) — 알고리즘과 성능 이력
- [operator-ui.html](mockup/operator-ui.html) — 동작하는 목업 (참고 구현)
