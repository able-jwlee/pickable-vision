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

## 엔드포인트

| Method | Path | 용도 |
|---|---|---|
| GET | `/health` | 헬스체크 |
| POST | `/detect` | 이미지(base64) → 콜로니 픽셀 좌표 리스트 |
| POST | `/detect/preview` | 검출 원을 붉게 그린 이미지 반환 (파라미터 튜닝용) |

### `POST /detect` 요청/응답

```jsonc
// 요청 — 이미지 입력은 image(base64) 또는 image_path(로컬 경로) 중 하나 필수
{
  "image": "base64 (data:image/...;base64, 접두사 허용)",  // 운영(UI)용
  "image_path": "../PICKABLE-Neon/temp/camera/.../x.jpg",  // 로컬 튜닝 편의용
  "min_area": 8,           // px² 하한
  "max_area": 5000,        // px² 상한
  "min_circularity": 0.45, // 원형도 하한 (4πA/P²)
  "invert": true,          // 콜로니가 배경보다 어두우면 true (기본 true)
  "tophat_kernel": 31,     // top-hat 구조요소 크기(px, >=3). 콜로니보다 크게
  "threshold_offset": 0,   // 민감도. Otsu 임계값에서 뺌. >0 더 민감, <0 더 엄격
  "mask_walls": true,      // 8웰(4×2 덱) 격자 내부로만 검출 제한 → 벽/프레임/웰밖 제외
  "split_touching": true,  // 붙은 콜로니를 watershed로 분리 (기본 ON, 밀집 재현율↑)
  "pick_top_n": null,      // 정수면 피킹 후보 중 점수 상위 N개만 후보로 (예: 96핀 → 96)
  "save_annotated": false  // true면 콜로니 표시 이미지를 vision/output/ 에 저장
}
// 응답 — 각 콜로니에 피킹 적합도(score)와 후보 여부(pickable) 포함
{
  "width": 1350, "height": 910, "count": 438,
  "colonies": [ { "id": 1, "x": 320.5, "y": 210.0, "radius": 12.3, "score": 0.83, "pickable": true }, ... ],
  "annotated_path": "C:/.../vision/output/agar_plate_260706-190246.jpg"  // save_annotated=true일 때
}
```

### 오퍼레이터용 0~100 스케일 필드 (선택)

CV 원본 파라미터 대신 오퍼레이터가 이해하기 쉬운 0~100 슬라이더 값으로도 요청 가능하다. 지정된 필드는 대응하는 raw 필드보다 우선한다.

| 추상 필드 (0~100) | 덮어쓰는 raw 필드 | 기본값 → raw |
|---|---|---|
| `sensitivity` | `threshold_offset` | 50 → +7 |
| `min_size` | `min_area` | 20 → ≈6 |
| `max_size` | `max_area` | 75 → ≈5027 |
| `edge_margin` | 벽 여백(px) | 40 → 60 |

응답에는 실제 적용된 raw 값이 `applied_params`에 담겨 되반환된다.

예:
```jsonc
{ "image_path": "...", "sensitivity": 65, "min_size": 30, "edge_margin": 50 }
```

UI 목업(`docs/mockup/operator-ui.html`)에서 이 필드들을 실제로 어떻게 슬라이더로 노출하는지 볼 수 있다.

**이미지 입력 두 방식**
- `image` (base64): **운영 계약**. UI가 Neon `/api/v1/driver/camera/capture` 응답의 base64를 그대로 전달. 브라우저 흐름에서 유일하게 가능한 방식.
- `image_path` (로컬 경로): **튜닝 편의용**. 서버와 파일시스템을 공유할 때만 동작(같은 PC). `/docs`에서 base64 붙여넣기 없이 Neon 저장 이미지를 바로 검출. 둘 다 오면 `image_path` 우선.

## 피킹 대상 선별 (pickable)

검출된 콜로니마다 **피킹 적합도 점수**(`score` 0~1)와 **후보 여부**(`pickable`)를 매긴다.
목적은 "로봇이 안전하게 집을 수 있는" 콜로니를 미리 골라주는 것(human-in-the-loop).

- **고립도**(가까운 이웃까지 거리): 이웃과 충분히 떨어져야 이웃을 안 건드리고 집을 수 있음
- **크기**: 너무 작으면(speck) / 너무 크면(병합 추정) 제외
- `pickable = 이웃과 PICK_MIN_SEPARATION 이상 && 반지름이 대역 안` (기준은 `app/config.py`)
- `pick_top_n`을 주면 후보 중 점수 상위 N개만 남긴다 (96핀 헤드 → `pick_top_n: 96`)

