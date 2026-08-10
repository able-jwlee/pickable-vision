"""체크인된 docs/openapi.json 이 코드와 일치하는지 지킨다.

프론트엔드가 이 파일로 타입을 생성하므로, 파일이 낡으면 UI 가 서버와 다른
계약을 믿게 된다. 이 프로젝트는 같은 종류의 드리프트(UI 표시값이 서버와
어긋남)를 이미 네 번 겪었고, 매번 원인은 "코드를 고쳤는데 복제본을 안 고침"
이었다. 그래서 복제본을 두되 **테스트로 묶는다.**
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = ROOT / "docs" / "openapi.json"


def _load_exporter():
    """scripts/export_openapi.py 를 모듈로 읽는다 (패키지가 아니라서 직접 로드)."""
    path = ROOT / "scripts" / "export_openapi.py"
    spec = importlib.util.spec_from_file_location("export_openapi", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["export_openapi"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def spec() -> dict:
    return json.loads(SPEC_PATH.read_text(encoding="utf-8"))


def test_checked_in_spec_matches_code():
    """docs/openapi.json 이 현재 코드가 만드는 스펙과 같아야 한다."""
    exporter = _load_exporter()
    want = exporter.serialise(exporter.build_spec())
    got = SPEC_PATH.read_text(encoding="utf-8")
    assert got == want, (
        f"{SPEC_PATH.name} 이 코드와 다르다. "
        "`python scripts/export_openapi.py` 로 갱신할 것."
    )


def test_every_request_field_is_documented(spec):
    """설명 없는 요청 필드는 프론트에서 정체를 알 수 없다."""
    props = spec["components"]["schemas"]["DetectRequest"]["properties"]
    undocumented = sorted(k for k, v in props.items() if not v.get("description"))
    assert not undocumented, f"description 없는 필드: {undocumented}"


def test_every_response_field_is_documented(spec):
    for name in ("Colony", "DetectResponse", "PreviewResponse"):
        props = spec["components"]["schemas"][name]["properties"]
        undocumented = sorted(k for k, v in props.items() if not v.get("description"))
        assert not undocumented, f"{name} 에 description 없는 필드: {undocumented}"


def test_every_endpoint_has_summary(spec):
    """Swagger 목록과 코드 생성기의 함수명이 여기서 나온다."""
    missing = [
        f"{method.upper()} {path}"
        for path, ops in spec["paths"].items()
        for method, op in ops.items()
        if not op.get("summary")
    ]
    assert not missing, f"summary 없는 엔드포인트: {missing}"


def test_expected_endpoints_present(spec):
    """계약이 조용히 사라지지 않게 한다."""
    assert set(spec["paths"]) == {"/health", "/image", "/detect", "/detect/preview"}


def test_operator_knobs_have_measured_curve_in_description(spec):
    """감도는 프론트가 라벨을 붙이는 값이라 실측 수치가 스펙에 있어야 한다.

    UI 가 "정밀도 91%" 같은 라벨을 하드코딩했다가 서버 변경으로 어긋난 적이
    있다. 스펙에 수치를 실어두면 최소한 한곳에서는 확인할 수 있다.
    """
    desc = spec["components"]["schemas"]["DetectRequest"]["properties"]["sensitivity"]["description"]
    assert "82.2%" in desc and "75.7%" in desc, (
        "sensitivity 설명의 실측 수치가 현재 기본 성적과 다르다 — "
        "성능이 바뀌면 이 설명도 갱신할 것"
    )


def test_coordinates_documented_as_original_pixels(spec):
    """좌표계는 프론트가 가장 틀리기 쉬운 부분이다."""
    for field in ("x", "y", "radius"):
        desc = spec["components"]["schemas"]["Colony"]["properties"][field]["description"]
        assert "원본" in desc, f"Colony.{field} 설명에 좌표 기준이 없다"
