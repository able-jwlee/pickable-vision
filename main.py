from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import router

# 스펙 버전. **엔드포인트나 요청/응답 필드를 바꾸면 올릴 것** —
# 프론트엔드가 docs/openapi.json 을 코드 생성에 쓰므로 버전이 계약의 눈금이다.
#
# 1.1.0 (2026-08-26) 파라미터 전수 점검:
#   - pick_top_n 에 하한 1 추가 (0·음수가 조용히 오동작하던 것을 422 로)
#   - applied_params 에 mask_walls · plate_size_ref 추가
#   - score 계산의 고립도 기준을 원본 픽셀 상수 → 자기 반지름 배수로
#     (값이 달라진다. 필드 구조는 그대로)
#   - marker 가 /detect/preview·save_annotated 에도 적용
#   - Colony.score·pickable 설명을 실제 동작에 맞게 정정
#
# 1.2.0 (2026-08-26) 색으로 검출 돕기:
#   - target_color · color_boost 추가. 오퍼레이터가 화면에서 찍은 색에 가까운
#     콜로니를 **더 잘 찾는다**(검출 후 거르는 게 아니라 검출 자체를 돕는다).
#     기본 꺼짐이라 기존 동작은 그대로다.
#
# 1.3.0 (2026-08-26) 색으로 거르기:
#   - Colony 에 color(내부 중앙 RGB) · color_distance(목표색까지 Lab a*b* 거리).
#     target_color 없이도 color 는 항상 온다 — 프론트가 직접 필터를 만들 수 있다.
#   - max_color_distance 추가(기본 20). **target_color 를 준 요청에만 적용된다.**
#     색을 찍으면 거르기까지 기본 동작이다 — 3초 기다려 재검출했는데 결과가
#     그대로면 오퍼레이터는 고장난 줄 안다. colonies 에서 빼지 않고 pickable 만
#     내리므로 화면이 "왜 빠졌는지" 를 보여줄 수 있다.
#   - color_boost 를 target_color 없이 켜면 422. 조용한 무동작을 없앤다.
API_VERSION = "1.3.0"

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


def _init_console() -> None:
    """Windows 콘솔 출력이 인코딩 때문에 죽지 않게 한다.

    한국어 Windows 의 기본 콘솔 코드페이지는 cp949 이고 거기에는 em dash(—)
    같은 문자가 없다. 그대로 두면 **`--help` 조차** argparse 가 도움말을 찍다가
    UnicodeEncodeError 로 죽는다(실측: exit 1, 스택트레이스 노출).

    콘솔을 UTF-8 로 바꾸고 스트림도 맞춘다. 코드페이지 변경이 실패해도
    errors="replace" 덕분에 글자가 깨질지언정 죽지는 않는다.
    """
    import sys

    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
    except Exception:  # 콘솔이 없는 환경(서비스로 실행 등)에서는 그냥 넘어간다
        pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            pass


def _run() -> None:
    """개발 실행과 PyInstaller exe 의 공통 진입점.

    exe 로 배포하면 포트가 이미 쓰이는 PC 가 있으므로 --port 를 받는다.
    `/image` 가 서빙하는 범위와 `output/` 저장 위치가 **실행 디렉터리 기준**이라
    시작할 때 그 경로를 찍어준다 — exe 를 더블클릭하면 exe 가 있는 폴더가 된다.
    """
    import argparse
    import sys
    from pathlib import Path

    import uvicorn

    _init_console()

    ap = argparse.ArgumentParser(
        prog="pickable-vision",
        description="PICKABLE Vision Server — 콜로니 검출 API",
    )
    ap.add_argument("--host", default="127.0.0.1",
                    help="바인드 주소 (기본 127.0.0.1). 다른 PC 에서 접속하려면 0.0.0.0")
    ap.add_argument("--port", type=int, default=7780, help="포트 (기본 7780)")
    ap.add_argument("--log-level", default="info",
                    choices=["critical", "error", "warning", "info", "debug"])
    ap.add_argument("--version", action="version", version=f"%(prog)s {API_VERSION}")
    args = ap.parse_args()

    frozen = getattr(sys, "frozen", False)
    print(f"PICKABLE Vision Server {API_VERSION}{' (exe)' if frozen else ''}")
    print(f"  http://{args.host}:{args.port}      Swagger: /docs")
    print(f"  작업 디렉터리: {Path.cwd()}")
    print(f"    → GET /image 는 이 아래 이미지만 서빙하고,")
    print(f"      save_annotated 결과도 이 아래 output/ 에 쌓인다.")
    if args.host == "0.0.0.0":  # noqa: S104 — 의도적, 사용자가 명시했을 때만
        print("  경고: 0.0.0.0 은 네트워크에 노출된다. CORS 가 아직 전체 허용이므로")
        print("        신뢰된 망에서만 쓸 것.")

    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)


if __name__ == "__main__":
    # PyInstaller 로 얼린 Windows 실행 파일에서 자식 프로세스가 스크립트를
    # 재실행하며 무한 증식하는 것을 막는다. uvicorn 을 단일 프로세스로 쓰므로
    # 지금은 발동하지 않지만, 워커를 쓰게 되면 없을 때 즉시 문제가 된다.
    import multiprocessing

    multiprocessing.freeze_support()
    _run()
