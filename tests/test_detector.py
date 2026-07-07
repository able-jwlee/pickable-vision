import cv2
import numpy as np

from app.detector import detect, _well_mask, _remove_wall_streaks


def _synthetic_plate() -> np.ndarray:
    """밝은 배경(200) + 어두운 원 3개(60) + 밝은 수직 벽(255) 한 줄."""
    img = np.full((300, 300, 3), 200, dtype=np.uint8)
    for cx, cy in [(60, 60), (150, 150), (240, 240)]:
        cv2.circle(img, (cx, cy), 12, (60, 60, 60), -1)
    cv2.line(img, (100, 0), (100, 300), (255, 255, 255), 6)  # 밝은 벽
    return img


def _detect(img, **kw):
    params = dict(
        min_area=50.0,
        max_area=5000.0,
        min_circularity=0.6,
        invert=True,
        tophat_kernel=31,
        mask_walls=False,  # 합성 이미지는 실제 8웰 plate가 아니므로 격자 제한 off
        threshold_offset=0,
    )
    params.update(kw)
    return detect(img, **params)


def test_detects_three_dark_circles():
    circles = _detect(_synthetic_plate())
    assert len(circles) == 3


def test_returns_x_y_radius_circularity_tuples():
    circles = _detect(_synthetic_plate())
    for x, y, r, circ in circles:
        assert r > 0
        assert 0.0 <= circ <= 1.0


def test_invert_false_misses_dark_colonies():
    # 어두운 콜로니는 invert=False에서 전경이 아니므로 검출이 급감
    circles = _detect(_synthetic_plate(), invert=False)
    assert len(circles) < 3


def test_area_filter_excludes_large_blobs():
    # max_area를 작은 원 넓이(≈452)보다 작게 두면 전부 걸러짐
    circles = _detect(_synthetic_plate(), max_area=100.0)
    assert len(circles) == 0


def test_wall_not_detected_as_colony():
    # 밝은 벽만 있는 이미지 → 콜로니 0
    img = np.full((300, 300, 3), 200, dtype=np.uint8)
    cv2.line(img, (150, 0), (150, 300), (255, 255, 255), 6)
    assert _detect(img) == []


def test_well_mask_includes_cells_excludes_gridlines():
    # 어두운 배경 위 밝은 plate 사각형 → 4x2 격자 마스크
    gray = np.zeros((440, 840), dtype=np.uint8)
    gray[20:420, 20:820] = 200
    m = _well_mask(gray)
    # plate bbox ≈ x[20,819], y[20,419] → col폭≈200, 행높≈200, margin 40
    # 첫 셀 중심(대략 x=120,y=120)은 포함
    assert m[120, 120] == 255
    # 첫/둘째 열 사이 벽 위치(대략 x=220)는 제외
    assert m[120, 220] == 0
    # 두 행 사이 벽 위치(대략 y=220)는 제외
    assert m[220, 120] == 0


def test_detect_excludes_outside_wells():
    # plate 밖(어두운 배경)에 찍힌 어두운 점은 웰 격자 밖이라 검출되지 않아야 함
    img = np.full((440, 840, 3), 30, dtype=np.uint8)   # 어두운 배경
    cv2.rectangle(img, (20, 20), (820, 420), (200, 200, 200), -1)  # 밝은 plate
    cv2.circle(img, (120, 120), 8, (60, 60, 60), -1)   # 웰 안 콜로니
    cv2.circle(img, (10, 10), 8, (0, 0, 0), -1)        # plate 밖(배경) 점
    circles = detect(
        img, min_area=20.0, max_area=5000.0, min_circularity=0.3,
        invert=True, tophat_kernel=31, mask_walls=True, split_touching=False,
    )
    # 검출된 것은 모두 밝은 plate 영역 안쪽(x>20)이어야 함
    assert circles, "웰 안 콜로니는 검출되어야 함"
    assert all(x > 20 for x, y, r, circ in circles)


def test_remove_wall_streaks_drops_line_keeps_blobs():
    # 길고 얇은 세로 줄(메니스커스) + 둥근 콜로니 blob 2개
    b = np.zeros((300, 300), dtype=np.uint8)
    b[20:280, 15:24] = 255              # 260x9 세로 줄 (aspect≈29) → 제거 대상
    cv2.circle(b, (150, 100), 8, 255, -1)  # 둥근 blob → 보존
    cv2.circle(b, (200, 200), 10, 255, -1)  # 둥근 blob → 보존
    out = _remove_wall_streaks(b)
    assert out[150, 15] == 0            # 줄은 지워짐
    assert out[100, 150] == 255         # blob 보존
    assert out[200, 200] == 255         # blob 보존


def _touching_pair() -> np.ndarray:
    """겹쳐 붙은 어두운 원 2개 (밝은 배경)."""
    img = np.full((200, 200, 3), 200, dtype=np.uint8)
    cv2.circle(img, (95, 100), 10, (60, 60, 60), -1)
    cv2.circle(img, (112, 100), 10, (60, 60, 60), -1)
    return img


def _detect_pair(**kw):
    params = dict(
        min_area=20.0,
        max_area=5000.0,
        min_circularity=0.3,
        invert=True,
        tophat_kernel=31,
        mask_walls=False,
    )
    params.update(kw)
    return detect(_touching_pair(), **params)


def test_split_touching_off_merges_pair():
    # 붙은 두 콜로니가 하나로 병합
    assert len(_detect_pair(split_touching=False)) == 1


def test_split_touching_on_separates_pair():
    # watershed로 두 콜로니 분리
    assert len(_detect_pair(split_touching=True)) == 2
