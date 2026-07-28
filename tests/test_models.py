import pytest
from pydantic import ValidationError

from app.models import DetectRequest


def test_defaults_applied():
    req = DetectRequest(image="x")
    assert req.min_area == 6.0
    assert req.max_area == 5000.0
    assert req.min_circularity == 0.42
    assert req.invert is True
    assert req.tophat_kernel == 31
    assert req.threshold_offset == 7
    assert req.mask_walls is True
    assert req.split_touching is True


def test_tophat_kernel_too_small_rejected():
    with pytest.raises(ValidationError):
        DetectRequest(image="x", tophat_kernel=1)


def test_circularity_out_of_range_rejected():
    with pytest.raises(ValidationError):
        DetectRequest(image="x", min_circularity=1.5)


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
        min_size=20,
        max_size=80,
        edge_margin=40,
    )
    assert req.sensitivity == 50
    assert req.min_size == 20
    assert req.max_size == 80
    assert req.edge_margin == 40


def test_detect_request_abstract_fields_default_to_none():
    req = DetectRequest(image="Zm9v")
    assert req.sensitivity is None
    assert req.min_size is None
    assert req.max_size is None
    assert req.edge_margin is None


def test_detect_request_rejects_out_of_range_abstract_field():
    with pytest.raises(ValidationError):
        DetectRequest(image="Zm9v", sensitivity=101)
    with pytest.raises(ValidationError):
        DetectRequest(image="Zm9v", min_size=-1)
