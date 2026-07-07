import base64
from pathlib import Path

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

FIXTURE = Path(__file__).parent / "fixtures" / "agar_sample.jpg"


def _fixture_b64() -> str:
    return base64.b64encode(FIXTURE.read_bytes()).decode()


def test_real_image_detects_many_colonies():
    resp = client.post("/detect", json={"image": _fixture_b64()})
    assert resp.status_code == 200
    body = resp.json()
    # 실제 배양 이미지엔 콜로니가 다수 존재 (튜닝 결과 ~438개)
    assert body["count"] > 100


def test_real_image_invert_false_detects_fewer():
    default = client.post("/detect", json={"image": _fixture_b64()}).json()
    inverted = client.post(
        "/detect", json={"image": _fixture_b64(), "invert": False}
    ).json()
    assert inverted["count"] < default["count"]
