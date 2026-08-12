"""검출 안에 들어간 검출을 찾는다.

**왜 별 모듈인가.** `detect_blobs` 의 NMS 는 중심 거리만 본다 — 억제 반경이
`max(r) * BLOB_NMS_FRAC` 이라, 큰 검출 안에 있어도 중심이 그 반경 밖이면
살아남는다. 포함 관계를 검사하지 않기 때문이다. 그 검사를 NMS 안에 넣지 않고
후처리로 분리한 이유는, 검출 경로를 건드리지 않으면 옵션을 끈 상태에서 기존
결과가 **바이트 단위로 동일**하다는 것을 보장할 수 있기 때문이다.

**왜 면적 겹침인가.** 실측(라벨 39장)에서 중첩 검출은 콜로니 윤곽선에 걸쳐
있는 경우가 흔해서, "완전히 포함" 기준으로는 놓친다. 문턱별 성적은
`config.BLOB_NESTED_OVERLAP` 주석에 있다.
"""
from __future__ import annotations

import math


def circle_overlap(
    x1: float, y1: float, r1: float, x2: float, y2: float, r2: float
) -> float:
    """두 원의 교집합 면적 (해석해).

    렌즈 모양 교집합은 두 원형 세그먼트의 합이다. 몬테카를로나 마스크 렌더링을
    쓰지 않는 이유는 검출 수가 수백 개면 쌍이 수만 개가 되기 때문이다.
    """
    d = math.hypot(x1 - x2, y1 - y2)
    if d >= r1 + r2:
        return 0.0
    if d <= abs(r1 - r2):
        # 한쪽이 다른 쪽을 완전히 품는다 — 작은 원 면적이 곧 교집합이다.
        return math.pi * min(r1, r2) ** 2
    a1 = math.acos((d * d + r1 * r1 - r2 * r2) / (2 * d * r1))
    a2 = math.acos((d * d + r2 * r2 - r1 * r1) / (2 * d * r2))
    return (r1 * r1 * (a1 - math.sin(2 * a1) / 2)
            + r2 * r2 * (a2 - math.sin(2 * a2) / 2))


def find_parents(geom: list[dict], overlap: float) -> list[int | None]:
    """각 검출을 감싸는 부모의 인덱스. 없으면 None.

    부모의 조건은 두 가지다.
      1. 반지름이 **더 크다** (같으면 어느 쪽이 부모인지 정할 수 없어 제외)
      2. 자기 면적의 `overlap` 배 이상을 덮는다

    여러 개가 조건을 만족하면 **가장 작은 것**(직속 부모)을 고른다. 그래야
    A ⊃ B ⊃ C 에서 C 의 부모가 A 가 아니라 B 가 된다.
    """
    out: list[int | None] = [None] * len(geom)
    for i, c in enumerate(geom):
        r = float(c["radius"])
        area = math.pi * r * r
        if area <= 0:
            continue
        best: int | None = None
        best_r: float | None = None
        for j, o in enumerate(geom):
            if j == i:
                continue
            ro = float(o["radius"])
            if ro <= r:
                continue
            shared = circle_overlap(
                float(c["x"]), float(c["y"]), r,
                float(o["x"]), float(o["y"]), ro,
            )
            if shared / area < overlap:
                continue
            if best_r is None or ro < best_r:
                best, best_r = j, ro
        out[i] = best
    return out
