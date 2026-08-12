# PICKABLE Vision Server

배양 플레이트 이미지에서 콜로니를 검출해 **픽셀 좌표**를 반환하는 독립 FastAPI + OpenCV 서버.

이미지는 PICKABLE-Neon(로봇 제어)이 캡처·왜곡보정한 것을 받는다. 이 서버는 검출만 담당하며,
픽셀→mm 변환·UI 오버레이·PocketBase 연동은 범위 밖(향후 단계)이다.

## 실행

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python main.py     # http://localhost:7780  (Swagger UI: /docs)
```

## 현재 성적

`sample/` 라벨 보유 39장(정답 1,886개) 기준. 측정 방법은 [§재현](#재현) 참조.

| 지표 | 값 |
|---|---|
| 재현율 | **75.7%** |
| 정밀도 | **82.2%** |
| F1 | 78.8 |
| 속도 | 약 2초/장 (4000px급, CPU) |

그룹별 재현율: lower-res 87% · dark 85% · bright 75% · vague 55%.
개선 이력과 기각한 시도들은 [docs/detection-improvement-2026-07-28.md](docs/detection-improvement-2026-07-28.md).

## 엔드포인트

| Method | Path | 용도 |
|---|---|---|
| GET | `/health` | 헬스체크 |
| GET | `/image?path=` | 원본 이미지 바이트 (UI 배경 표시용) |
| POST | `/detect` | 이미지 → 콜로니 픽셀 좌표 리스트 |
| POST | `/detect/preview` | 검출 원을 그린 이미지만 반환 (좌표 없음) |

**UI는 `GET /image` + `POST /detect` 두 개를 쓴다.** 원본은 브라우저가 캐시하고
검출 응답은 좌표만 담아 3.9KB다 (이미지를 함께 담으면 260KB). 프론트엔드 연동은
[docs/react-integration.md](docs/react-integration.md).

### `POST /detect` 요청/응답

```jsonc
// 요청 — 이미지 입력은 image(base64) 또는 image_path(로컬 경로) 중 하나 필수
{
  "image": "base64 (data:image/...;base64, 접두사 허용)",  // 운영 계약
  "image_path": "sample/971.jpg",                          // 로컬 튜닝 편의용

  "sensitivity": 50,        // 0~100 감도 (오퍼레이터용). min_t 로 매핑됨
  "polarity": "auto",       // auto | both | bright | dark
  "plate_type": "petri",    // petri | well8

  "pick_top_n": null,       // 정수면 피킹 후보 중 점수 상위 N개만 (96핀 → 96)
  "save_annotated": false   // true면 표시 이미지를 vision/output/ 에 저장
}
// 응답 — 좌표는 항상 원본 픽셀 기준 (처리 해상도와 무관)
{
  "width": 4032, "height": 3024, "count": 287,
  "colonies": [
    { "id": 1, "x": 320.5, "y": 210.0, "radius": 12.3,
      "circularity": 0.91, "score": 0.83, "pickable": true }
  ],
  "applied_params": { "min_t": 20.0, "candidate_source": "union", ... }
}
```

전체 파라미터(33개)는 **[docs/openapi.json](docs/openapi.json)** 이 정본이다 —
범위·기본값·enum·설명이 전부 들어 있고, 서버의 `/openapi.json`·`/docs`(Swagger)와
같은 내용이다. 필드별 실측 근거는
[docs/detection_parameters.md](docs/detection_parameters.md)에 있다.

```bash
# 스펙 갱신 (코드를 바꾼 뒤)
.venv/Scripts/python scripts/export_openapi.py

