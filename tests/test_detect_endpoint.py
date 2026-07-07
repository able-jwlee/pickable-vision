import base64

import cv2
import numpy as np
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def _synthetic_b64() -> str:
    img = np.full((300, 300, 3), 200, dtype=np.uint8)
    for cx, cy in [(60, 60), (150, 150), (240, 240)]:
        cv2.circle(img, (cx, cy), 12, (60, 60, 60), -1)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return base64.b64encode(buf).decode()


def test_detect_returns_colonies():
    resp = client.post(
        "/detect", json={"image": _synthetic_b64(), "min_area": 50, "mask_walls": False}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["width"] == 300
    assert body["height"] == 300
    assert body["count"] == len(body["colonies"])
    assert body["count"] >= 3
    first = body["colonies"][0]
    assert set(first) == {
        "id", "x", "y", "radius", "circularity", "score", "pickable"
    }
    assert body["colonies"][0]["id"] == 1


def test_detect_marks_pickable():
    # 멀리 떨어진 적당한 크기 3개 → 모두 피킹 후보
    resp = client.post("/detect", json={"image": _synthetic_b64(), "min_area": 50, "mask_walls": False})
    body = resp.json()
    assert sum(1 for c in body["colonies"] if c["pickable"]) >= 3


def test_detect_pick_top_n_limits():
    resp = client.post(
        "/detect",
        json={"image": _synthetic_b64(), "min_area": 50, "pick_top_n": 2, "mask_walls": False},
    )
    body = resp.json()
    assert sum(1 for c in body["colonies"] if c["pickable"]) == 2


def test_detect_invalid_base64_returns_400():
    resp = client.post("/detect", json={"image": "!!!not base64!!!"})
    assert resp.status_code == 400


def test_detect_invalid_tophat_kernel_returns_422():
    resp = client.post(
        "/detect", json={"image": _synthetic_b64(), "tophat_kernel": 1}
    )
    assert resp.status_code == 422