`save_annotated` 이미지에서 **피킹 후보는 초록 굵은 원**, 나머지 검출은 **얇은 빨강 원**으로 표시된다.
밀집 클럼프 안의 콜로니는 (집기 위험하므로) 후보에서 빠지고, 흩어진 콜로니가 후보가 된다.

## 검출 결과 이미지로 확인하기

`save_annotated: true`를 넣으면 콜로니를 붉은 원으로 표시한 이미지를 `vision/output/` 에 저장하고,
응답의 `annotated_path`로 저장 경로를 알려준다. 로컬에서 검출 품질을 눈으로 확인·튜닝하는 용도.

```bash
# 경로 입력 + 결과 이미지 저장
curl -X POST http://localhost:7780/detect \
  -H 'Content-Type: application/json' \
  -d '{ "image_path": "../PICKABLE-Neon/temp/camera/260706/260706-160546.jpg", "save_annotated": true }'
# → vision/output/260706-160546_<타임스탬프>.jpg 생성

# 또는 헬퍼로 (파일 → base64 → /detect, 결과 이미지 저장까지)
.venv/Scripts/python tools/detect_file.py ../PICKABLE-Neon/resources/dummy/agar_plate.bmp --save
```

`tools/detect_file.py`는 UI 없이 base64 `image` 필드를 시험하는 헬퍼다. `--save`는 서버가
`output/`에 저장, `--preview --out x.png`는 반환 이미지를 로컬 파일로 저장한다.

## 검출 파이프라인 (`app/detector.py`)

그레이스케일 → 가우시안 블러 → **top-hat**(조명 평탄화·콜로니 강조) → **Otsu** →
(**plate ROI 제한**) → 모폴로지 열림 → findContours → 넓이·원형도 필터 → minEnclosingCircle.

- **top-hat**(black/white)이 국소 배경을 제거해 조명 불균일·그림자에 강하고, 밝은 격자 벽은
  자연히 억제된다. adaptive threshold보다 흐린 콜로니 재현율이 높다.
- **8웰 격자 제한**(`mask_walls=true`): plate를 규칙 4×2 격자로 나눠 각 웰 내부만 남기고
  격자 벽·바깥 프레임을 제외한다(웰 밖 검출 방지). 여백은 `WELL_MARGIN`(config).
  격자는 규칙적 배치를 가정하며, 근본적으로 정확한 웰 경계는 향후 덱 좌표 캘리브레이션으로 대체 가능.
- **붙은 콜로니 분리(watershed)**: 거리변환 국소 최대를 씨앗으로 watershed하여 뭉친 클러스터를
  개별로 나눈다. **기본 ON** — 밀집 구간 재현율↑(dummy 전체 661→1014, 밀집 well2 130→191).
  가장자리 오검출이 조금 늘 수 있어, 깨끗한 기본 동작이 필요하면 `split_touching:false`로 끈다.
- 기본 파라미터는 `app/config.py` (재현율 우선 튜닝). dummy `agar_plate.bmp`에서
  431 → 661개로 재현율이 크게 향상됨.

### 민감도(`threshold_offset`)와 한계

`threshold_offset`은 Otsu 임계값을 조절하는 민감도 knob이다(>0 더 민감, <0 더 엄격).
단, **기본값 0(순수 Otsu)이 대체로 재현율 최댓값**이다 — 올리면 흐린 blob들이 뭉쳐
개수가 오히려 줄고, 내리면 흐린 것을 놓친다. 조명 불균일 구간(그림자/haze)의 저대비
콜로니는 대비가 노이즈 수준이라 **어떤 파라미터로도 좋은 영역을 오염시키지 않고는
살릴 수 없다.** 이 구간의 재현율은 알고리즘이 아니라 촬영 조명 균일화로 올려야 한다.
지역 이진화(adaptive)도 시도했으나 밀집 열에서 콜로니를 놓쳐(국소 평균이 콜로니에
지배됨) 전역 Otsu보다 나빴다.

## 테스트

```bash
.venv/Scripts/python -m pip install -r requirements-test.txt
.venv/Scripts/python -m pytest -v
```

## 범위 밖 (향후 단계)

픽셀→mm 좌표 변환(캘리브레이션), UI 오버레이·선택/해제, PocketBase 레시피/이력 연동,
PyInstaller 패키징. (watershed 붙은 콜로니 분리·피킹 대상 선별은 구현됨)
