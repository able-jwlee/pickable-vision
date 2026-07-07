import cv2
import numpy as np

from app import config


def _plate_roi(gray: np.ndarray) -> np.ndarray:
    """밝은 plate 내부(agar) 영역 마스크(255=plate). 어두운 프레임/배경 제외.

    Otsu로 밝은 영역을 뽑고, 닫힘으로 콜로니 구멍을 메워 plate를 하나의 덩어리로
    만든 뒤, 침식으로 프레임 경계에서 안쪽으로 수축해 테두리 오검출을 막는다.
    """
    _, roi = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    close = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (config.ROI_CLOSE_KERNEL, config.ROI_CLOSE_KERNEL)
    )
    roi = cv2.morphologyEx(roi, cv2.MORPH_CLOSE, close)
    erode = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (config.ROI_ERODE_KERNEL, config.ROI_ERODE_KERNEL)
    )
    return cv2.erode(roi, erode)


def _well_mask(gray: np.ndarray) -> np.ndarray:
    """8개 웰(덱) 내부만 남긴 마스크. plate를 규칙 4×2 격자로 나눠 각 셀을 여백만큼
    안쪽으로 줄여 격자 벽·바깥 프레임을 제외한다(웰 밖 검출 방지).

    plate 위치는 _plate_roi의 bounding box에서 얻는다. 격자는 규칙적이라고 가정한다
    (source plate가 몰딩된 4×2 웰 구조). 여백(WELL_MARGIN)이 약간의 정렬 오차를 흡수한다.
    최종적으로 격자 마스크와 침식된 plate ROI를 교집합해, 셀이 바깥벽을 물어도 제외한다.
    """
    roi = _plate_roi(gray)
    ys, xs = np.where(roi > 0)
    if len(xs) == 0:
        return roi
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    mask = np.zeros(gray.shape, dtype=np.uint8)
    cw = (x1 - x0) / config.WELL_COLS
    ch = (y1 - y0) / config.WELL_ROWS
    mg = config.WELL_MARGIN
    for r in range(config.WELL_ROWS):
        for c in range(config.WELL_COLS):
            cx0, cx1 = int(x0 + c * cw + mg), int(x0 + (c + 1) * cw - mg)
            cy0, cy1 = int(y0 + r * ch + mg), int(y0 + (r + 1) * ch - mg)
            if cx1 > cx0 and cy1 > cy0:
                mask[cy0:cy1, cx0:cx1] = 255
    # 격자 셀 ∩ 침식된 plate ROI — 셀이 plate 바깥벽/프레임을 물어도 확실히 제외.
    return cv2.bitwise_and(mask, roi)