# 프론트엔드 타입 생성
npx openapi-typescript vision/docs/openapi.json -o src/api/schema.d.ts
```

`docs/openapi.json` 은 **손으로 고치지 말 것** — 코드에서 생성하며, 어긋나면
`pytest` 가 실패한다.

### 오퍼레이터용 0~100 스케일 필드

CV 원본 파라미터 대신 0~100 값으로도 요청할 수 있다. 지정하면 대응 raw 필드보다 우선한다.

| 추상 필드 | 덮어쓰는 raw 필드 | 매핑 |
|---|---|---|
| `sensitivity` | `min_t` | 0→90, 50→20, 100→12 |
| `edge_margin` | 피킹 안전 여백(px) | `app/param_mapping.py` |

**클라이언트는 이 매핑을 복제하지 말 것.** 실제 적용된 raw 값이 응답
`applied_params` 에 되반환되므로 그걸 표시하면 된다 (개발 중 UI 표시가 서버와
세 번 어긋났고, 원인은 매번 JS쪽 복제였다).

**이미지 입력 두 방식**
- `image` (base64): **운영 계약**. 브라우저 흐름에서 유일하게 가능한 방식.
- `image_path` (로컬 경로): **튜닝 편의용**. 서버와 파일시스템을 공유할 때만 동작.
  둘 다 오면 `image_path` 우선. 운용 배포 시에는 차단할 것.

## 검출 파이프라인 (`app/blob_detector.py`)

**이진화로 시작하지 않는다.** 전역 임계값 하나로는 밝기가 다른 콜로니를 동시에
잡을 수 없기 때문이다. 대신 후보를 넉넉히 만들고 통계로 거른다.

```
1. 접시 ROI      HoughCircles (petri) 또는 4×2 격자 (well8)
2. 극성 판정      접시별로 콜로니가 배경보다 밝은지/어두운지 자동 결정
3. 후보 생성      LoG 스케일공간 극값  ∪  다중레벨 이진화 연결성분
4. 통계 판정      면적가중 Welch t-통계량 ≥ min_t
5. 모양 게이트    solidity ≥ 0.75, 크기 창
6. 분리          거리변환 watershed 로 붙은 콜로니 나눔
7. NMS           중복 제거
```

### 3단계 — 후보를 왜 합집합으로 만드는가

두 방식이 **서로 다른 것을 본다.** LoG는 흐릿하고 경계가 불분명한 것을 잡고,
이진화는 경계가 뚜렷하지만 크기가 제각각인 것을 잡는다. 합치면 전 구간에서
LoG 단독보다 **+2.9~3.5%p** 위다.

- `candidate_source: "union"` (기본) — 재현율 우선
- `"threshold"` — 정밀도 93% 이상 구간에서는 이쪽이 낫다 (계수/CFU 용도)
- `"log"` — 구동작

### 4단계 — t-통계량

콜로니 후보 안쪽과 바깥 링의 밝기 차이가 **노이즈 대비 얼마나 큰지**를 잰다.
절대 밝기가 아니라 대비의 통계적 유의성이므로 조명이 불균일해도 동작한다.

```
t = (m_in − m_out) / √(s_in²/n_in + s_out²/n_out)
```

중앙값·MAD를 써서 이웃 콜로니가 링에 걸쳐도 흔들리지 않는다. `min_t` 가 감도
노브이고, 낮추면 흐린 콜로니까지 잡히면서 오검출이 는다.

기본값은 전부 sample/ 라벨 39장 실측 최적이며, 각 상수의 곡선과 기각 사유가
[app/config.py](app/config.py) 주석에 기록돼 있다.

## 피킹 대상 선별 (pickable)

검출된 콜로니마다 **피킹 적합도 점수**(`score` 0~1)와 **후보 여부**(`pickable`)를 매긴다.
목적은 "로봇이 안전하게 집을 수 있는" 콜로니를 미리 골라주는 것(human-in-the-loop).

- **고립도**: 이웃과 충분히 떨어져야 이웃을 안 건드리고 집을 수 있음
- **크기**: 너무 작으면(speck) / 너무 크면(병합 추정) 제외
- **경계 여백**: 접시·웰 가장자리에서 안쪽만 인정 (`mask_walls`, `edge_margin`)
- `pick_top_n` 을 주면 후보 중 점수 상위 N개만 남긴다

`save_annotated` 이미지에서 **피킹 후보는 초록**, 나머지 검출은 **빨강**으로 표시된다.

## 검출 결과 이미지로 확인하기

```bash
# 경로 입력 + 결과 이미지 저장
curl -X POST http://localhost:7780/detect \
  -H 'Content-Type: application/json' \
  -d '{ "image_path": "sample/971.jpg", "save_annotated": true }'
