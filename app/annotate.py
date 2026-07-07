from pathlib import Path

import cv2
import numpy as np

from app import config


def draw_colonies(
    img: np.ndarray,
    circles: list[tuple[float, float, float]],
) -> np.ndarray:
    """검출된 콜로니를 붉은 원으로 표시한 새 이미지를 반환 (원본 불변)."""
    out = img.copy()
    for x, y, r in circles:
        cv2.circle(
            out,
            (int(x), int(y)),
            max(int(r), config.MIN_DRAW_RADIUS),
            config.DRAW_COLOR,
            config.DRAW_THICKNESS,
        )
    return out


def draw_pick_targets(
    img: np.ndarray, colonies: list, mode: str = "all"
) -> np.ndarray:
    """콜로니를 표시한 새 이미지를 반환 (원본 불변).

    colonies: x, y, radius, pickable 속성을 가진 객체 리스트(Pydantic Colony 등).
    mode:
      "all"  → 검출 전체를 붉은 원으로 (카운트/분석용).
      "pick" → 피킹 대상(pickable=True)만 초록 굵은 원으로 (로봇이 실제 집을
               안전 후보만 보여줌). 밀집·노이즈는 pickable에서 이미 제외돼 안 그려짐.
    두 모드 모두 응답 JSON의 값은 바꾸지 않는다(표시만 다름).
    """
    if mode == "pick":
        out = img.copy()
        for c in colonies:
            if getattr(c, "pickable", False):
                cv2.circle(
                    out,
                    (int(c.x), int(c.y)),
                    max(int(c.radius), config.MIN_DRAW_RADIUS),
                    config.DRAW_PICK_COLOR,
                    config.DRAW_THICKNESS + 1,
                )
        return out
    return draw_colonies(img, [(c.x, c.y, c.radius) for c in colonies])


def save_annotated(img: np.ndarray, out_dir: str, name: str) -> Path:
    """이미지를 out_dir/name 으로 저장하고 저장 경로를 반환. 폴더 없으면 생성.

    imencode + tofile을 써서 한글 등 비-ASCII 경로에도 저장한다
    (cv2.imwrite는 Windows 비-ASCII 경로를 못 씀).
    """
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    ext = path.suffix if path.suffix else ".jpg"
    ok, buf = cv2.imencode(ext, img)
    if not ok:
        raise ValueError(f"could not encode image for {path}")
    buf.tofile(str(path))
    return path
