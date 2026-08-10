from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import router

# 스펙 버전. **엔드포인트나 요청/응답 필드를 바꾸면 올릴 것** —
# 프론트엔드가 docs/openapi.json 을 코드 생성에 쓰므로 버전이 계약의 눈금이다.
API_VERSION = "1.0.0"

DESCRIPTION = """\
배양 플레이트 이미지에서 콜로니를 검출해 **원본 픽셀 좌표**를 반환한다.

### 프론트엔드가 쓰는 두 엔드포인트

| | |
|---|---|
| `GET /image?path=` | 배경으로 깔 원본 이미지 (브라우저가 캐시한다) |
| `POST /detect` | 좌표 JSON — 4000px 이미지에서 약 3.9KB |

좌표는 **처리 해상도와 무관하게 항상 원본 픽셀 기준**이므로
`<svg viewBox="0 0 {width} {height}">` 에 그대로 얹으면 좌표 변환이 필요 없다.

`return_image: true` 로 서버가 그린 이미지를 받을 수도 있지만 응답이 260KB 로
67배 커지고 확대하면 마커가 뭉개진다 — 웹 UI 에서는 쓰지 말 것.

### 감도

오퍼레이터가 실제로 조절하는 값은 `sensitivity`(0~100) 하나다. 나머지 기본값은
`sample/` 라벨 39장(정답 1,886개) 실측 최적이다.

| sensitivity | min_t | 정밀도 | 재현율 |
|---|---|---|---|
| 43 | 30 | 89.0% | 70.9% |
| 46 | 25 | 86.7% | 73.3% |
| **50 (기본)** | **20** | **82.2%** | **75.7%** |
| 81 | 15 | 73.5% | 77.3% |

**매핑식을 클라이언트에 복제하지 말 것.** 실제 적용된 값이 응답의
`applied_params` 로 되돌아온다 — 복제 때문에 UI 표시가 서버와 어긋난 적이 네 번 있다.

### 알아둘 것

- 정밀도 82% · 재현율 76% 다. **검출 5~6개 중 1개는 빈 한천**이고 **4개 중 1개는
  놓친다.** 로봇에 보내기 전 사람이 확인하는 단계를 두는 것을 전제로 한 값이다.
- `image_path` 는 서버와 파일시스템을 공유할 때만 동작하는 **개발용**이다.
  운영에서는 `image`(base64)를 쓴다.
- 검출은 4000px 이미지에서 약 2초 걸린다. 감도 슬라이더는 디바운스할 것.
"""

app = FastAPI(
    title="PICKABLE Vision Server",
    version=API_VERSION,
    description=DESCRIPTION,
    openapi_tags=[
        {"name": "detect", "description": "콜로니 검출."},
        {"name": "image", "description": "이미지 제공."},
        {"name": "ops", "description": "운영·헬스체크."},
    ],
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=7780)
