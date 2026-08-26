"""다중 스케일 blob 검출기 — 콜로니처럼 생긴 것만 남긴다.

기존 `detector.detect`(top-hat + Otsu + watershed)가 실패한 이유를 라벨 40장
측정으로 규명한 뒤 다시 설계한 경로다. 측정 결과(정답 1,886개 기준):

    기존 top-hat 경로   정밀도  1.2%  재현율 23.8%   (네 그룹 모두 무작위 산포보다 나쁨)
    이 모듈            정밀도 90.0%  재현율 55.4%

기존 경로가 실패한 원인 세 가지:

1. **극성** — `DEFAULT_INVERT=True`(black-hat)는 어두운 콜로니를 가정한다. 실측은
   lower-resolution이 밝은 콜로니 100%, higher-resolution bright/dark가 어두운
   콜로니 94~98%, vague는 한 장 안에 혼재. 전역 고정 자체가 불가능하다.
   → 양극성 모두 검출하고 blob마다 판정한다.

2. **스케일** — `tophat_kernel=31`인데 콜로니 지름은 중앙값 57px, 최대 404px.
   커널이 콜로니보다 작으면 큰 콜로니 내부 응답이 0이 되고 테두리만 남아,
   watershed가 이미지당 2,000~3,000개 파편을 만든다.
   → 스케일 정규화 LoG의 scale-space 국소최대로 크기를 스스로 추정한다.

3. **ROI** — 8웰용 2×4 격자는 8웰 몰딩 plate 가정. 실제 샘플은 원형
   petri 접시 1개라 격자가 접시를 잘라냈다.
   → 접시 원을 HoughCircles로 직접 찾는다(밝기 극성 무관).

"콜로니처럼 생긴 것"의 판정은 서로 독립인 네 축이다:

    t-통계량      면적 가중 Welch t. 평면(균일한 한천)은 0 근처 → 탈락.
                 절대 대비로는 안 된다 — vague 그룹은 대비 2~3단계인데 지름이
                 200px여서, 평균의 표준오차(std/√N)를 쓰면 유의해진다.
    |Δ채도|       주변 고리 대비 채도차의 **절댓값**. 점자식 인쇄 잉크의 개별 점은
                 진짜 둥글어서 모양으로 못 걸러내지만, 색 차이가 0 근처다.
                 부호를 쓰면 안 된다 — 콜로니가 한천보다 채도가 낮은 접시도 있다.
    모양          원형도·solidity·종횡비 → 획 글씨·벽 주름·긁힘 탈락.
    위치          접시 원을 안쪽으로 수축 → 테두리 링·메니스커스 탈락.
"""
from __future__ import annotations

import math

import cv2
import numpy as np

from app import config


def dish_roi(gray: np.ndarray) -> tuple[np.ndarray, tuple[int, int, int] | None]:
    """원형 접시 내부 마스크(255=내부)와 (cx, cy, r).

    접시 경계는 강한 닫힌 원형 엣지이므로 HoughCircles로 원을 직접 찾는다.
    밝기 극성에 의존하지 않는다 — 한천이 프레임보다 어두운 데이터셋과 밝은
    데이터셋이 모두 존재하기 때문(실측: lower-res 한천 56 vs 프레임 밝음,
    higher-res 한천 115~145 vs 배경 어두움).
    """
    h, w = gray.shape
    blur = cv2.medianBlur(gray, 5)
    rmin = int(min(h, w) * config.BLOB_DISH_R_MIN_FRAC)
    rmax = int(min(h, w) * config.BLOB_DISH_R_MAX_FRAC)
    circles = cv2.HoughCircles(
        blur, cv2.HOUGH_GRADIENT, dp=1.5, minDist=min(h, w),
        param1=120, param2=40, minRadius=rmin, maxRadius=rmax,
    )
    best: tuple[int, int, int] | None = None
    if circles is not None:
        # 중앙에 가깝고 큰 원을 고른다.
        cand = sorted(
            circles[0],
            key=lambda c: math.hypot(c[0] - w / 2, c[1] - h / 2) - c[2] * 0.3,
        )
        cx, cy, r = cand[0]
        best = (int(cx), int(cy), int(r))

    if best is None:
        best = _roi_fallback(blur)

    mask = np.zeros(gray.shape, np.uint8)
    if best is None:
        mask[:] = 255
        return mask, None
    cx, cy, r = best
    # 접시 테두리·메니스커스·벽을 배제하려 반지름을 안쪽으로 수축한다.
    cv2.circle(mask, (cx, cy), max(1, int(r * config.BLOB_DISH_SHRINK)), 255, -1)
    return mask, best


def _roi_fallback(blur: np.ndarray) -> tuple[int, int, int] | None:
    """Hough가 실패하면 양극성 모두 시도해 가장 원에 가까운 큰 성분을 접시로 본다."""
    h, w = blur.shape
    _, bw = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    pick, pick_score = None, None
    for m in (bw, cv2.bitwise_not(bw)):
        m2 = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((31, 31), np.uint8))
        n, _lab, stats, cents = cv2.connectedComponentsWithStats(m2, 8)
        for i in range(1, n):
            area = stats[i, cv2.CC_STAT_AREA]
            if area < h * w * 0.05:
                continue
            bwid, bhei = stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT]
            fill = area / max(1, bwid * bhei)
            aspect = max(bwid, bhei) / max(1, min(bwid, bhei))
            # 원이면 fill≈π/4≈0.785, aspect≈1
            score = -abs(fill - 0.785) - abs(aspect - 1) + area / (h * w)
            if pick_score is None or score > pick_score:
                pick = (int(cents[i][0]), int(cents[i][1]),
                        int(math.sqrt(area / math.pi)))
                pick_score = score
    return pick


def plate_roi_with_scale(
    gray: np.ndarray, plate_type: str
) -> tuple[np.ndarray, float]:
    """ROI 마스크와 **크기 기준 길이**(작업 픽셀)를 함께 돌려준다.

    크기 기준은 접시 지름이다. 콜로니 크기를 "접시 지름 대비 비율"로 표현하면
    해상도·카메라·촬영 거리와 무관해진다 — petri 접시는 물리적 규격품이므로
    같은 비율이 항상 같은 물리 크기를 뜻한다. 작업 픽셀이나 원본 픽셀을 그대로
    노출하면 이미지마다 의미가 달라져 오퍼레이터가 쓸 수 없다.

    well8(사각 다웰)에는 접시 원이 없으므로 이미지 짧은 변을 기준으로 삼는다.
    """
    if plate_type == "well8":
        from app.well_plate import well_mask
        return well_mask(gray), float(min(gray.shape))
    mask, circle = dish_roi(gray)
    ref = float(2 * circle[2]) if circle else float(min(gray.shape))
    return mask, ref


