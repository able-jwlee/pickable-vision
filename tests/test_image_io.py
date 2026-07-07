import base64

import cv2
import numpy as np
import pytest

from app.image_io import decode_base64_image, encode_png_base64, read_image_file


def _sample_png_b64(prefix: bool = False) -> str:
    img = np.full((10, 10, 3), 128, dtype=np.uint8)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    b64 = base64.b64encode(buf).decode()
    return f"data:image/png;base64,{b64}" if prefix else b64


def test_decode_plain_base64():
    img = decode_base64_image(_sample_png_b64())
    assert img.shape == (10, 10, 3)


def test_decode_strips_data_uri_prefix():
    img = decode_base64_image(_sample_png_b64(prefix=True))
    assert img.shape == (10, 10, 3)


def test_decode_invalid_base64_raises():
    with pytest.raises(ValueError):
        decode_base64_image("!!!not base64!!!")


def test_decode_non_image_bytes_raises():
    junk = base64.b64encode(b"hello world").decode()
    with pytest.raises(ValueError):
        decode_base64_image(junk)


def test_encode_roundtrip():
    img = np.full((5, 5, 3), 200, dtype=np.uint8)
    out = decode_base64_image(encode_png_base64(img))
    assert out.shape == (5, 5, 3)


def test_read_image_file(tmp_path):
    path = tmp_path / "sample.png"
    cv2.imwrite(str(path), np.full((8, 8, 3), 100, dtype=np.uint8))
    img = read_image_file(str(path))
    assert img.shape == (8, 8, 3)


def test_read_image_file_missing_raises():
    with pytest.raises(ValueError):
        read_image_file("no/such/file.png")


def test_read_image_file_non_image_raises(tmp_path):
    path = tmp_path / "not_image.txt"
    path.write_text("hello")
    with pytest.raises(ValueError):
        read_image_file(str(path))
