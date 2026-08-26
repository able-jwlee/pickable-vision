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


def test_preview_honours_marker_shape():
    """프리뷰는 파라미터를 눈으로 튜닝하는 엔드포인트인데 `marker` 를 무시했다.

    `marker` 가 `return_image` 전용이라 프리뷰·저장 이미지는 항상 원이었다.
    모양 knob 을 보려고 쓰는 화면에서 정작 모양이 안 바뀌면 쓸 수 없다.
    """
    img = _synthetic_b64()
    sq = client.post(
        "/detect/preview", json={"image": img, "mask_walls": False, "marker": "square"}
    ).json()["image"]
    ci = client.post(
        "/detect/preview", json={"image": img, "mask_walls": False, "marker": "circle"}
    ).json()["image"]
    assert sq != ci, "marker 를 바꿔도 프리뷰 이미지가 같다"
