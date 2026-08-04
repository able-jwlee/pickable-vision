"""/detect 가 좌표와 표시 이미지를 **한 응답에** 담는지 검증.

/detect 는 좌표만, /detect/preview 는 이미지만 주므로 둘을 같이 받을 방법이
없었다. return_image 플래그가 그 간극을 메운다.

좌표는 항상 원본 픽셀 기준이고 이미지는 전송을 위해 축소될 수 있으므로,
축소 배율(annotated_image_scale)이 함께 와야 클라이언트가 겹쳐 그릴 수 있다.
이 계약이 깨지면 UI에서 원이 엉뚱한 곳에 그려진다.
"""
import base64

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def _synthetic_b64(size=2400) -> str:
    """접시 위 콜로니 3개. 축소가 일어나도록 기본 폭(1600)보다 크게 만든다."""
    img = np.full((size, size, 3), 15, dtype=np.uint8)
    cv2.circle(img, (size // 2, size // 2), int(size * 0.45), (60, 90, 70), -1)
    for cx, cy in [(900, 900), (1500, 960), (1200, 1500)]:
        cv2.circle(img, (cx, cy), 90, (150, 200, 170), -1)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return base64.b64encode(buf).decode()


def _decode(b64: str) -> np.ndarray:
    arr = np.frombuffer(base64.b64decode(b64), dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    assert img is not None
    return img


def test_no_image_by_default():
    body = client.post("/detect", json={"image": _synthetic_b64()}).json()
    assert body["annotated_image"] is None
    assert body["annotated_image_scale"] == 1.0


def test_returns_image_and_coordinates_together():
    body = client.post(
        "/detect", json={"image": _synthetic_b64(), "return_image": True}
    ).json()
    assert body["count"] > 0
    assert body["colonies"], "좌표가 함께 와야 한다"
    assert body["annotated_image"], "표시 이미지가 함께 와야 한다"
    img = _decode(body["annotated_image"])
    assert img.ndim == 3


def test_image_downscaled_to_max_width_and_scale_reported():
    body = client.post(
        "/detect",
        json={"image": _synthetic_b64(), "return_image": True,
              "image_max_width": 800},
    ).json()
    img = _decode(body["annotated_image"])
    assert img.shape[1] == 800
    assert body["annotated_image_scale"] == pytest.approx(800 / body["width"])


def test_coordinates_stay_in_original_pixels():
    """이미지를 축소해도 좌표는 원본 픽셀이어야 한다."""
    small = client.post(
        "/detect",
        json={"image": _synthetic_b64(), "return_image": True,
              "image_max_width": 600},
    ).json()
    full = client.post(
        "/detect",
        json={"image": _synthetic_b64(), "return_image": True,
              "image_max_width": 0},
    ).json()
    assert small["annotated_image_scale"] < 1.0
    assert full["annotated_image_scale"] == 1.0
    # 같은 이미지이므로 좌표는 동일해야 한다 (이미지 크기와 무관)
    assert len(small["colonies"]) == len(full["colonies"])
    for a, b in zip(small["colonies"], full["colonies"]):
        assert a["x"] == pytest.approx(b["x"])
        assert a["y"] == pytest.approx(b["y"])


def test_scaled_coordinates_land_inside_returned_image():
    """좌표 × scale 이 반환된 이미지 범위 안에 들어와야 한다."""
    body = client.post(
        "/detect",
        json={"image": _synthetic_b64(), "return_image": True,
              "image_max_width": 700},
    ).json()
    img = _decode(body["annotated_image"])
    h, w = img.shape[:2]
    s = body["annotated_image_scale"]
    for c in body["colonies"]:
        assert 0 <= c["x"] * s < w
        assert 0 <= c["y"] * s < h


def test_max_width_zero_keeps_original_size():
    body = client.post(
        "/detect",
        json={"image": _synthetic_b64(), "return_image": True,
              "image_max_width": 0},
    ).json()
    img = _decode(body["annotated_image"])
    assert img.shape[1] == body["width"]


def _noisy_b64(size=2400) -> str:
    """센서 노이즈가 있는 이미지 — 실제 접시 사진에 가깝다.

    평탄한 합성 이미지는 PNG가 오히려 작게 압축되므로(무손실인데 반복 패턴이
    많음) 형식 크기 비교에는 쓸 수 없다. 실제 사진에는 노이즈가 있어 PNG가
    훨씬 커진다 — 실측: 2048px 접시 사진에서 PNG 4.2MB 대 JPEG 279KB.
    """
    rng = np.random.RandomState(0)
    img = np.full((size, size, 3), 15, dtype=np.uint8)
    cv2.circle(img, (size // 2, size // 2), int(size * 0.45), (60, 90, 70), -1)
    for cx, cy in [(900, 900), (1500, 960), (1200, 1500)]:
        cv2.circle(img, (cx, cy), 90, (150, 200, 170), -1)
    noise = rng.normal(0, 6, img.shape)
    img = np.clip(img.astype(np.float32) + noise, 0, 255).astype(np.uint8)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return base64.b64encode(buf).decode()


def test_png_is_larger_than_jpeg_on_photographic_input():
    """기본값이 JPEG인 이유 — 실제 사진에서는 PNG 응답이 훨씬 커진다."""
    b64 = _noisy_b64()

    def size(fmt):
        body = client.post(
            "/detect",
            json={"image": b64, "return_image": True,
                  "image_format": fmt, "image_max_width": 0},
        ).json()
        return len(body["annotated_image"])

    assert size("png") > size("jpeg")


def test_both_formats_decode():
    for fmt in ("jpeg", "png"):
        body = client.post(
            "/detect",
            json={"image": _synthetic_b64(), "return_image": True,
                  "image_format": fmt},
        ).json()
        assert _decode(body["annotated_image"]).ndim == 3


def test_invalid_image_params_rejected():
    for bad in ({"image_format": "gif"}, {"image_quality": 10},
                {"image_quality": 200}, {"image_max_width": -1}):
        resp = client.post(
            "/detect", json={"image": _synthetic_b64(), "return_image": True, **bad}
        )
        assert resp.status_code == 422, f"{bad} 는 422여야 함"
