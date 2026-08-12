"""GET /image — 원본 이미지 서빙과 경로 제약.

좌표만 받아 클라이언트가 오버레이를 그리려면 클라이언트도 원본 이미지를 가져야
한다. 이 엔드포인트가 그 간극을 메우는데, 파일 **내용을 그대로 반환**하므로
`/detect` 의 image_path(읽어서 검출에만 씀)와 노출 성격이 다르다. 제약이 실제로
동작하는지 고정해 둔다.
"""
from pathlib import Path

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

FIXTURE = "tests/fixtures/agar_sample.jpg"


def test_serves_image_bytes():
    r = client.get("/image", params={"path": FIXTURE})
    assert r.status_code == 200
    assert r.content[:2] == b"\xff\xd8"          # JPEG 매직
    assert len(r.content) == Path(FIXTURE).stat().st_size


def test_rejects_path_outside_server_root():
    """상위 디렉터리 탈출은 403.

    `..` 를 문자열로 검사하지 않고 resolve 후 루트 포함 여부를 본다 — 문자열
    검사는 심볼릭 링크나 인코딩 변형으로 우회된다.
    """
    for bad in ("../../../etc/passwd",
                "../../../Windows/System32/drivers/etc/hosts",
                "tests/../../outside.jpg"):
        r = client.get("/image", params={"path": bad})
        assert r.status_code == 403, f"{bad} 가 통과됨"


def test_rejects_non_image_extension():
    """이미지가 아닌 파일은 403 — 설정·소스가 새어 나가면 안 된다."""
    for bad in ("app/config.py", "main.py", ".gitignore"):
        r = client.get("/image", params={"path": bad})
        assert r.status_code == 403, f"{bad} 가 통과됨"


def test_missing_file_is_404_not_403():
    """없는 파일과 금지된 파일을 구분한다 — 디버깅할 때 원인이 갈린다."""
    r = client.get("/image", params={"path": "tests/fixtures/nope.jpg"})
    assert r.status_code == 404
