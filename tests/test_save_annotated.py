from pathlib import Path

import cv2
from fastapi.testclient import TestClient

from app import config
from main import app

client = TestClient(app)

FIXTURE = Path(__file__).parent / "fixtures" / "agar_sample.jpg"


def test_detect_saves_annotated_image(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OUTPUT_DIR", str(tmp_path))
    resp = client.post(
        "/detect", json={"image_path": str(FIXTURE), "save_annotated": True}
    )
    assert resp.status_code == 200
    saved = resp.json()["annotated_path"]
    assert saved is not None
    p = Path(saved)
    assert p.is_file()
    # 저장된 이미지는 원본과 같은 크기의 유효한 이미지
    img = cv2.imread(str(p))
    assert img.shape == (910, 1350, 3)


def test_detect_without_save_has_null_path():
    resp = client.post("/detect", json={"image_path": str(FIXTURE)})
    assert resp.status_code == 200
    assert resp.json()["annotated_path"] is None
