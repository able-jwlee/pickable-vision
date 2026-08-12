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
