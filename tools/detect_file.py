"""로컬 이미지 파일을 base64로 인코딩해 /detect(또는 /detect/preview)에 POST하는 테스트 헬퍼.

UI 없이 base64 `image` 경로를 그대로 시험해보는 용도.

사용법 (vision/ 에서, venv 파이썬으로):
    .venv/Scripts/python tools/detect_file.py <이미지경로> [--preview] [--out preview.png] [--url http://localhost:7780]

예시:
    .venv/Scripts/python tools/detect_file.py ../PICKABLE-Neon/resources/dummy/agar_plate.bmp
    .venv/Scripts/python tools/detect_file.py ../PICKABLE-Neon/temp/camera/260706/260706-160546.jpg --preview --out preview.png
"""

import argparse
import base64
import sys
from pathlib import Path
from urllib.request import Request, urlopen
import json


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("image", help="로컬 이미지 파일 경로")
    ap.add_argument("--url", default="http://localhost:7780")
    ap.add_argument("--preview", action="store_true", help="/detect/preview 호출")
    ap.add_argument("--out", default="preview.png", help="preview 로컬 저장 경로")
    ap.add_argument(
        "--save",
        action="store_true",
        help="서버가 콜로니 표시 이미지를 vision/output/ 에 저장",
    )
    args = ap.parse_args()

    path = Path(args.image)
    if not path.is_file():
        print(f"파일 없음: {path}", file=sys.stderr)
        return 1

    b64 = base64.b64encode(path.read_bytes()).decode()
    endpoint = "/detect/preview" if args.preview else "/detect"
    body = json.dumps({"image": b64, "save_annotated": args.save}).encode()

    req = Request(
        args.url + endpoint,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req) as resp:
        result = json.loads(resp.read())

    print("count:", result["count"])
    if args.preview:
        Path(args.out).write_bytes(base64.b64decode(result["image"]))
        print("preview 저장:", args.out)
    else:
        for col in result["colonies"][:5]:
            print(col)
        if result["count"] > 5:
            print(f"... (+{result['count'] - 5} more)")
        if result.get("annotated_path"):
            print("표시 이미지 저장:", result["annotated_path"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
