"""blob 검출기 테스트.

검증 대상은 이 모듈이 기존 top-hat 경로의 실패 원인으로 규명된 세 가지를
실제로 해결하는지다: 극성 고정, 콜로니보다 작은 커널, 8웰 격자 ROI.
"""
import cv2
import numpy as np

from app import config
from app.blob_detector import detect_blobs, dish_pick_region, dish_roi


def _dish(
    agar: int = 60,
    colony: int = 140,
    radius: int = 40,
    colony_bgr: tuple[int, int, int] | None = None,
    agar_bgr: tuple[int, int, int] | None = None,
    size: int = 800,
) -> np.ndarray:
    """원형 접시 위에 콜로니 3개. 색과 극성을 인자로 바꿀 수 있다."""
    img = np.full((size, size, 3), 15, dtype=np.uint8)  # 접시 밖 어두운 배경
    cv2.circle(img, (size // 2, size // 2), int(size * 0.45),
               agar_bgr or (agar, agar, agar), -1)
    for cx, cy in [(300, 300), (500, 320), (400, 500)]:
        cv2.circle(img, (cx, cy), radius, colony_bgr or (colony,) * 3, -1)
    return img


def test_polarity_estimated_per_dish_both_directions():
    """접시별 극성 추정이 양방향 모두 맞아야 한다.

    극성을 반대로 고르면 검출이 0 에 가까워진다(실측: 971.jpg 98 → 3). 그래서
    이 판정은 조용히 틀리면 안 되고, 노이즈가 없는 합성 이미지에서도 맞아야 한다 —
    흑백 카메라·과노출 클리핑·평탄한 배지에서 같은 조건이 생긴다.

    후보 대비를 합산하는 초기 구현이 바로 이 케이스(radius=90)에서 틀렸다.
    """
    import cv2 as _cv2

    from app.blob_detector import estimate_bright, plate_roi_with_scale

    for agar, colony, expect in ((60, 140, True), (180, 90, False)):
        for radius in (40, 90):
            img = _dish(agar=agar, colony=colony, radius=radius)
            gray = _cv2.GaussianBlur(
                _cv2.cvtColor(img, _cv2.COLOR_BGR2GRAY), (3, 3), 0)
            roi, _ = plate_roi_with_scale(gray, "petri")
            got = estimate_bright(gray, roi)
            assert got is expect, (
                f"한천 {agar} 콜로니 {colony} 반지름 {radius}: "
                f"{got} 이 나왔지만 {expect} 여야 함")


def test_uniform_image_declines_polarity_guess():
    """구조가 없으면 추정을 포기해야 한다 (None → 호출자가 양극성으로 되돌림)."""
    import cv2 as _cv2

    from app.blob_detector import estimate_bright, plate_roi_with_scale

    flat = np.full((400, 400, 3), 128, dtype=np.uint8)
    gray = _cv2.cvtColor(flat, _cv2.COLOR_BGR2GRAY)
    roi, _ = plate_roi_with_scale(gray, "petri")
    assert estimate_bright(gray, roi) is None


def test_finds_bright_colonies_on_dark_agar():
    circles = detect_blobs(_dish(agar=60, colony=140))
    assert len(circles) == 3


def test_finds_dark_colonies_on_bright_agar():
    """극성이 반대여도 찾아야 한다.

    기존 경로는 invert 플래그로 극성을 하나 고정해야 했고, 실측상 데이터셋마다
    극성이 반대여서 재현율이 무너졌다. 이 경로는 양극성을 모두 검출한다.
    """
    circles = detect_blobs(_dish(agar=180, colony=90))
    assert len(circles) == 3


def test_finds_colonies_much_larger_than_legacy_kernel():
    """콜로니 지름이 레거시 tophat_kernel(31px)보다 훨씬 커도 찾아야 한다.

    커널이 콜로니보다 작으면 내부 응답이 0이 되어 테두리만 남는 것이
    기존 경로의 주요 실패 원인이었다.
    """
    circles = detect_blobs(_dish(radius=90))  # 지름 180px ≫ 31px
    assert len(circles) == 3
    for _x, _y, r, _c in circles:
        assert r > 31 / 2, f"반지름 {r}이 레거시 커널 절반보다 작음"


def test_returns_x_y_radius_circularity_tuples():
    for x, y, r, circ in detect_blobs(_dish()):
        assert r > 0
        assert 0.0 <= circ <= 1.0


def test_uniform_plate_yields_no_colonies():
    """균일한 한천 평면에서는 아무것도 검출하지 않아야 한다(t-통계량 ≈ 0)."""
    img = np.full((800, 800, 3), 15, dtype=np.uint8)
    cv2.circle(img, (400, 400), 360, (120, 120, 120), -1)
    assert detect_blobs(img) == []


def test_thin_line_not_detected_as_colony():
    """얇고 긴 선(벽 주름·획 글씨)은 모양 게이트에서 탈락해야 한다."""
    img = np.full((800, 800, 3), 15, dtype=np.uint8)
    cv2.circle(img, (400, 400), 360, (60, 60, 60), -1)
    cv2.line(img, (250, 400), (550, 400), (150, 150, 150), 5)
    assert detect_blobs(img) == []


def test_monochrome_image_still_detects():
    """무채색 이미지에서는 색 게이트를 끄고 검출해야 한다.

    흑백 카메라 입력은 채도가 0이므로, 색 게이트를 무조건 적용하면 전멸한다.
    """
    img = _dish(agar=60, colony=140)  # 회색조 BGR — 채도 0
    hsv_sat = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)[..., 1]
    assert hsv_sat.max() == 0, "이 픽스처는 무채색이어야 한다"
    assert len(detect_blobs(img)) == 3