def plate_roi(gray: np.ndarray, plate_type: str) -> np.ndarray:
    """플레이트 내부 ROI 마스크.

    "petri" → 접시 원을 찾아 안쪽으로 수축.
    "well8" → well_plate.well_mask 의 4×2 격자 (벽·프레임 제외).

    두 기하구조를 모두 지원해야 하는 이유: 이 프로젝트 하드웨어는 4×2 몰딩
    8웰 플레이트인데(tests/fixtures/agar_sample.jpg), sample/ 의 이미지는
    원형 petri 접시다. ROI를 원으로 강제하면 사각 플레이트의 모서리 웰이
    통째로 잘려나가고, 격자로 강제하면 둥근 접시가 8조각으로 잘린다.

    자동 판정은 두 방법 모두 실패해서 넣지 않았다. 호출자가 명시해야 한다.
      - bbox 채움율: 8웰 0.740 대 petri 0.875로 역전돼 판별력 없음
        (플레이트가 이미지 경계에서 잘리거나 배경과 연결되기 때문).
      - "양쪽 완주 후 검출 수 많은 쪽": 8웰 픽스처에서 petri ROI가 44개,
        well8 ROI가 31개로 사각 플레이트인데 petri를 골랐다.
    """
    if plate_type == "well8":
        from app.well_plate import well_mask  # 순환 import 방지용 지역 import
        return well_mask(gray)
    mask, _circle = dish_roi(gray)
    return mask


def dish_pick_region(
    img: np.ndarray,
    edge_margin: int = 0,
    work_size: int = config.BLOB_WORK_SIZE,
) -> np.ndarray:
    """피킹 안전 영역 마스크(255=안전), 원본 해상도.

    `detector.pick_region`은 2×4 웰 격자를 전제하는데 원형 petri 접시에는 맞지
    않는다. 여기서는 접시 원을 `edge_margin`만큼 더 안쪽으로 줄여 테두리 근처의
    반점·데브리가 피킹 대상이 되는 것을 막는다.
    """
    h, w = img.shape[:2]
    s = min(1.0, work_size / max(h, w))
    small = (cv2.resize(img, (max(1, int(w * s)), max(1, int(h * s))),
                        interpolation=cv2.INTER_AREA) if s < 1.0 else img)
    gray = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (3, 3), 0)
    _roi, circle = dish_roi(gray)

    mask = np.zeros((h, w), np.uint8)
    if circle is None:
        mask[:] = 255
        return mask
    cx, cy, r = circle
    inv = 1.0 / s if s > 0 else 1.0
    r_full = r * config.BLOB_DISH_SHRINK * inv - max(0, edge_margin)
    if r_full <= 0:
        return mask
    cv2.circle(mask, (int(cx * inv), int(cy * inv)), int(r_full), 255, -1)
    return mask


