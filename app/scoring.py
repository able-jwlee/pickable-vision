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


def _size_score(r: float) -> float:
    """선호 크기 대역([MIN, MAX]) 안이면 1.0, 밖이면 선형 감쇠."""
    lo, hi = config.PICK_RADIUS_MIN, config.PICK_RADIUS_MAX
    if r < lo:
        return max(0.0, r / lo)
    if r > hi:
        return max(0.0, 1.0 - (r - hi) / hi)
    return 1.0


def score_colonies(
    colonies: list[dict], top_n: int | None = None, pick_mask=None
) -> list[dict]:
    """각 콜로니에 pickability 점수와 pickable 여부를 매긴다.

    입력: [{"x","y","radius", ...}, ...]
    출력(입력과 같은 순서): [{"score": float(0~1), "pickable": bool}, ...]

    - score = (고립도 * w_iso + 크기적합도 * w_size) * 원형도보정(0.5~1.0)
      → 둥근 콜로니가 상위로 랭크됨. circularity가 없으면 보정=1(기존과 동일).
    - pickable = 이웃과 충분히 떨어져 있고(PICK_MIN_SEPARATION) 크기가 대역 안이며,
      (circularity가 주어지면) 충분히 둥글 때(PICK_MIN_CIRCULARITY).
    - pick_mask(2D uint8)가 주어지면 중심이 mask 밖(=0)인 것은 pickable에서 제외
      (웰/plate 경계 근처 반점을 안전 여백으로 걸러냄).
    - top_n이 주어지면 pickable 중 점수 상위 top_n개만 pickable로 남긴다.
    """
    if not colonies:
        return []

    pts = [(c["x"], c["y"]) for c in colonies]
    out = []
    for i, c in enumerate(colonies):
        r = c["radius"]
        q = c.get("circularity")  # None이면 원형도 기준을 적용하지 않음(하위호환)
        nn = _nearest_neighbor_dist(pts, i)
        iso = 1.0 if nn == math.inf else min(nn / config.PICK_ISOLATION_REF, 1.0)
        size = _size_score(r)
        base = config.PICK_W_ISOLATION * iso + config.PICK_W_SIZE * size
        round_factor = 0.5 + 0.5 * (q if q is not None else 1.0)
        score = round(base * round_factor, 3)
        pickable = (
            nn >= config.PICK_MIN_SEPARATION
            and config.PICK_RADIUS_MIN <= r <= config.PICK_RADIUS_MAX
        )
        if pickable and q is not None and q < config.PICK_MIN_CIRCULARITY:
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