def test_min_t_is_monotone_in_detection_count():
    """t 하한을 올리면 검출 수가 늘어나지 않아야 한다(감도 슬라이더 방향성)."""
    img = _dish(agar=60, colony=100)
    loose = len(detect_blobs(img, min_t=4.0))
    tight = len(detect_blobs(img, min_t=60.0))
    assert tight <= loose


def test_dish_roi_finds_circle_regardless_of_polarity():
    """접시 ROI는 한천이 배경보다 밝든 어둡든 찾아야 한다."""
    for agar, bg in ((200, 20), (40, 220)):
        img = np.full((800, 800, 3), bg, dtype=np.uint8)
        cv2.circle(img, (400, 400), 340, (agar,) * 3, -1)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        mask, circle = dish_roi(gray)
        assert circle is not None, f"agar={agar} bg={bg}에서 접시를 못 찾음"
        cx, cy, r = circle
        assert abs(cx - 400) < 60 and abs(cy - 400) < 60
        assert mask[400, 400] == 255


def test_dish_roi_excludes_rim():
    """접시 테두리는 ROI에서 제외돼야 한다(반지름 수축)."""
    img = np.full((800, 800, 3), 20, dtype=np.uint8)
    cv2.circle(img, (400, 400), 340, (200, 200, 200), -1)
    mask, circle = dish_roi(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
    _cx, _cy, r = circle
    edge = int(r * 0.99)
    assert mask[400, 400 + edge] == 0, "테두리 근처가 ROI에 포함됨"


def test_dish_pick_region_shrinks_with_margin():
    img = _dish()
    wide = dish_pick_region(img, edge_margin=0)
    narrow = dish_pick_region(img, edge_margin=120)
    assert (narrow > 0).sum() < (wide > 0).sum()


def test_colonies_outside_dish_not_detected():
    """접시 밖(프레임·배경)의 둥근 반점은 검출되지 않아야 한다."""
    img = _dish()
    cv2.circle(img, (60, 60), 30, (200, 200, 200), -1)  # 접시 밖 밝은 점
    circles = detect_blobs(img)
    for x, y, _r, _c in circles:
        assert (x - 400) ** 2 + (y - 400) ** 2 < (800 * 0.45) ** 2


def test_empty_image_returns_empty():
    assert detect_blobs(np.zeros((0, 0, 3), dtype=np.uint8)) == []


def test_config_defaults_present():
    """기본값이 config에 있어야 한다(요청에서 override 가능)."""
    assert config.BLOB_MIN_T > 0
    assert config.BLOB_MIN_REL_SAT > 0
    assert 0 < config.BLOB_DISH_SHRINK <= 1.0


def _monochrome_dish() -> np.ndarray:
    """완전 무채색 접시 — 세 채널이 같으면 HSV 채도가 0 이다.

    실측: 이 이미지의 ROI 채도 표준편차는 0.0 으로 BLOB_MONO_SAT_STD(2.0)
    아래이고, 검출은 1개 나온다(빈 리스트가 아니라서 반환 형식 단정이 유효하다).
    """
    grey = np.full((600, 600, 3), 120, np.uint8)
    cv2.circle(grey, (300, 300), 40, (170, 170, 170), -1)
    return grey


def test_detect_blobs_reports_has_chroma_without_changing_return():
    """stats 를 주면 색 축 적용 여부를 알려준다. 반환 형식은 그대로여야 한다.

    무채색 이미지(흑백 카메라·합성)에서는 blob_detector 가 색 게이트를 조용히
    끄는데, 지금은 호출자가 그것을 알 수 없다. 반환값에 끼워 넣으면
    detector.detect 와의 호환이 깨지므로 out-파라미터로 받는다.
    """
    stats: dict = {}
    out = detect_blobs(_monochrome_dish(), stats=stats)
    assert isinstance(out, list)
    assert out, "이 합성 접시에서는 최소 1개가 검출돼야 한다"
    for item in out:
        assert len(item) == 4, "반환은 (x, y, radius, circularity) 4-튜플이어야 한다"
    assert stats["has_chroma"] is False


def test_detect_blobs_stats_is_optional():
    """stats 를 주지 않아도 기존과 똑같이 동작해야 한다."""
    assert detect_blobs(_monochrome_dish()) == detect_blobs(_monochrome_dish())


def test_detect_blobs_reports_has_chroma_true_on_colour_dish():
    """색이 있는 접시에서는 True 여야 한다 — 늘 False 를 넣는 구현을 막는다."""
    stats: dict = {}
    detect_blobs(_dish(colony_bgr=(60, 200, 90), agar_bgr=(200, 190, 160)),
                 stats=stats)
    assert stats["has_chroma"] is True
