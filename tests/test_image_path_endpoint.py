from pathlib import Path

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

FIXTURE = Path(__file__).parent / "fixtures" / "agar_sample.jpg"


def test_detect_via_image_path():
    resp = client.post("/detect", json={"image_path": str(FIXTURE)})
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] > 100
    assert body["width"] == 1350
    assert body["height"] == 910


def test_detect_missing_file_returns_400():
    resp = client.post("/detect", json={"image_path": "no/such/file.jpg"})
    assert resp.status_code == 400


def test_detect_no_source_returns_422():
    resp = client.post("/detect", json={"min_area": 20})
    assert resp.status_code == 422


def test_preview_via_image_path():
    resp = client.post("/detect/preview", json={"image_path": str(FIXTURE)})
    assert resp.status_code == 200
    assert resp.json()["count"] > 100