def pick_region(img: np.ndarray, edge_margin: int = 0) -> np.ndarray:
    """피킹 안전 영역 마스크(255=안전). 웰 마스크를 edge_margin만큼 더 침식해
    웰/plate 경계 근처를 제외한다. 벽 반점/데브리가 피킹 대상이 되는 것을 막는다.
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    roi = _well_mask(blur)
    if edge_margin > 0:
        k = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (edge_margin, edge_margin)
        )
        roi = cv2.erode(roi, k)
    return roi


def _remove_wall_streaks(binary: np.ndarray) -> np.ndarray:
    """길고 얇은 연결성분(벽면 메니스커스/agar 주름)을 제거한 이진 이미지를 반환.

    콜로니·콜로니 클러스터는 compact(aspect≈1~3)한 반면, 벽면 메니스커스는
    길고 가는 선형 성분(aspect≫)이다. 최대변이 길고(MENISCUS_MIN_LEN↑) 동시에
    가는(aspect≥MENISCUS_MIN_ASPECT) 성분만 지워, 내부 콜로니는 그대로 둔다.
    """
    n, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    out = binary
    for i in range(1, n):
        w = stats[i, cv2.CC_STAT_WIDTH]
        h = stats[i, cv2.CC_STAT_HEIGHT]
        long_side = max(w, h)
        aspect = long_side / max(1, min(w, h))
        if (
            long_side >= config.MENISCUS_MIN_LEN
            and aspect >= config.MENISCUS_MIN_ASPECT
        ):
            if out is binary:
                out = binary.copy()
            out[labels == i] = 0
    return out


def _circle_from_contour(
    contour: np.ndarray,
    min_area: float,
    max_area: float,
    min_circularity: float,
) -> tuple[float, float, float, float] | None:
    """contour가 넓이·원형도 필터를 통과하면 (x, y, radius, circularity), 아니면 None.

    circularity(4πA/P², 0~1)는 하류 피킹 품질 판정/랭킹에 쓰인다(1에 가까울수록 원).
    """
    area = cv2.contourArea(contour)
    if area < min_area or area > max_area:
        return None
    perimeter = cv2.arcLength(contour, True)
    if perimeter == 0:
        return None
    circularity = 4.0 * np.pi * area / (perimeter * perimeter)
    if circularity < min_circularity:
        return None
    (ex, ey), r = cv2.minEnclosingCircle(contour)
    # 중심은 무게중심(centroid)을 쓴다 — 로봇 핀이 콜로니 body 정중앙을 찍도록.
    # minEnclosingCircle 중심은 최외곽 기준이라 비대칭 콜로니에서 한쪽으로 치우친다.
    m = cv2.moments(contour)
    if m["m00"] > 0:
        cx, cy = m["m10"] / m["m00"], m["m01"] / m["m00"]
    else:
        cx, cy = ex, ey  # 면적 0 방어(직선형 등)
    return (float(cx), float(cy), float(r), float(min(circularity, 1.0)))


def _contour_circles(
    binary: np.ndarray,
    min_area: float,
    max_area: float,
    min_circularity: float,
) -> list[tuple[float, float, float, float]]:
    """연결 성분마다 하나의 원(붙은 콜로니는 하나로 병합)."""
    contours, _ = cv2.findContours(
        binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    circles = []
    for c in contours:
        circ = _circle_from_contour(c, min_area, max_area, min_circularity)
        if circ is not None:
            circles.append(circ)
    return circles


def _watershed_circles(
    img: np.ndarray,
    binary: np.ndarray,
    roi: np.ndarray | None,
    min_area: float,
    max_area: float,
    min_circularity: float,
) -> list[tuple[float, float, float, float]]:
    """거리변환 국소 최대를 씨앗으로 watershed하여 붙은 콜로니를 분리.

    크기가 다른 콜로니에 강하도록 전역 max가 아닌 국소 최대(local maxima)로
    씨앗을 잡는다. roi가 주어지면 영역 중심이 plate 밖이면 버린다.
    """
    dist = cv2.distanceTransform(binary, cv2.DIST_L2, 5)
    k = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE,
        (config.WATERSHED_MIN_DISTANCE, config.WATERSHED_MIN_DISTANCE),
    )
    peaks = (
        (dist == cv2.dilate(dist, k)) & (dist >= config.WATERSHED_SEED_MIN)
    ).astype(np.uint8) * 255

    _, markers = cv2.connectedComponents(peaks)
    markers = markers + 1
    sure_bg = cv2.dilate(binary, np.ones((3, 3), np.uint8), iterations=3)
    markers[cv2.subtract(sure_bg, peaks) == 255] = 0
    markers = cv2.watershed(img, markers)

    # 라벨별 bounding box를 전경 픽셀 1회 스캔으로 계산 → 각 라벨을 전체 이미지가
    # 아니라 작은 crop에서만 findContours. (라벨수×이미지) → (전경픽셀 1패스)로 대폭 가속.
    n_labels = int(markers.max())
    ys, xs = np.nonzero(markers > 1)
    if len(xs) == 0:
        return []
    labs = markers[ys, xs]
    minx = np.full(n_labels + 1, 1 << 30, np.int64)
    miny = np.full(n_labels + 1, 1 << 30, np.int64)
    maxx = np.full(n_labels + 1, -1, np.int64)
    maxy = np.full(n_labels + 1, -1, np.int64)
    np.minimum.at(minx, labs, xs)
    np.minimum.at(miny, labs, ys)
    np.maximum.at(maxx, labs, xs)
    np.maximum.at(maxy, labs, ys)

    circles = []
    for lbl in range(2, n_labels + 1):
        if maxx[lbl] < 0:  # 이 라벨은 전경 픽셀 없음
            continue
        x0, y0 = int(minx[lbl]), int(miny[lbl])
        sub = (
            markers[y0 : int(maxy[lbl]) + 1, x0 : int(maxx[lbl]) + 1] == lbl
        ).astype(np.uint8)
        contours, _ = cv2.findContours(
            sub, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        if not contours:
            continue
        c = max(contours, key=cv2.contourArea)
        circ = _circle_from_contour(c, min_area, max_area, min_circularity)
        if circ is None:
            continue
        cx, cy, r, q = circ
        cx, cy = cx + x0, cy + y0  # crop 좌표 → 전체 이미지 좌표
        if roi is not None:
            yi = int(min(max(cy, 0), roi.shape[0] - 1))
            xi = int(min(max(cx, 0), roi.shape[1] - 1))
            if roi[yi, xi] == 0:
                continue
        circles.append((cx, cy, r, q))
    return circles


def detect(
    img: np.ndarray,
    min_area: float,
    max_area: float,
    min_circularity: float,
    invert: bool,
    tophat_kernel: int,
    mask_walls: bool,
    threshold_offset: int = config.DEFAULT_THRESHOLD_OFFSET,
    split_touching: bool = config.DEFAULT_SPLIT_TOUCHING,
) -> list[tuple[float, float, float, float]]:
    """콜로니를 검출해 (x, y, radius, circularity) 리스트를 반환.

    파이프라인: 그레이 → 블러 → top-hat(조명 평탄화·콜로니 강조) →
    Otsu(전역 임계값, offset으로 민감도 조절) → (8웰 격자 제한) → 열림 →
    벽면 메니스커스(선형 성분) 제거 → [split_touching이면 watershed 분리] →
    contour → 넓이·원형도 필터 → 중심(무게중심)·반지름·원형도.

    top-hat은 국소 배경을 제거해 조명 불균일에 강하고, 밝은 격자 벽은 자연히
    억제된다. split_touching=True면 붙은 콜로니를 watershed로 분리한다(밀집
    구간 재현율↑, 과분할 위험이 있어 필요 시 요청에서 끌 수 있음. 기본 on).
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (3, 3), 0)

    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (tophat_kernel, tophat_kernel)
    )
    op = cv2.MORPH_BLACKHAT if invert else cv2.MORPH_TOPHAT
    hat = cv2.morphologyEx(blur, op, kernel)

    otsu_value, _ = cv2.threshold(
        hat, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )
    thresh = max(1.0, otsu_value - threshold_offset)
    _, binary = cv2.threshold(hat, thresh, 255, cv2.THRESH_BINARY)

    # mask_walls=True면 8개 웰(덱) 격자 내부로만 검출을 제한 (벽·프레임·웰 밖 제외).
    roi = _well_mask(blur) if mask_walls else None
    if roi is not None:
        binary[roi == 0] = 0

    opened = cv2.morphologyEx(binary, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    opened = _remove_wall_streaks(opened)

    if split_touching:
        return _watershed_circles(
            img, opened, roi, min_area, max_area, min_circularity
        )
    return _contour_circles(opened, min_area, max_area, min_circularity)
