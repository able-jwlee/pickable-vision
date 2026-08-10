# PyInstaller 스펙 — PICKABLE Vision Server 를 단독 실행 파일로 묶는다.
#
#   .venv\Scripts\python -m PyInstaller vision.spec --noconfirm
#
# 기본은 onedir(폴더 배포)이다. 단일 파일이 필요하면:
#
#   set PICKABLE_ONEFILE=1  &&  .venv\Scripts\python -m PyInstaller vision.spec --noconfirm
#
# onedir 을 기본으로 두는 이유는 시작 속도다. onefile 은 실행할 때마다 100MB 대를
# 임시 폴더에 풀어야 해서 첫 응답까지 수 초가 더 걸리고, 백신이 그 동작을
# 의심하는 일도 잦다. 서버는 한 번 띄워 계속 쓰는 물건이라 폴더 배포가 맞다.

import os

ONEFILE = os.environ.get("PICKABLE_ONEFILE") == "1"

# uvicorn 은 프로토콜·이벤트루프 구현을 문자열로 늦게 import 하므로 정적 분석에
# 잡히지 않는다. 빠지면 exe 가 뜨자마자 ModuleNotFoundError 로 죽는다.
HIDDEN = [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
]

# 이 venv 에는 Cellpose 실험 때 깔린 torch·torchvision 등이 남아 있다(수 GB).
# 앱은 cv2/numpy/fastapi/pydantic/uvicorn 만 쓰므로 분석에 잡힐 이유가 없지만,
# 전이 의존으로 딸려 들어가면 산출물이 조용히 거대해진다. 명시적으로 끊는다.
EXCLUDE = [
    "torch", "torchvision", "cellpose", "segment_anything",
    "scipy", "sympy", "networkx", "numba", "llvmlite",
    "matplotlib", "pandas", "IPython", "notebook",
    "PIL", "tifffile", "imagecodecs", "roifile", "fastremap", "fill_voids",
    "tkinter", "PyQt5", "PySide2", "wx",
    "pytest", "_pytest", "setuptools", "pip",
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    # 검출은 순수 코드라 동봉할 모델·가중치 파일이 없다. config.py 의 상수가
    # 곧 파라미터이므로 datas 가 비어 있는 것이 정상이다.
    datas=[],
    hiddenimports=HIDDEN,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDE,
    noarchive=False,
    optimize=0,
)
# OpenCV 의 ffmpeg DLL 은 26MB(산출물의 16%)인데 **영상 입출력 전용**이다.
# 이 서버는 정지 이미지만 디코딩하므로 VideoCapture/VideoWriter 를 쓰지 않는다.
# 빼고 빌드해 검출을 돌려 결과가 동일한지 확인했다(14581.jpg 115개 그대로).
# 나중에 영상 프레임을 받게 되면 이 줄을 지워야 한다.
a.binaries = [b for b in a.binaries if "opencv_videoio_ffmpeg" not in b[0]]

pyz = PYZ(a.pure)

if ONEFILE:
    exe = EXE(
        pyz, a.scripts, a.binaries, a.datas, [],
        name="pickable-vision",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,          # OpenCV DLL 이 UPX 압축에서 깨진 사례가 있어 끈다
        runtime_tmpdir=None,
        console=True,       # 서버 로그를 봐야 하므로 콘솔 유지
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
else:
    exe = EXE(
        pyz, a.scripts, [],
        exclude_binaries=True,
        name="pickable-vision",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=True,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
    coll = COLLECT(
        exe, a.binaries, a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name="pickable-vision",
    )
