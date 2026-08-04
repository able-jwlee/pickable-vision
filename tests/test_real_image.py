import base64
from pathlib import Path

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

FIXTURE = Path(__file__).parent / "fixtures" / "agar_sample.jpg"


def _fixture_b64() -> str:
    return base64.b64encode(FIXTURE.read_bytes()).decode()


def test_real_image_detects_colonies():
    """기본 경로(blob)가 실제 배양 이미지에서 동작하고 결과를 반환한다.

    이 픽스처는 4×2 몰딩 8웰 플레이트이고 blob 경로는 원형 petri 접시 기준으로
    튜닝돼 있다. 이 포맷은 정답 라벨이 없어 검출 수의 정답을 알 수 없으므로,
    개수 하한을 단정하지 않고 동작만 확인한다. 8웰 포맷의 검출률을 검증하려면
    라벨이 필요하다.
    """
    resp = client.post("/detect", json={"image": _fixture_b64()})
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] > 0
    assert body["count"] == len(body["colonies"])


def test_real_image_tophat_path_still_detects_many():
    resp = client.post(
        "/detect", json={"image": _fixture_b64(), "method": "tophat"}
    )
    body = resp.json()
    # 레거시 경로 하위호환 — 8웰 플레이트에 맞게 튜닝된 경로 (~438개)
    assert body["count"] > 100


def test_real_image_invert_false_detects_fewer():
    # invert는 tophat 전용 knob — blob 경로는 양극성을 모두 검출하므로 무시한다
    default = client.post(
        "/detect", json={"image": _fixture_b64(), "method": "tophat"}
    ).json()
    inverted = client.post(
        "/detect",
        json={"image": _fixture_b64(), "method": "tophat", "invert": False},
    ).json()
    assert inverted["count"] < default["count"]
