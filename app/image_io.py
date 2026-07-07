import base64
import binascii
from pathlib import Path

import cv2
import numpy as np


def read_image_file(path: str) -> np.ndarray:
    """로컬 파일 경로를 BGR 이미지로 읽는다 (로컬 튜닝 편의용).

    np.fromfile + imdecode를 써서 한글 등 비-ASCII 경로도 읽는다
    (cv2.imread는 Windows 비-ASCII 경로를 못 읽음).
    """
    p = Path(path)
    if not p.is_file():
        raise ValueError(f"image file not found: {path}")
    buf = np.fromfile(str(p), dtype=np.uint8)
    img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"could not read image file: {path}")
    return img


def decode_base64_image(data: str) -> np.ndarray:
    """base64 문자열(data URI 접두사 허용)을 BGR 이미지로 디코드."""
    text = data.strip()
    if text.startswith("data:") and "," in text:
        text = text.split(",", 1)[1]
    try:
        raw = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("invalid base64 image data") from exc
    arr = np.frombuffer(raw, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("could not decode image bytes")
    return img


def encode_png_base64(img: np.ndarray) -> str:
    """BGR 이미지를 PNG base64 문자열로 인코드."""
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise ValueError("could not encode image to png")
    return base64.b64encode(buf).decode()
