"""OpenAPI 스펙을 docs/openapi.json 으로 내보낸다.

프론트엔드가 이 파일로 폼을 만들고 타입을 생성한다. 서버를 띄우지 않아도
되도록 app.openapi() 를 직접 호출한다.

    .venv\\Scripts\\python scripts/export_openapi.py
    .venv\\Scripts\\python scripts/export_openapi.py --check   # 갱신 필요 여부만

--check 는 파일을 쓰지 않고 코드와 다르면 exit 1 이다. tests/test_openapi_spec.py
가 같은 비교를 하므로 pytest 만 돌려도 드리프트는 잡힌다.

**왜 파일로 체크인하는가.** /openapi.json 을 서버에서 받아도 되지만, 그러려면
프론트 빌드 때마다 서버가 떠 있어야 한다. 파일로 두면 CI 와 오프라인 작업이
가능하고, 스펙 변경이 diff 로 리뷰에 남는다. 대가는 드리프트인데 그건 위
--check 로 막는다.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app  # noqa: E402

SPEC_PATH = Path(__file__).resolve().parent.parent / "docs" / "openapi.json"


def build_spec() -> dict:
    """현재 코드가 만들어내는 스펙. 파일 비교의 기준이다."""
    # app.openapi() 는 결과를 app.openapi_schema 에 캐시하므로, 같은 프로세스에서
    # 여러 번 부르면 첫 결과가 굳는다. 여기서는 한 번만 부르므로 문제없다.
    return app.openapi()


def serialise(spec: dict) -> str:
    # sort_keys 로 딕셔너리 순회 순서에 따른 무의미한 diff 를 없앤다.
    # ensure_ascii=False 라야 한글 설명이 \uXXXX 로 깨지지 않는다.
    return json.dumps(spec, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="파일을 쓰지 않고 코드와 일치하는지만 확인 (다르면 exit 1)")
    args = ap.parse_args()

    want = serialise(build_spec())

    if args.check:
        if not SPEC_PATH.exists():
            print(f"없음: {SPEC_PATH}", file=sys.stderr)
            print("scripts/export_openapi.py 를 실행해 생성할 것", file=sys.stderr)
            return 1
        if SPEC_PATH.read_text(encoding="utf-8") != want:
            print(f"코드와 다름: {SPEC_PATH}", file=sys.stderr)
            print("scripts/export_openapi.py 를 실행해 갱신할 것", file=sys.stderr)
            return 1
        print(f"최신 상태: {SPEC_PATH}")
        return 0

    SPEC_PATH.parent.mkdir(parents=True, exist_ok=True)
    changed = (not SPEC_PATH.exists()
               or SPEC_PATH.read_text(encoding="utf-8") != want)
    SPEC_PATH.write_text(want, encoding="utf-8")

    spec = build_spec()
    n_fields = len(spec["components"]["schemas"]["DetectRequest"]["properties"])
    print(f"{'갱신' if changed else '변경 없음'}: {SPEC_PATH}")
    print(f"  버전 {spec['info']['version']} · "
          f"엔드포인트 {len(spec['paths'])}개 · DetectRequest 필드 {n_fields}개")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
