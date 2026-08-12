"""4×2 몰딩 8웰 플레이트의 ROI 마스크.

`app/detector.py`(top-hat 검출 경로)에서 옮겨왔다. 그 경로는 실측에서 정밀도
0.85% / 재현율 33.0% 로 **네 촬영 조건 모두에서 무작위 산포보다 나빠** 제거했지만,
여기 있는 격자 ROI 는 검출 방식과 무관한 **기하구조 정보**라 blob 경로가
`plate_type="well8"` 에서 그대로 쓴다.

원형 petri 접시용 ROI 는 `blob_detector.dish_roi` 가 담당한다. 둘을 나눠 둔 이유는
기하구조가 근본적으로 다르기 때문이다 — 원으로 강제하면 사각 플레이트의 모서리
웰이 잘려나가고, 격자로 강제하면 둥근 접시가 8조각으로 잘린다.

**주의: 이 격자는 8웰 포맷에서 검증된 적이 없다.** 그 포맷에 정답 라벨이 없어
성능을 측정할 방법이 없기 때문이다(개선 보고서 §8.4). 라벨 10~20장을 확보하면
`scripts/evaluate_labeled.py` 가 그대로 읽는다.
"""
import cv2
import numpy as np

from app import config


def plate_roi(gray: np.ndarray) -> np.ndarray:
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


def well_mask(gray: np.ndarray) -> np.ndarray:
    """8개 웰(덱) 내부만 남긴 마스크. plate를 규칙 4×2 격자로 나눠 각 셀을 여백만큼
    안쪽으로 줄여 격자 벽·바깥 프레임을 제외한다(웰 밖 검출 방지).

    plate 위치는 plate_roi의 bounding box에서 얻는다. 격자는 규칙적이라고 가정한다
    (source plate가 몰딩된 4×2 웰 구조). 여백(WELL_MARGIN)이 약간의 정렬 오차를 흡수한다.
    최종적으로 격자 마스크와 침식된 plate ROI를 교집합해, 셀이 바깥벽을 물어도 제외한다.
    """
    roi = plate_roi(gray)
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

    원형 접시용은 `blob_detector.dish_pick_region` 이다.
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    roi = well_mask(blur)
    if edge_margin > 0:
        k = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (edge_margin, edge_margin)
        )
        roi = cv2.erode(roi, k)
    return roi
