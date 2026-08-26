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
        "/detect", json={"image": _synthetic_b64(), "mask_walls": False}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["width"] == 300
    assert body["height"] == 300
    assert body["count"] == len(body["colonies"])
    assert body["count"] >= 3
    first = body["colonies"][0]
    assert set(first) == {
        "id", "x", "y", "radius", "circularity", "score", "pickable",
        "parent_id",
    }
    assert body["colonies"][0]["id"] == 1


def test_detect_marks_pickable():
    # 멀리 떨어진 적당한 크기 3개 → 모두 피킹 후보
    resp = client.post("/detect", json={"image": _synthetic_b64(), "mask_walls": False})
    body = resp.json()
    assert sum(1 for c in body["colonies"] if c["pickable"]) >= 3


def test_detect_pick_top_n_limits():
    resp = client.post(
        "/detect",
        json={"image": _synthetic_b64(), "pick_top_n": 2, "mask_walls": False},
    )
    body = resp.json()
    assert sum(1 for c in body["colonies"] if c["pickable"]) == 2


def test_detect_invalid_base64_returns_400():
    resp = client.post("/detect", json={"image": "!!!not base64!!!"})
    assert resp.status_code == 400


def test_detect_returns_applied_params():
    resp = client.post(
        "/detect",
        json={"image": _synthetic_b64(), "mask_walls": False},
    )
    body = resp.json()
    assert "applied_params" in body
    ap = body["applied_params"]
    # 요청에 없던 값은 서버 default 가 담긴다 (튜닝 재현·이슈 리포트용).
    for key in ("plate_type", "polarity", "min_t", "work_size",
                "pick_edge_margin", "pick_top_n",
                "min_rel_sat", "exclude_nested", "has_chroma"):
        assert key in ap, f"applied_params 에 {key} 누락"


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
    """추상 필드를 기본값으로 명시한 요청과 아예 안 준 요청이 같은 결과여야 한다.

    어긋나면 sensitivity 를 보내는 클라이언트와 안 보내는 클라이언트가 서로 다른
    감도로 동작한다 — 눈으로 알아채기 어려운 종류의 버그다.
    """
    raw = client.post(
        "/detect",
        json={"image": _synthetic_b64(), "mask_walls": False},
    ).json()
    abstract = client.post(
        "/detect",
        json={
            "image": _synthetic_b64(),
            "mask_walls": False,
            "sensitivity": 50,
        },
    ).json()
    assert abstract["count"] == raw["count"]


SAMPLE_PATH = "tests/fixtures/agar_sample.jpg"


def _post_detect(**abstract):
    return client.post(
        "/detect",
        json={"image_path": SAMPLE_PATH, **abstract},
    ).json()


def _post_tophat(**abstract):
    """tophat 전용 knob(min_area/invert/threshold_offset)을 검증할 때 쓴다.

    기본 경로는 method="blob"이고 이 knob들을 무시하므로, 레거시 knob의
    방향성을 확인하는 테스트는 경로를 명시해야 한다.
    """
    return client.post(
        "/detect",
        json={"image_path": SAMPLE_PATH, "method": "tophat", **abstract},
    ).json()


def test_sensitivity_direction_more_sensitive_finds_more():
    """감도 방향성은 두 경로 모두에서 성립해야 한다(blob은 min_t로 매핑)."""
    strict = _post_detect(sensitivity=0)["count"]
    permissive = _post_detect(sensitivity=100)["count"]
    assert permissive > strict, (
        f"expected permissive({permissive}) > strict({strict})"
    )


def test_edge_margin_direction_larger_margin_reduces_pickable():
    def pickable(edge):
        colonies = _post_detect(edge_margin=edge)["colonies"]
        return sum(1 for c in colonies if c["pickable"])
    assert pickable(100) <= pickable(0), (
        "larger edge margin should not increase pickable count"
    )


def test_applied_params_reports_pick_mask_switch():
    """`pick_edge_margin` 만 돌려주면 여백이 적용됐는지 알 수 없다.

    경계 여백은 `mask_walls` 가 꺼져 있으면 무동작이다. UI 가
    applied_params 만 보고 화면에 표시하므로 스위치도 함께 실려야 한다.
    """
    for mask_walls in (True, False):
        resp = client.post(
            "/detect", json={"image": _synthetic_b64(), "mask_walls": mask_walls}
        )
        applied = resp.json()["applied_params"]
        assert applied["mask_walls"] is mask_walls
        assert "pick_edge_margin" in applied


def test_applied_params_reports_plate_size_reference():
    """크기 창(`min/max_diam_frac`)의 분모를 돌려준다.

    비율의 기준 길이는 petri 접시면 접시 지름이지만, well8 이거나 접시
    검출이 실패하면 이미지 짧은 변으로 조용히 폴백한다. UI 가 "5% = 몇 px"
    을 표시하려면 서버가 쓴 기준 길이를 알아야 한다.
    """
    resp = client.post(
        "/detect", json={"image": _synthetic_b64(), "mask_walls": False}
    )
    applied = resp.json()["applied_params"]
    assert applied["plate_size_ref"] > 0
    # 원본 픽셀 기준이다. 프레임보다 클 수 있다 — HoughCircles 가 이미지 밖으로
    # 걸치는 원을 맞출 수 있어서(이 합성 300x300 에서 338 이 나온다). 그래서
    # UI 는 이 값을 그대로 표시하지 말고 크기 창 환산에만 쓸 것.
    assert applied["plate_size_ref"] <= 300 * 2
