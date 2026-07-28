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


def test_detect_returns_applied_params():
    resp = client.post(
        "/detect",
        json={"image": _synthetic_b64(), "min_area": 50, "mask_walls": False},
    )
    body = resp.json()
    assert "applied_params" in body
    ap = body["applied_params"]
    # raw 필드 그대로 반영되는지 확인
    assert ap["min_area"] == 50
    # 요청에 없던 값은 서버 default가 담김
    assert "threshold_offset" in ap
    assert "max_area" in ap
    assert "pick_edge_margin" in ap
    assert "split_touching" in ap
    assert "pick_top_n" in ap


def test_abstract_sensitivity_overrides_threshold_offset():
    # sensitivity=100 → threshold_offset should be 15, ignoring raw field
    resp = client.post(
        "/detect",
        json={
            "image": _synthetic_b64(),
            "mask_walls": False,
            "threshold_offset": 0,   # should be OVERRIDDEN
            "sensitivity": 100,
        },
    )
    ap = resp.json()["applied_params"]
    assert ap["threshold_offset"] == 15


def test_abstract_min_size_overrides_min_area():
    resp = client.post(
        "/detect",
        json={
            "image": _synthetic_b64(),
            "mask_walls": False,
            "min_area": 999,          # should be OVERRIDDEN
            "min_size": 20,
        },
    )
    ap = resp.json()["applied_params"]
    # min_size=20 → min_area ≈ 5.81 (current default)
    assert abs(ap["min_area"] - 5.81) < 0.5


def test_abstract_edge_margin_overrides_config():
    resp = client.post(
        "/detect",
        json={
            "image": _synthetic_b64(),
            "mask_walls": True,
            "edge_margin": 100,       # → 150px
        },
    )
    ap = resp.json()["applied_params"]
    assert ap["pick_edge_margin"] == 150


def test_default_abstract_matches_raw_defaults():
    """새 필드 미지정 요청과 abstract default(50/20/75/40) 요청이 같은 결과."""
    raw = client.post(
        "/detect",
        json={"image": _synthetic_b64(), "min_area": 50, "mask_walls": False},
    ).json()
    abstract = client.post(
        "/detect",
        json={
            "image": _synthetic_b64(),
            "mask_walls": False,
            "sensitivity": 50,
            "max_size": 75,
            "edge_margin": 40,
            # min_size는 지정 안 함 — 기존 min_area=50과 비교
            "min_area": 50,
        },
    ).json()
    assert abstract["count"] == raw["count"]


SAMPLE_PATH = "tests/fixtures/agar_sample.jpg"


def _post_detect(**abstract):
    return client.post(
        "/detect",
        json={"image_path": SAMPLE_PATH, **abstract},
    ).json()


def test_sensitivity_direction_more_sensitive_finds_more():
    strict = _post_detect(sensitivity=0)["count"]
    permissive = _post_detect(sensitivity=100)["count"]
    assert permissive > strict, (
        f"expected permissive({permissive}) > strict({strict})"
    )


def test_min_size_direction_stricter_finds_fewer():
    permissive = _post_detect(min_size=0)["count"]
    strict = _post_detect(min_size=100)["count"]
    assert strict < permissive, (
        f"expected strict({strict}) < permissive({permissive})"
    )


def test_edge_margin_direction_larger_margin_reduces_pickable():
    def pickable(edge):
        colonies = _post_detect(edge_margin=edge)["colonies"]
        return sum(1 for c in colonies if c["pickable"])
    assert pickable(100) <= pickable(0), (
        "larger edge margin should not increase pickable count"
    )