def log_candidates(
    gray: np.ndarray,
    roi: np.ndarray,
    bright: bool,
    r_min: float,
    r_max: float,
    n_scale: int,
    log_thresh: float,
    max_candidates: int,
) -> list[tuple[float, float, float]]:
    """스케일 정규화 LoG의 scale-space 국소최대 → (x, y, r) 후보.

    임계값을 낮게 두어 흐린 콜로니까지 후보로 올리고, 판정은 t-게이트에 맡긴다.
    큰 sigma는 이미지를 줄여 처리한다(옥타브 피라미드) — 그렇지 않으면 sigma 78에서
    469×469 가우시안 커널이 되어 수십 배 느려진다.
    """
    img = gray.astype(np.float32)
    if not bright:
        img = 255.0 - img
    sigmas = np.geomspace(r_min / math.sqrt(2), r_max / math.sqrt(2), n_scale)

    h, w = img.shape
    vol = np.empty((len(sigmas), h, w), np.float32)
    for i, s in enumerate(sigmas):
        f = max(1, int(s / config.BLOB_PYRAMID_SIGMA))
        if f > 1:
            small = cv2.resize(img, (max(8, w // f), max(8, h // f)),
                               interpolation=cv2.INTER_AREA)
            se = s / f
        else:
            small, se = img, s
        k = int(se * 6) | 1
        g = cv2.GaussianBlur(small, (k, k), se)
        resp = (-cv2.Laplacian(g, cv2.CV_32F, ksize=3)) * (se ** 2)
        vol[i] = (resp if f == 1
                  else cv2.resize(resp, (w, h), interpolation=cv2.INTER_LINEAR))

    # 공간 국소최대(스케일별) ∩ 스케일 방향 국소최대.
    # 팽창 커널은 RECT를 쓴다 — 분리 가능해 ELLIPSE보다 훨씬 빠르고,
    # 국소최대 억제 목적에는 커널 모양이 정확할 필요가 없다.
    dil = np.empty_like(vol)
    for i in range(len(sigmas)):
        rad = max(1, int(sigmas[i] * math.sqrt(2) * 0.7))
        dil[i] = cv2.dilate(vol[i], np.ones((rad * 2 + 1,) * 2, np.uint8))
    up, dn = np.roll(vol, 1, 0), np.roll(vol, -1, 0)
    up[0] = -np.inf
    dn[-1] = -np.inf

    cand = (vol >= dil - 1e-6) & (vol >= up) & (vol >= dn) & (vol > log_thresh)
    cand &= (roi > 0)[None, :, :]

    si, yi, xi = np.nonzero(cand)
    if len(si) == 0:
        return []
    order = np.argsort(-vol[si, yi, xi])[:max_candidates]
    return [
        (float(xi[i]), float(yi[i]), float(sigmas[si[i]] * math.sqrt(2)))
        for i in order
    ]


def threshold_candidates(
    gray: np.ndarray,
    roi: np.ndarray,
    bright: bool,
    r_min: float,
    r_max: float,
    n_levels: int,
    max_candidates: int,
) -> list[tuple[float, float, float]]:
    """여러 이진화 레벨의 연결성분 → (x, y, r) 후보. LoG 후보와 같은 형식.

    LoG 와 **성격이 반대**다. LoG 는 봉우리면 무엇이든 올려 커버리지가 높지만
    (93.4%) 후보가 지저분하다. 이쪽은 "연결된 덩어리"라는 조건을 이미 만족한
    것만 올려 커버리지는 낮지만(89.7%) 순도가 훨씬 높다.

    실측(39장) — 둘을 같은 게이트에 태웠을 때 정밀도 구간별 재현율:

        정밀도 ~98%   LoG 23.0%   이진화 **58.5%**   ← 이진화 압승
        정밀도 ~94%   LoG 59.0%   이진화 **67.3%**
        정밀도 ~88%   LoG 68.5%   이진화 68.2%       ← 교차점
        정밀도 ~81%   LoG **72.1%**  이진화 69.3%
        정밀도 ~65%   LoG **74.8%**  이진화 71.3%

    높은 정밀도를 원할수록 게이트를 조여야 하고, 그때는 후보가 깨끗한 쪽이
    유리하다. 반대로 재현율을 짜낼 때는 커버리지가 높은 쪽이 이긴다.

    **레벨을 늘려도 커버리지 천장은 안 오른다** — 12/24/36 레벨에서 재현율
    67.9/70.8/71.3%. 흐린 콜로니는 어떤 절대 임계값에서도 배경과 갈라지지
    않는다는 원리적 한계다(vague 그룹 커버리지 74%, LoG 는 97%).

    백분위로 레벨을 잡는 이유: 전역 고정값을 쓰면 접시마다 밝기가 달라 대부분의
    레벨이 무의미해진다.
    """
    g = gray if bright else (255 - gray)
    inside = g[roi > 0]
    if inside.size < 100:
        return []
    lo, hi = np.percentile(inside, [5, 95])
    if not hi > lo:
        return []
    k3 = np.ones((3, 3), np.uint8)
    out: list[tuple[float, float, float]] = []
    seen: set[tuple[int, int, int]] = set()
    for t in np.linspace(float(lo), float(hi), n_levels):
        _, m = cv2.threshold(g, float(t), 255, cv2.THRESH_BINARY)
        m = cv2.morphologyEx(cv2.bitwise_and(m, roi), cv2.MORPH_OPEN, k3)
        n, _lab, stats, cents = cv2.connectedComponentsWithStats(m, 8)
        for i in range(1, n):
            a = stats[i, cv2.CC_STAT_AREA]
            if a < 6:
                continue
            r = math.sqrt(a / math.pi)
            if r < r_min or r > r_max:
                continue
            x, y = float(cents[i][0]), float(cents[i][1])
            # 같은 성분이 여러 레벨에서 반복 나온다. 격자로 거칠게 중복 제거 —
            # 촘촘하게 하면 중복이 남아 게이트 비용만 늘어난다.
            key = (int(x / 3), int(y / 3), int(r / 3))
            if key in seen:
                continue
            seen.add(key)
            out.append((x, y, r))
            if len(out) >= max_candidates:
                return out
    return out


def merge_candidates(
    *groups: list[tuple[float, float, float]],
) -> list[tuple[float, float, float]]:
    """여러 후보 집합을 합치고 같은 자리를 하나로 줄인다."""
    seen: set[tuple[int, int, int]] = set()
    out: list[tuple[float, float, float]] = []
    for g in groups:
        for x, y, r in g:
            key = (int(x / 3), int(y / 3), int(r / 3))
            if key in seen:
                continue
            seen.add(key)
            out.append((x, y, r))
    return out


def estimate_bright(gray: np.ndarray, roi: np.ndarray) -> bool | None:
    """접시 하나의 콜로니 극성을 추정한다. True = 콜로니가 한천보다 밝다.

    판단이 애매하면 None (호출자가 양극성으로 되돌린다).

    **왜 접시별로 하는가.** 극성은 데이터셋마다 반대라 전역 상수로 고정할 수
    없다(실측: lower-resolution 은 밝은 콜로니, 나머지 세 그룹은 어두운 콜로니).
    그래서 기존 구현은 양극성을 모두 검출해 병합했는데, 그러면 **틀린 극성 분기가
    기여 없이 오검출만 추가한다.** 접시 단위로 한쪽을 고르면 그 낭비가 사라진다.

    **판정은 접시 단위로 가능하다.** 개별 콜로니의 극성은 섞일 수 있어도(vague
    그룹은 28%가 반대 극성) 접시 전체로 집계하면 부호가 일관된다.

    **방법: 픽셀 편차 질량.** ROI 안에서 중앙값을 한천으로 보고, 그보다 밝은
    픽셀들의 편차 총량과 어두운 픽셀들의 편차 총량을 비교한다. 콜로니는 소수라도
    편차 총량으로는 드러난다.

    후보 위치의 대비를 합산하는 방식을 먼저 썼다가 **기각했다.** 실제 39장에서는
    39/39 였지만 노이즈가 없는 이미지(합성·흑백 카메라·과노출 클리핑)에서 틀렸다 —
    배경 산포가 노이즈 하한까지 내려가 정규화 대비가 폭발하고, 합산이라 한 후보가
    전체를 지배한다. 후보당 기여를 클램프해도 고쳐지지 않았다(실측: 두 방식 모두
    42/43, 픽셀 질량은 **43/43**). 극성을 반대로 고르면 검출이 0 에 가까워지므로
    (실측: 971.jpg 98 → 3) 이 실패 모드는 무시할 수 없다.

    픽셀 질량은 후보를 쓰지 않아 비용이 사실상 0이고, 고른 극성 쪽 후보만 생성하면
    되므로 양극성 병합보다 **오히려 빠르다**.

    실측 점수 분포: 어두운 콜로니 접시 −0.51~−0.63, 밝은 콜로니 접시 +0.17~+0.48.
    인쇄 글씨가 어두워 밝은 콜로니를 뒤집을까 우려했으나 그렇지 않았다 — 글씨가
    있는 lower-resolution 접시도 전부 양수다.
    """
    v = gray[roi > 0].astype(np.float32)
    if v.size < 100:
        return None
    m = float(np.median(v))          # 한천 = 최다 픽셀
    up = float(np.sum(v[v > m] - m))
    down = float(np.sum(m - v[v < m]))
    total = up + down
    if total <= 0:
        return None
    # 한쪽으로 충분히 기울지 않으면 판정을 포기한다. 실측 최소 마진이 0.166
    # 이므로 0.05 는 충분히 아래이면서 진짜 애매한 이미지를 걸러낸다.
    if abs(up - down) / total < config.BLOB_POLARITY_MIN_MARGIN:
        return None
    return up > down


def colony_gate(
    gray: np.ndarray,
    sat: np.ndarray | None,
    roi: np.ndarray,
    cands: list[tuple[float, float, float]],
    bright: bool,
    min_t: float,
    min_rel_sat: float,
    min_circularity: float,
    min_solidity: float,
    max_aspect: float,
    min_fill: float,
    min_radius: float,
    max_radius: float,
    min_roundness: float = 0.0,
    colour_credit: float = 1.0,
    limit_contour: float = 0.0,
    split_area_ratio: float = 2.0,
    watershed_split: bool = False,
    ink_sigma: float = 0.0,
    contour_levels: int = 1,
    contour_span: float = 0.4,
    radius_mode: str = "contour",
    radius_scale: float = 1.0,
    radius_alpha: float = 0.0,
    inner_frac: float = 0.65,
    outer_lo: float = 1.4,
    outer_hi: float = 2.1,
) -> list[tuple[float, float, float, float]]:
    """콜로니처럼 생긴 후보만 (x, y, radius, circularity)로 반환."""
    h, w = gray.shape
    f = gray.astype(np.float32)
    binm_kernel = np.ones((3, 3), np.uint8)
    kept: list[tuple[float, float, float, float]] = []
    for x, y, r in cands:
        r = max(2.0, r)
        pad = int(r * 2.2) + 2
        x0, y0 = max(0, int(x - pad)), max(0, int(y - pad))
        x1, y1 = min(w, int(x + pad) + 1), min(h, int(y + pad) + 1)
        patch = f[y0:y1, x0:x1]
        if patch.size < 16:
            continue
        pr = roi[y0:y1, x0:x1]
        cx, cy = x - x0, y - y0
        yy, xx = np.mgrid[0:patch.shape[0], 0:patch.shape[1]]
        d = np.hypot(xx - cx, yy - cy)

        # t-통계량 표본 영역. inner 가 넓으면 표본이 늘어 t 가 커지지만 콜로니
        # 가장자리(배경과 섞이는 구간)까지 들어와 대비가 줄어든다. outer 가
        # 가까우면 콜로니 헤일로가 배경 추정을 오염시키고, 멀면 조명 그라데이션을
        # 배경으로 잡는다. 셋 다 이 프로젝트에서 튜닝된 적이 없다.
        inner = (d <= r * inner_frac) & (pr > 0)
        outer = (d >= r * outer_lo) & (d <= r * outer_hi) & (pr > 0)

        # 인쇄 글씨(잉크) 픽셀을 통계에서 제외한다.
        #
        # 실측상 놓친 839개 중 297개(35%)가 인쇄 글씨에 걸친 콜로니였다 —
        # 가장 큰 단일 원인이다. 점자식 잉크는 한천보다도 콜로니보다도 훨씬
        # 어두워서, 내부·주변 고리 양쪽에 섞이면 산포를 키워 t-통계량을 떨어뜨리고
        # 지역 임계값 윤곽까지 깨뜨린다. 중앙값/MAD가 부분적으로 강건하지만
        # 잉크 비율이 몇 %를 넘으면 버티지 못한다.
        #
        # 잉크는 패치 밝기 분포에서 아래쪽 극단이므로, 중앙값에서 MAD의
        # ink_sigma 배 이상 어두운 픽셀을 잉크로 보고 뺀다. 콜로니가 어두운
        # 접시(bright/dark 그룹)에서도 콜로니는 이 문턱보다 훨씬 밝다.
        ink = None
        if ink_sigma > 0.0:
            valid = pr > 0
            if valid.sum() >= 20:
                pm = float(np.median(patch[valid]))
                pmad = 1.4826 * float(np.median(np.abs(patch[valid] - pm)))
                pmad = max(pmad, config.BLOB_NOISE_FLOOR)
                cand_ink = patch < (pm - ink_sigma * pmad)
                # 잉크가 영역을 다 덮으면 제외해봐야 표본이 남지 않는다.
                if (cand_ink[inner].mean() < 0.7
                        and cand_ink[outer].mean() < 0.7):
                    ink = cand_ink
                    inner = inner & ~ink
                    outer = outer & ~ink

        # 통계에서 빼는 것만으로는 부족하다. 모양 판정에 쓰는 지역 이진화에서도
        # 잉크를 없애야 한다 — 밝은 콜로니에서는 잉크가 임계값 아래라 윤곽에
        # 구멍을 내고, 어두운 콜로니에서는 잉크가 콜로니와 한 덩어리로 붙는다.
        # 그래서 이진화 **전에** 잉크 픽셀을 주변 중앙값으로 메운다.
        if ink is not None and ink.any():
            patch = patch.copy()
            fill = float(np.median(patch[outer])) if outer.any() else 0.0
            patch[ink] = fill

        n_in, n_out = int(inner.sum()), int(outer.sum())
        if n_in < 5 or n_out < 10:
            continue

        vi, vo = patch[inner], patch[outer]
        # 면적 가중 t-통계량. 넓고 흐린 콜로니(대비 2~3단계, 지름 200px)를
        # 살리려면 절대 대비가 아니라 평균의 표준오차로 나눠야 한다.
        #
        # 중심·배경 추정에 중앙값/MAD를 쓴다(로버스트). 평균을 쓰면 주변 고리에
        # 섞인 소수의 밝은 픽셀(긁힘·메니스커스·응결선·글씨 획)이 배경 추정을
        # 흔들어, 균일한 한천 위에 거짓 콜로니가 생긴다.
        #
        # 산포에는 양자화 노이즈 하한을 둔다. 완전히 균일한 영역(과노출 클리핑,
        # 합성 이미지)은 산포가 0이라 t가 폭발한다. 8비트 센서는 최소
        # ±0.5 LSB 양자화 노이즈를 가지므로 그것을 하한으로 삼는다.
        mi, mo = float(np.median(vi)), float(np.median(vo))
        diff = (mi - mo) if bright else (mo - mi)
        floor = config.BLOB_NOISE_FLOOR
        s_in = max(1.4826 * float(np.median(np.abs(vi - mi))), floor)
        s_out = max(1.4826 * float(np.median(np.abs(vo - mo))), floor)
        se = math.sqrt(s_in * s_in / n_in + s_out * s_out / n_out)
        t_stat = diff / se
        # 색이 t를 보완할 수 있으므로 t 단독 탈락은 아래 합산 판정에서 처리한다.
        # 단 명백히 반대 극성인 후보는 여기서 끊는다(반대 극성 루프가 잡는다).
        if t_stat <= 0:
            continue

        # 색 신호. 무채색 이미지(흑백 카메라, 합성 이미지)에서는 sat이 None이라
        # 색을 쓸 수 없으므로 t 단독으로 판정한다.
        rel_sat = 0.0
        has_colour = False
        if sat is not None:
            sp = sat[y0:y1, x0:x1]
            si_, so_ = sp[inner], sp[outer]
            if si_.size and so_.size:
                rel_sat = abs(float(np.median(si_)) - float(np.median(so_)))
                has_colour = True

        # 색 게이트는 그대로 유지한다 — 점자식 인쇄 잉크·데브리는 주변과 색차가
        # 0 근처라 여기서 걸러진다.
        if has_colour and min_rel_sat > 0.0 and rel_sat < min_rel_sat:
            continue

        # 그 위에, 색이 문턱을 크게 넘으면 t 요구치를 그만큼 할인한다.
        #
        # AND 사슬은 각 축에서 조금씩 잃어 손실이 곱으로 누적된다. 반면 측정상
        # 색거리는 대비가 충분한 구간에서 TP/FP를 강하게 갈랐다(t≥35에서
        # TP 18~26 대 FP 5~6). 즉 색이 뚜렷하면 t가 다소 낮아도 콜로니다.
        # BLOB_COLOUR_CREDIT_MAX=1.0이면 할인이 없어 기존 AND 동작과 같다.
        need = min_t
        if has_colour and min_rel_sat > 0.0 and colour_credit > 1.0:
            credit = min(rel_sat / min_rel_sat, colour_credit)
            need = min_t / max(1.0, credit)
        if t_stat < need:
            continue

        # 지역 임계값(중심과 주변의 중간)으로 blob 윤곽을 뽑아 모양을 검사한다.
        def _pick_contour(mask):
            cs, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                     cv2.CHAIN_APPROX_SIMPLE)
            for c in cs:
                if cv2.pointPolygonTest(c, (float(cx), float(cy)), False) >= 0:
                    return c
            return None

        # 모양 판정을 여러 이진화 레벨에서 시도한다.
        #
        # 모양 게이트가 판정하는 윤곽은 **임계값 하나**로 뽑은 것이다. 그 값이
        # 어긋나면 진짜 콜로니가 이상한 모양으로 측정돼 탈락한다 — 게이트가
        # 틀린 것이 아니라 판정 대상이 불안정한 것이다. 실측(971.jpg): 문턱을
        # 다 열어도 모양 게이트에서 21개(16%)가 죽었다.
        #
        # 여러 레벨을 훑고 **하나라도 통과하면 인정**한다. 진짜 콜로니는 어느
        # 레벨에선 둥글게 잡히고, 획 글씨·긁힘은 어느 레벨에서도 둥글지 않다.
        # OpenCFU 의 score-map(여러 threshold 에서 원형 영역을 누적)과 같은
        # 발상인데, 후보 생성이 아니라 모양 판정 단계에 적용한다 — 계측상 후보
        # 생성은 이미 정답의 93%를 덮고 있어 손댈 이유가 없다.
        #
        # levels=1 이면 alpha=0.5 하나뿐이고 (mi+mo)/2 라 기존 동작과 동일하다.
        if contour_levels <= 1:
            alphas = (0.5,)
        else:
            alphas = np.linspace(0.5 - contour_span / 2.0,
                                 0.5 + contour_span / 2.0, contour_levels)

        got = None
        for _alpha in alphas:
            got = _judge_level(
                mo + float(_alpha) * (mi - mo), patch, pr, binm_kernel,
                bright, d, r, cx, cy, x0, y0, _pick_contour,
                min_circularity=min_circularity, min_solidity=min_solidity,
                max_aspect=max_aspect, min_fill=min_fill,
                min_roundness=min_roundness, min_radius=min_radius,
                max_radius=max_radius, limit_contour=limit_contour,
                split_area_ratio=split_area_ratio,
                watershed_split=watershed_split,
                size_level=(mo + radius_alpha * (mi - mo)
                            if radius_alpha > 0.0 else None),
            )
            if got is not None:
                break
        if got is None:
            continue

        # 반지름 보정.
        #
        # 윤곽 면적 기반 반지름은 정답 지름의 0.73배로 계통 과소추정된다
        # (임계값이 (mi+mo)/2 라 사실상 FWHM 을 잰다). LoG 스케일도 0.71배로
        # 거의 같아서 어느 한쪽이 낫지 않다 — 오차 중앙값 0.29 대 0.30.
        #
        # 그러나 **꼬리는 다르다.** 하위 10% 지점에서 윤곽 0.30, LoG 0.15 다.
        # 한 방식이 무너질 때(콜로니의 밝은 심부만 잡히거나 스케일 선택이
        # 어긋날 때) 다른 방식이 받쳐주므로 최대값을 쓰면 파국적 과소추정이
        # 줄어든다. 그것이 "큰 콜로니에 점만 한 마커"와 NMS 중복의 원인이었다.
        if radius_mode == "max":
            gx, gy, gr, gc = got
            got = (gx, gy, max(gr, r), gc)
        if radius_scale != 1.0:
            gx, gy, gr, gc = got
            got = (gx, gy, gr * radius_scale, gc)
        kept.append(got)
    return kept


def _judge_level(
    lvl: float,
    patch: np.ndarray,
    pr: np.ndarray,
    binm_kernel: np.ndarray,
    bright: bool,
    d: np.ndarray,
    r: float,
    cx: float,
    cy: float,
    x0: int,
    y0: int,
    _pick_contour,
    *,
    min_circularity: float,
    min_solidity: float,
    max_aspect: float,
    min_fill: float,
    min_roundness: float,
    min_radius: float,
    max_radius: float,
    limit_contour: float,
    split_area_ratio: float,
    watershed_split: bool,
    size_level: float | None = None,
) -> tuple[float, float, float, float] | None:
    """이진화 레벨 하나에서 윤곽을 뽑아 모양 게이트를 통과하면 결과를 반환.

    통과하지 못하면 None. 호출부가 여러 레벨을 훑으며 하나라도 통과하는지 본다.

    `size_level` 이 주어지면 **반지름만** 그 레벨의 윤곽에서 다시 잰다. 모양
    판정은 `lvl`(검증된 반값 레벨) 그대로 유지한다.

    왜 반지름만 따로 재는가: 반값 레벨은 콜로니의 **반높이 지점**을 잡으므로
    외곽보다 안쪽이다. 실측상 지름이 정답의 0.73배로 계통 과소추정됐고, 눈으로
    확인해도 검출 원이 콜로니 안쪽에 들어가 있다. 배경에 가까운 레벨에서 재면
    외곽을 직접 찾으므로 콜로니마다 프로파일에 맞춰 적응한다 — 일괄 곱셈 보정과
    달리 특정 라벨 관행에 값을 고정하지 않는다.

    모양 판정을 낮은 레벨로 옮기지 않는 이유: 낮은 레벨은 이웃 콜로니·한천
    텍스처와 붙기 쉬워 모양이 망가진다. 실측상 여러 레벨에서 모양을 판정하는
    시도는 기각됐다(감도 낮추기에 지배).
    """
    binm = ((patch >= lvl) if bright else (patch <= lvl)).astype(np.uint8) * 255
    binm[pr == 0] = 0
    binm = cv2.morphologyEx(binm, cv2.MORPH_OPEN, binm_kernel)

    pick = _pick_contour(binm)
    if pick is None:
        return None  # 중심을 품은 윤곽이 없으면 이 후보의 blob이 아니다

    # 붙은 콜로니 분리 — 거리변환 watershed 로 콜로니 사이의 실제 골짜기를
    # 따라 자른다.
    #
    # 원반 클리핑(limit_contour)과 다른 점: 원을 강제로 씌우지 않으므로 잘린
    # 조각이 여전히 자기 모양을 유지하고, 모양 게이트가 그대로 작동한다.
    # 원반 클리핑은 모든 후보를 둥글게 만들어 게이트를 무력화시켰다(실측
    # 정밀도 90.1→48.9%). 그래서 그 방식은 기각됐다.
    #
    # 시각 확인: 밀집 접시에서 감도를 50→75로 올려도 검출이 248→252로 거의
    # 변하지 않았다 — 대비 문제가 아니라 분할 문제라는 뜻이다. 놓친 것은
    # 일관되게 뭉친 군집이었고 고립된 콜로니는 잘 잡혔다.
    if watershed_split and cv2.contourArea(pick) > math.pi * r * r * split_area_ratio:
        comp = np.zeros(binm.shape, np.uint8)
        cv2.drawContours(comp, [pick], -1, 255, -1)
        dist = cv2.distanceTransform(comp, cv2.DIST_L2, 5)
        # 씨앗 간 최소 간격을 후보 반지름에 맞춘다 — 콜로니 하나에 씨앗
        # 하나가 되도록.
        k = max(3, int(r * 0.8) | 1)
        peaks = ((dist >= cv2.dilate(dist, np.ones((k, k), np.uint8)) - 1e-6)
                 & (dist >= r * 0.35)).astype(np.uint8)
        n_seed, seeds = cv2.connectedComponents(peaks)
        if n_seed > 2:  # 씨앗이 2개 이상이면 실제로 붙은 덩어리다
            markers = seeds + 1
            markers[(comp > 0) & (peaks == 0)] = 0
            markers[comp == 0] = 1
            bgr = cv2.cvtColor(
                np.clip(patch, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)
            markers = cv2.watershed(bgr, markers.astype(np.int32))
            lbl = markers[int(round(cy)), int(round(cx))]
            if lbl > 1:
                part = (markers == lbl).astype(np.uint8) * 255
                got = _pick_contour(part)
                if got is not None and cv2.contourArea(got) >= 6:
                    pick = got

    # (기각된 대안) 원반 클리핑 — **병합된 경우에만** 후보 주변 원반으로 잘라 재평가.
    #
    # 붙은 콜로니는 지역 이진화에서 하나의 큰 연결 성분이 되고, 그 성분이
    # 길쭉해서 종횡비·원형도 게이트에 걸려 양쪽 후보가 모두 탈락한다.
    # 실측상 놓친 839개 중 258개(31%)가 서로 겹치는 라벨 영역이었다.
    #
    # 단 무조건 원반으로 자르면 안 된다 — 모든 후보가 둥근 윤곽을 갖게 되어
    # 모양 게이트가 무력화되고 텍스처 노이즈까지 통과한다(실측: 재현율
    # 51.9%→68.8%인데 정밀도 90.1%→48.9%). 그래서 자연 윤곽 면적이 후보
    # 기대 면적의 split_area_ratio 배를 넘을 때만 병합으로 보고 자른다.
    if limit_contour > 0.0:
        expect = math.pi * r * r
        if cv2.contourArea(pick) > expect * split_area_ratio:
            disc = (d <= r * limit_contour).astype(np.uint8) * 255
            clipped = _pick_contour(cv2.bitwise_and(binm, disc))
            if clipped is not None:
                pick = clipped

    area = cv2.contourArea(pick)
    per = cv2.arcLength(pick, True)
    if area < 6 or per <= 0:
        return None
    circ = 4.0 * math.pi * area / (per * per)
    # 면적 기반 둥글기 = 면적 / 최소외접원 면적. 둘레 기반 원형도(4πA/P²)는
    # 경계 거칠기에 극도로 민감해서, 가장자리가 부슬부슬한(방사형 균사)
    # 콜로니가 둥글어도 값이 급락한다. 측정상 원형도 게이트가 진짜 콜로니
    # 352개(18.7%)를 버렸고, vague 그룹은 원형도 중앙값 0.454 대
    # 면적기반 0.538로 후자가 덜 깎인다.
    (_ex, _ey), r_enc = cv2.minEnclosingCircle(pick)
    roundness = area / (math.pi * r_enc * r_enc) if r_enc > 0 else 0.0
    hull_a = cv2.contourArea(cv2.convexHull(pick))
    solidity = area / hull_a if hull_a > 0 else 0.0
    _bx, _by, bwid, bhei = cv2.boundingRect(pick)
    aspect = max(bwid, bhei) / max(1, min(bwid, bhei))
    fill = area / max(1, bwid * bhei)
    # 얇고 긴 획 글씨·벽 주름·긁힘은 여기서 탈락한다.
    if (circ < min_circularity or solidity < min_solidity
            or aspect > max_aspect or fill < min_fill
            or roundness < min_roundness):
        return None

    r_fit = math.sqrt(area / math.pi)
    if r_fit < min_radius or (max_radius > 0 and r_fit > max_radius):
        return None

    m = cv2.moments(pick)
    if m["m00"] <= 0:
        return None

    # 반지름을 배경에 가까운 레벨에서 다시 잰다 (모양 판정은 위에서 이미 끝났다).
    # 실패하거나 더 작게 나오면 원래 값을 쓴다 — 이 단계는 과소추정을 고치려는
    # 것이므로 값을 줄이는 방향으로는 쓰지 않는다.
    if size_level is not None:
        sm = ((patch >= size_level) if bright
              else (patch <= size_level)).astype(np.uint8) * 255
        sm[pr == 0] = 0
        sm = cv2.morphologyEx(sm, cv2.MORPH_OPEN, binm_kernel)
        big = _pick_contour(sm)
        if big is not None:
            a2 = cv2.contourArea(big)
            # 이웃과 붙어 덩어리가 되면 면적이 폭발한다. 후보 기대 면적의
            # split_area_ratio 배를 넘으면 병합으로 보고 버린다.
            if 0 < a2 <= math.pi * r * r * split_area_ratio * 2.0:
                r2 = math.sqrt(a2 / math.pi)
                r_fit = max(r_fit, r2)

    return (m["m10"] / m["m00"] + x0, m["m01"] / m["m00"] + y0,
            r_fit, min(circ, 1.0))


def detect_blobs(
    img: np.ndarray,
    adaptive_scale: bool = config.BLOB_ADAPTIVE_SCALE,
    min_t: float = config.BLOB_MIN_T,
    min_rel_sat: float = config.BLOB_MIN_REL_SAT,
    min_circularity: float = config.BLOB_MIN_CIRCULARITY,
    min_solidity: float = config.BLOB_MIN_SOLIDITY,
    max_aspect: float = config.BLOB_MAX_ASPECT,
    min_fill: float = config.BLOB_MIN_FILL,
    min_roundness: float = config.BLOB_MIN_ROUNDNESS,
    min_radius: float = config.BLOB_MIN_RADIUS,
    max_radius: float = config.BLOB_MAX_RADIUS,
    min_diam_frac: float = config.BLOB_MIN_DIAM_FRAC,
    max_diam_frac: float = config.BLOB_MAX_DIAM_FRAC,
    colour_credit: float = config.BLOB_COLOUR_CREDIT_MAX,
    limit_contour: float = config.BLOB_LIMIT_CONTOUR,
    split_area_ratio: float = config.BLOB_SPLIT_AREA_RATIO,
    watershed_split: bool = config.BLOB_WATERSHED_SPLIT,
    ink_sigma: float = config.BLOB_INK_SIGMA,
    contour_levels: int = config.BLOB_CONTOUR_LEVELS,
    contour_span: float = config.BLOB_CONTOUR_SPAN,
    candidate_source: str = config.BLOB_CANDIDATE_SOURCE,
    threshold_levels: int = config.BLOB_THRESHOLD_LEVELS,
    radius_mode: str = config.BLOB_RADIUS_MODE,
    radius_scale: float = config.BLOB_RADIUS_SCALE,
    radius_alpha: float = config.BLOB_RADIUS_ALPHA,
    inner_frac: float = config.BLOB_INNER_FRAC,
    outer_lo: float = config.BLOB_OUTER_LO,
    outer_hi: float = config.BLOB_OUTER_HI,
    force_bright: bool | None = None,
    auto_polarity: bool = config.BLOB_AUTO_POLARITY,
    work_size: int = config.BLOB_WORK_SIZE,
    # None이면 work_size에 비례해 자동 산출한다 (아래 설명 참조).
    r_min: float | None = None,
    r_max: float | None = None,
    n_scale: int = config.BLOB_N_SCALE,
    log_thresh: float = config.BLOB_LOG_THRESH,
    plate_type: str = "petri",
    # 호출자가 dict 를 주면 검출 중 알아낸 사실을 채워 준다. 반환값에 끼워 넣지
    # 않는 이유는 detector.detect 와 형식이 같아야 하기 때문이다(모듈 docstring).
    stats: dict | None = None,
) -> list[tuple[float, float, float, float]]:
    """콜로니를 검출해 원본 좌표계의 (x, y, radius, circularity) 리스트를 반환.

    `detector.detect`와 반환 형식이 같아 scoring/annotate에 그대로 연결된다.
    반지름·좌표는 처리 해상도에서 원본 스케일로 되돌려 준다.

    adaptive_scale=True면 1차 검출로 콜로니 크기를 재고, 작업 픽셀 기준 콜로니
    지름이 목표 대역에 들도록 해상도를 조정해 재검출한다. t-통계량은 면적 가중이라
    콜로니당 픽셀 수가 적으면 원리적으로 작아진다 — 실측상 bright 그룹 콜로니는
    1024에서 지름 10.8px(내부 픽셀 38개)뿐이어서 대비가 -36.7로 충분한데도
    t가 문턱을 못 넘었다. 해상도를 올리면 픽셀이 늘어 표준오차가 줄고 t가 커진다.

    단 해상도를 올릴 때 r_min/r_max를 함께 키워 **물리적 크기 창을 고정**해야
    한다. 그러지 않으면 콜로니보다 작은 한천 텍스처까지 검출 대상이 되어
    정밀도가 무너진다(실측: 크기창 미고정 시 정밀도 90.5%→47.9%, 고정 시 67.5%).
    """
    h, w = img.shape[:2]
    if h == 0 or w == 0:
        return []

    # LoG 스케일 탐색 범위를 work_size에 비례시킨다.
    #
    # r_min/r_max 는 **작업 픽셀** 단위라, work_size 만 올리고 이 값을 그대로 두면
    # 검출하는 **물리적** 크기 범위가 함께 작아진다 — 콜로니보다 작은 한천 텍스처가
    # 새로 검출 대상이 되어 정밀도가 무너진다(실측: 1536에서 정밀도 90.1→47.3%).
    # 크기 창을 고정하면 같은 1536에서 67.5%가 되고 bright 조건은 F1 64.7→68.0으로
    # 오른다. 즉 work_size 는 처리 해상도만 바꿔야 하고 무엇을 콜로니로 볼지는
    # 바꾸면 안 된다.
    _k = work_size / float(config.BLOB_WORK_SIZE)
    if r_min is None:
        r_min = config.BLOB_R_MIN * _k
    if r_max is None:
        r_max = config.BLOB_R_MAX * _k

    if adaptive_scale:
        probe = detect_blobs(
            img, adaptive_scale=False, min_t=min_t, min_rel_sat=min_rel_sat,
            min_circularity=min_circularity, min_solidity=min_solidity,
            max_aspect=max_aspect, min_fill=min_fill,
            min_roundness=min_roundness, min_radius=min_radius,
            max_radius=max_radius, min_diam_frac=min_diam_frac,
            max_diam_frac=max_diam_frac, colour_credit=colour_credit,
            force_bright=force_bright,
            work_size=work_size, r_min=r_min,
            r_max=r_max, n_scale=n_scale, log_thresh=log_thresh,
            plate_type=plate_type, stats=stats,
        )
        if len(probe) >= config.BLOB_SCALE_PROBE_MIN:
            s0 = min(1.0, work_size / max(h, w))
            med_d = 2.0 * float(np.median([r for _x, _y, r, _c in probe])) * s0
            if med_d > 0:
                k = config.BLOB_SCALE_TARGET_DIAM / med_d
                k = min(max(k, 1.0), config.BLOB_SCALE_MAX_UPSCALE)
                if k > 1.05:
                    # 물리적 크기 창을 고정한 채 해상도만 올려 재검출한다.
                    # min/max_diam_frac 는 접시 지름 대비 비율이라 해상도가
                    # 바뀌어도 그대로 유효하다(작업 픽셀 단위인 radius만 배율 적용).
                    return detect_blobs(
                        img, adaptive_scale=False, min_t=min_t,
                        min_rel_sat=min_rel_sat,
                        min_circularity=min_circularity,
                        min_solidity=min_solidity, max_aspect=max_aspect,
                        min_fill=min_fill, min_roundness=min_roundness,
                        min_radius=min_radius * k, max_radius=max_radius * k,
                        min_diam_frac=min_diam_frac,
                        max_diam_frac=max_diam_frac,
                        colour_credit=colour_credit,
                        force_bright=force_bright,
                        work_size=int(work_size * k),
                        r_min=r_min * k, r_max=r_max * k,
                        n_scale=n_scale, log_thresh=log_thresh,
                        plate_type=plate_type, stats=stats,
                    )
        return probe

    s = min(1.0, work_size / max(h, w))
    if s < 1.0:
        small = cv2.resize(img, (max(1, int(w * s)), max(1, int(h * s))),
                           interpolation=cv2.INTER_AREA)
    else:
        small = img
    gray = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (3, 3), 0)
    sat_full = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)[..., 1].astype(np.float32)

    roi, size_ref = plate_roi_with_scale(gray, plate_type)

    # 콜로니 크기 창을 "접시 지름 대비 비율"로 받아 작업 픽셀 반지름으로 바꾼다.
    # 비율로 받는 이유는 해상도·카메라·촬영 거리와 무관해지기 때문이다.
    if min_diam_frac > 0.0:
        min_radius = max(min_radius, min_diam_frac * size_ref / 2.0)
    if max_diam_frac > 0.0:
        cap = max_diam_frac * size_ref / 2.0
        max_radius = cap if max_radius <= 0.0 else min(max_radius, cap)

    # 무채색 이미지에서는 색 게이트를 끈다. 흑백 카메라나 합성 이미지는
    # 채도가 0이라, 그대로 두면 모든 후보가 색 게이트에서 탈락한다.
    inside = sat_full[roi > 0]
    has_chroma = (inside.size > 0
                  and float(inside.std()) >= config.BLOB_MONO_SAT_STD)
    sat = sat_full if has_chroma else None
    if stats is not None:
        # 무채색이면 색 게이트와 색 할인이 모두 무동작이 된다. 호출자가 그것을
        # 모르면 색 슬라이더를 움직여도 결과가 안 바뀌는 이유를 알 수 없다.
        stats["has_chroma"] = bool(has_chroma)
        # min/max_diam_frac 의 분모. petri 는 접시 지름이지만 well8 이거나
        # 접시 검출이 실패하면 이미지 짧은 변으로 조용히 폴백한다 — 같은 비율이
        # 다른 물리 크기를 뜻하게 되므로 호출자가 알아야 한다. 여기서 원본
        # 픽셀로 되돌려 담는다(size_ref 는 작업 픽셀 단위다).
        stats["size_ref"] = float(size_ref / s) if s > 0 else float(size_ref)

    kept: list[tuple[float, float, float, float]] = []
    # 극성. None = 양극성 모두 검출 후 병합(기본). True/False 로 고정하면
    # 그 극성만 본다 — 검출이 늘지는 않지만, 틀린 극성의 가짜 blob이 NMS 에서
    # 진짜 콜로니를 억제하고 있다면 고정이 정밀도·재현율을 함께 올릴 수 있다.
    # 극성 결정.
    #   force_bright=True/False → 그 극성만 (호출자 지정)
    #   force_bright=None + auto_polarity=True  → **접시별 추정 후 한쪽만** (기본)
    #   force_bright=None + auto_polarity=False → 양극성 모두 검출 후 병합 (구동작)
    #
    # 접시별 추정이 양극성 병합보다 **모든 운영점에서 낫다.** 실측(39장, 같은
    # 정밀도 기준 재현율): ~88.5% 에서 60.3 → 63.6%, ~75.6% 에서 66.4 → 69.5%,
    # ~65.3% 에서 69.0 → 72.8%. 틀린 극성 분기가 기여 없이 오검출만 추가하고
    # 있었기 때문이다. 추정 정확도는 39/39(100%)였다.
    #
    # 후보는 두 극성 다 뽑는다(추정에 필요). 대신 게이트는 고른 쪽만 통과시키므로
    # 비용이 크게 늘지 않는다 — 무거운 쪽은 후보 생성이 아니라 게이트다.
    if force_bright is not None:
        polarities: tuple[bool, ...] = (force_bright,)
    elif auto_polarity:
        guess = estimate_bright(gray, roi)
        # 판정이 애매하면 양극성으로 되돌린다 — 조용히 한쪽만 보면 그 접시에서
        # 검출이 0 에 가까워질 수 있다(실측: 극성을 반대로 고른 971.jpg 98 → 3).
        polarities = (True, False) if guess is None else (guess,)
    else:
        polarities = (True, False)

    for bright in polarities:
        # 후보 생성 — 성격이 다른 두 방식을 합친다. 실측(39장)에서 합집합이
        # LoG 단독보다 **모든 운영점에서 +2.9~3.5%p** 위다:
        #   정밀도 ~95.5% → 55.1% → **58.0%**
        #   정밀도 ~88.5% → 68.5% → **72.0%**   ← 기본 운영점
        #   정밀도 ~65.3% → 74.8% → **77.8%**
        # 교환이 아니라 곡선 전체가 평행 이동한다. LoG 는 커버리지(93.4%)를,
        # 이진화는 후보 순도를 기여한다 — 서로 다른 것을 보므로 합쳐진다.
        #
        # 단 정밀도 93% 이상에서는 **이진화 단독**이 합집합보다 낫다(94%에서
        # 67.3% 대 62.9%). LoG 후보가 그 구간에서는 잡음으로만 작용하기 때문이다.
        # 계수(CFU)처럼 정밀도가 중요한 용도라면 candidate_source="threshold".
        cands = []
        if candidate_source in ("union", "log"):
            cands.append(log_candidates(
                gray, roi, bright, r_min=r_min, r_max=r_max, n_scale=n_scale,
                log_thresh=log_thresh,
                max_candidates=config.BLOB_MAX_CANDIDATES,
            ))
        if candidate_source in ("union", "threshold"):
            cands.append(threshold_candidates(
                gray, roi, bright, r_min=r_min, r_max=r_max,
                n_levels=threshold_levels,
                max_candidates=config.BLOB_MAX_CANDIDATES,
            ))
        cands = merge_candidates(*cands)
        kept += colony_gate(
            gray, sat, roi, cands, bright,
            min_t=min_t, min_rel_sat=min_rel_sat,
            min_circularity=min_circularity, min_solidity=min_solidity,
            max_aspect=max_aspect, min_fill=min_fill,
            min_roundness=min_roundness, colour_credit=colour_credit,
            limit_contour=limit_contour, split_area_ratio=split_area_ratio,
            watershed_split=watershed_split, ink_sigma=ink_sigma,
            min_radius=min_radius, max_radius=max_radius,
            contour_levels=contour_levels, contour_span=contour_span,
            radius_mode=radius_mode, radius_scale=radius_scale,
            radius_alpha=radius_alpha, inner_frac=inner_frac,
            outer_lo=outer_lo, outer_hi=outer_hi,
        )

    # 두 극성이 같은 자리를 잡으면 원형도가 높은 쪽만 남긴다.
    kept.sort(key=lambda t: -t[3])
    merged: list[tuple[float, float, float, float]] = []
    for x, y, r, c in kept:
        if all(math.hypot(x - ox, y - oy) >= max(r, orr) * config.BLOB_NMS_FRAC
               for ox, oy, orr, _ in merged):
            merged.append((x, y, r, c))

    inv = 1.0 / s if s > 0 else 1.0
    return [(x * inv, y * inv, r * inv, c) for x, y, r, c in merged]
