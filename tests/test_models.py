import pytest
from pydantic import ValidationError

from app.models import DetectRequest


def test_defaults_applied():
    """기본값은 config 에서 온다. 값 자체가 아니라 **출처**를 고정한다 —
    실측으로 최적값을 바꿀 때 테스트가 발목을 잡으면 안 된다."""
    from app import config

    req = DetectRequest(image="x")
    assert req.plate_type == "petri"
    assert req.polarity == "auto"
    assert req.min_solidity == config.BLOB_MIN_SOLIDITY
    assert req.min_roundness == config.BLOB_MIN_ROUNDNESS
    assert req.work_size == config.BLOB_WORK_SIZE
    assert req.watershed_split is config.BLOB_WATERSHED_SPLIT
    assert req.mask_walls is True


def test_missing_both_sources_rejected():
    with pytest.raises(ValidationError):
        DetectRequest()


def test_image_path_alone_is_valid():
    req = DetectRequest(image_path="some/path.jpg")
    assert req.image is None
    assert req.image_path == "some/path.jpg"


def test_detect_request_accepts_abstract_fields():
    req = DetectRequest(
        image="Zm9v",  # base64 dummy
        sensitivity=50,
        edge_margin=40,
    )
    assert req.sensitivity == 50
    assert req.edge_margin == 40


def test_detect_request_abstract_fields_default_to_none():
    req = DetectRequest(image="Zm9v")
    assert req.sensitivity is None
    assert req.edge_margin is None


def test_detect_request_rejects_out_of_range_abstract_field():
    with pytest.raises(ValidationError):
        DetectRequest(image="Zm9v", sensitivity=101)
    with pytest.raises(ValidationError):
        DetectRequest(image="Zm9v", edge_margin=-1)


def test_pick_top_n_rejects_zero_and_negative():
    """상한이 0/음수면 조용히 이상하게 동작한다 — 422 로 막는다.

    scoring 은 `ranked[:top_n]` 으로 자르므로 top_n=-3 이면 "상위 3개"가
    아니라 **하위 3개를 뺀 전부**가 pickable 로 남는다. 오퍼레이터가
    알아챌 수 없는 오동작이라 스키마에서 막는다.
    """
    for bad in (0, -1, -3):
        with pytest.raises(ValidationError):
            DetectRequest(image="x", pick_top_n=bad)


def test_pick_top_n_accepts_positive():
    assert DetectRequest(image="x", pick_top_n=96).pick_top_n == 96


def test_target_color_rejects_out_of_range_channels():
    """0~255 밖 값은 numpy 가 조용히 감아버린다 (300 → 44).

    스펙에 항목 범위가 없으면 UI 가 생성한 타입도 그것을 막지 못하므로,
    잘못된 색으로 검출이 돌아간 것을 아무도 모른다.
    """
    for bad in ([300, 0, 0], [-5, 0, 0], [0, 0, 256]):
        with pytest.raises(ValidationError):
            DetectRequest(image="x", target_color=bad)


def test_target_color_accepts_full_range():
    for ok in ([0, 0, 0], [255, 255, 255], [214, 198, 120]):
        assert DetectRequest(image="x", target_color=ok).target_color == ok
