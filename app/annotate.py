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


def draw_for_response(
    img: np.ndarray,
    colonies: list,
    mode: str = "all",
    max_width: int = 0,
    marker: str = "square",
) -> tuple[np.ndarray, float]:
    """응답에 실어 보낼 표시 이미지와 **축소 배율**을 반환한다.

    (표시 이미지, scale) — scale은 원본 대비 배율이다. 응답의 콜로니 좌표는
    항상 **원본 픽셀** 기준이므로, 클라이언트가 축소 이미지 위에 좌표를 겹치려면
    좌표에 이 scale을 곱해야 한다.

    먼저 축소한 뒤 그린다. 원본에 그린 다음 축소하면 선이 1px 아래로 얇아져
    사실상 사라진다. 선 두께도 이미지 크기에 비례시켜 어느 해상도에서든 보이게 한다.

    marker="square" (기본) 는 정사각 테두리, "circle" 은 원을 그린다.
    네모가 기본인 이유: 콜로니 자체가 원형이라 원을 그리면 윤곽선과 겹쳐 어디가
    표시고 어디가 콜로니인지 구분이 어렵다. 직선 테두리는 배경의 원형·불규칙
    패턴과 형태가 달라 한천 텍스처 위에서도 눈에 띈다. 콜로니 지름 대비 여유를
    두어 콜로니를 가리지 않게 한다.
    """
    h, w = img.shape[:2]
    scale = 1.0
    if max_width and w > max_width:
        scale = max_width / w
        img = cv2.resize(img, (max_width, max(1, int(h * scale))),
                         interpolation=cv2.INTER_AREA)

    out = img.copy()
    th = max(1, int(round(max(out.shape[:2]) / 600)))
    pick_only = mode == "pick"
    for c in colonies:
        if pick_only and not getattr(c, "pickable", False):
            continue
        colour = (config.DRAW_PICK_COLOR if getattr(c, "pickable", False)
                  else config.DRAW_COLOR)
        cx, cy = int(c.x * scale), int(c.y * scale)
        # 콜로니를 가리지 않게 반지름에 여유를 준다. 작은 콜로니는 반지름이
        # 1~2px 이라 그대로 그리면 점이 되므로 최소 크기를 둔다.
        rad = max(int(c.radius * scale * config.DRAW_MARKER_PAD), th * 3)
        if marker == "circle":
            cv2.circle(out, (cx, cy), rad, colour, th)
        else:
            cv2.rectangle(out, (cx - rad, cy - rad), (cx + rad, cy + rad),
                          colour, th)
    return out, scale


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
