import cv2
import numpy as np

from app.annotate import draw_colonies, draw_pick_targets, save_annotated


class _C:
    """테스트용 Colony 대역 (x, y, radius, pickable)."""

    def __init__(self, x, y, radius, pickable):
        self.x, self.y, self.radius, self.pickable = x, y, radius, pickable


def test_draw_colonies_does_not_mutate_input():
    img = np.full((50, 50, 3), 200, dtype=np.uint8)
    before = img.copy()
    out = draw_colonies(img, [(25.0, 25.0, 6.0)])
    # 원본 불변, 결과물엔 붉은 픽셀 존재
    assert np.array_equal(img, before)
    assert out.shape == img.shape
    assert (out[:, :, 2] == 255).any()


def _green_count(img):
    """초록(약 0,200,0) 픽셀 수."""
    return int(
        ((img[:, :, 0] < 60) & (img[:, :, 1] > 150) & (img[:, :, 2] < 60)).sum()
    )


def test_annotate_mode_all_draws_red_no_green():
    img = np.full((60, 60, 3), 200, dtype=np.uint8)
    cols = [_C(20, 20, 6, False), _C(40, 40, 6, True)]
    out = draw_pick_targets(img, cols, mode="all")
    assert (out[:, :, 2] == 255).any()   # 붉은색 존재
    assert _green_count(out) == 0        # all 모드엔 초록 없음


def test_annotate_mode_pick_draws_only_pickable_green():
    img = np.full((60, 60, 3), 200, dtype=np.uint8)
    out = draw_pick_targets(
        img, [_C(20, 20, 6, False), _C(40, 40, 6, True)], mode="pick"
    )
    assert _green_count(out) > 0         # pickable 1개 → 초록 존재
    # 아무도 pickable이 아니면 아무것도 안 그린다 (원본 그대로)
    none = draw_pick_targets(img, [_C(20, 20, 6, False)], mode="pick")
    assert np.array_equal(none, img)


def test_save_annotated_creates_file(tmp_path):
    img = np.full((40, 40, 3), 128, dtype=np.uint8)
    path = save_annotated(img, str(tmp_path), "result.jpg")
    assert path.is_file()
    reread = cv2.imread(str(path))
    assert reread.shape == (40, 40, 3)


def test_save_annotated_creates_missing_dir(tmp_path):
    target = tmp_path / "nested" / "out"
    img = np.full((10, 10, 3), 50, dtype=np.uint8)
    path = save_annotated(img, str(target), "x.jpg")
    assert path.is_file()
