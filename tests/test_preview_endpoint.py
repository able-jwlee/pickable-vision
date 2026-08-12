import base64

import cv2
import numpy as np
from fastapi.testclient import TestClient

from app.image_io import decode_base64_image
from main import app

client = TestClient(app)


def _synthetic_b64() -> str:
    img = np.full((300, 300, 3), 200, dtype=np.uint8)
    for cx, cy in [(60, 60), (150, 150), (240, 240)]:
        cv2.circle(img, (cx, cy), 12, (60, 60, 60), -1)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return base64.b64encode(buf).decode()


def test_preview_returns_valid_png():
    resp = client.post(
        "/detect/preview", json={"image": _synthetic_b64(), "mask_walls": False}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] >= 3
    # 반환된 base64가 실제 디코드 가능한 이미지인지 확인
    out = decode_base64_image(body["image"])
    assert out.shape == (300, 300, 3)