# → vision/output/971_<타임스탬프>.jpg 생성

# 샘플 전체를 갤러리 HTML로 (재현율 낮은 순 정렬)
.venv/Scripts/python scripts/annotate_samples.py --gallery
```

## 테스트

```bash
.venv/Scripts/python -m pip install -r requirements-test.txt
.venv/Scripts/python -m pytest -v
```

## exe 빌드 (Python 없는 PC 배포)

```bash
.venv/Scripts/python -m pip install -r requirements-build.txt
.venv/Scripts/python -m PyInstaller vision.spec --noconfirm
# → dist/pickable-vision/  (140MB, 폴더 통째로 복사해 쓴다)
```

```bash
dist/pickable-vision/pickable-vision.exe                  # 127.0.0.1:7780
dist/pickable-vision/pickable-vision.exe --port 8080
dist/pickable-vision/pickable-vision.exe --host 0.0.0.0   # 다른 PC 에서 접속
```

**작업 디렉터리가 곧 서빙 범위다.** `GET /image` 는 exe 를 실행한 디렉터리 아래
이미지만 내주고, `save_annotated` 결과도 그 아래 `output/` 에 쌓인다. 더블클릭하면
exe 가 있는 폴더가 기준이 된다. 서버가 시작할 때 그 경로를 찍어준다.

| | |
|---|---|
| 크기 | 140MB (폴더) · 기동 약 2초 |
| 검출 | **개발 서버와 좌표까지 동일** (샘플 3장 대조 확인) |
| 기본 바인드 | `127.0.0.1` — 외부 노출은 `--host 0.0.0.0` 을 **명시**해야 한다 |
| `/docs` | Swagger UI 는 CDN 에서 JS 를 받으므로 **인터넷이 없으면 안 뜬다.** 스펙 자체(`/openapi.json`)는 오프라인에서도 나온다 |

폴더 배포(onedir)가 기본이다. 단일 파일이 필요하면:

```bash
PICKABLE_ONEFILE=1 .venv/Scripts/python -m PyInstaller vision.spec --noconfirm
```

단일 파일은 실행할 때마다 140MB 를 임시 폴더에 풀어 기동이 느리고 백신 오탐도
잦다. 서버는 한 번 띄워 계속 쓰는 물건이라 폴더 배포를 권한다.

빌드 설정과 제외 목록의 근거는 [vision.spec](vision.spec) 주석에 있다.

## 재현

성적 수치는 `sample/` 이미지와 그 정답 라벨(JSON) 39쌍으로 측정한다. 이미지는 용량 때문에
git에서 제외돼 있다(`.gitignore`).

```bash
# 전체 지표 (디렉터리 재귀 탐색)
.venv/Scripts/python scripts/evaluate_labeled.py sample

# 파라미터를 바꿔가며 비교
.venv/Scripts/python scripts/evaluate_labeled.py sample --param min_t=25
.venv/Scripts/python scripts/evaluate_labeled.py sample --json out.json
```

**한 축을 바꾸면 의존하는 축의 캘리브레이션이 무효가 된다.** 실제로 겪은 쌍들:
`work_size` ↔ `r_min`/`r_max`, 반지름 ↔ NMS, 반지름 ↔ `split_area_ratio`,
`candidate_source` ↔ 모양 게이트. 하나만 바꾸고 측정하면 잘못된 결론이 나온다.

## 범위 밖 (향후 단계)

픽셀→mm 좌표 변환(캘리브레이션), 오퍼레이터 승인 UI, PocketBase 레시피/이력 연동.
(PyInstaller 패키징은 위 [exe 빌드](#exe-빌드-python-없는-pc-배포) 에서 구현됨)
