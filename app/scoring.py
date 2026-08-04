import math

from app import config


def _nearest_neighbor_dist(points: list[tuple[float, float]], i: int) -> float:
    """i번 점에서 가장 가까운 다른 점까지 거리. 혼자면 inf."""
    xi, yi = points[i]
    best = math.inf
    for j, (xj, yj) in enumerate(points):
        if j == i:
            continue
        d = math.hypot(xi - xj, yi - yj)
        if d < best:
            best = d
    return best


def _size_score(r: float, lo: float, hi: float) -> float:
    """선호 크기 대역([lo, hi]) 안이면 1.0, 밖이면 선형 감쇠."""
    if lo > 0 and r < lo:
        return max(0.0, r / lo)
    if hi > 0 and r > hi:
        return max(0.0, 1.0 - (r - hi) / hi)
    return 1.0


def score_colonies(
    colonies: list[dict],
    top_n: int | None = None,
    pick_mask=None,
    radius_min: float | None = None,
    radius_max: float | None = None,
    min_separation: float | None = None,
    min_circularity: float | None = None,
) -> list[dict]:
    """각 콜로니에 pickability 점수와 pickable 여부를 매긴다.

    입력: [{"x","y","radius", ...}, ...]
    출력(입력과 같은 순서): [{"score": float(0~1), "pickable": bool}, ...]

    **기본값에서는 모든 검출이 pickable이다** (config의 피킹 필터가 전부 0).
    이 기준들은 8웰 플레이트에 맞춘 원본 픽셀 값이라 4000px 페트리 이미지에서는
    사실상 아무것도 걸러내지 못했다 — 실측 96.5%가 통과했고 원형도는 검출
    게이트가 이미 더 엄격해서 0개 탈락이었다. 자세한 배경은 config 주석 참조.

    - score = (고립도 * w_iso + 크기적합도 * w_size) * 원형도보정(0.5~1.0)
      → 필터를 껐어도 **랭킹은 유지된다**. pick_top_n(예: 96핀)으로 상한을 둘 때
      고립되고 둥근 콜로니가 먼저 선택된다.
    - pickable = 아래 기준을 모두 통과. 각 기준은 0이면 적용하지 않는다.
        min_separation  이웃 중심과의 최소 거리 (붙은 콜로니 = 혼합 클론 방지)
        radius_min/max  핀 기하에 맞는 크기 대역
        min_circularity 단일 원형 콜로니인지
    - pick_mask(2D uint8)가 주어지면 중심이 mask 밖(=0)인 것은 pickable에서 제외.
    - top_n이 주어지면 pickable 중 점수 상위 top_n개만 pickable로 남긴다.
    - 모든 기준은 인자로 요청별 덮어쓰기가 가능하다. 단위가 원본 이미지 픽셀이라
      해상도에 의존하므로, 다시 켤 때는 접시 지름 대비 비율로 환산해 넘겨야 한다.
    """
    if not colonies:
        return []

    lo = config.PICK_RADIUS_MIN if radius_min is None else radius_min
    hi = config.PICK_RADIUS_MAX if radius_max is None else radius_max
    sep = (config.PICK_MIN_SEPARATION if min_separation is None
           else min_separation)
    min_circ = (config.PICK_MIN_CIRCULARITY if min_circularity is None
                else min_circularity)
    pts = [(c["x"], c["y"]) for c in colonies]
    out = []
    for i, c in enumerate(colonies):
        r = c["radius"]
        q = c.get("circularity")  # None이면 원형도 기준을 적용하지 않음(하위호환)
        nn = _nearest_neighbor_dist(pts, i)
        iso = 1.0 if nn == math.inf else min(nn / config.PICK_ISOLATION_REF, 1.0)
        size = _size_score(r, lo, hi)
        base = config.PICK_W_ISOLATION * iso + config.PICK_W_SIZE * size
        round_factor = 0.5 + 0.5 * (q if q is not None else 1.0)
        score = round(base * round_factor, 3)
        # 각 기준은 0이면 적용하지 않는다 (기본값 = 검출된 것 전부 피킹 대상).
        pickable = (
            nn >= sep
            and r >= lo
            and (hi <= 0 or r <= hi)
        )
        if pickable and min_circ > 0 and q is not None and q < min_circ:
            pickable = False
        if pickable and pick_mask is not None:
            yi = int(min(max(c["y"], 0), pick_mask.shape[0] - 1))
            xi = int(min(max(c["x"], 0), pick_mask.shape[1] - 1))
            if pick_mask[yi, xi] == 0:
                pickable = False
        out.append({"score": score, "pickable": pickable})

    if top_n is not None:
        ranked = sorted(
            (i for i, o in enumerate(out) if o["pickable"]),
            key=lambda i: out[i]["score"],
            reverse=True,
        )
        keep = set(ranked[:top_n])
        for i, o in enumerate(out):
            if o["pickable"] and i not in keep:
                o["pickable"] = False

    return out
