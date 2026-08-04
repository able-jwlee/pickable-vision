"""후보별 특징 벡터와 라벨을 추출해 npz로 저장한다.

왜 학습된 경계인가: 현재 게이트는 t·채도·원형도·solidity·aspect·fill을 각각
문턱으로 자르는 AND 사슬이다. 이는 특징 공간에서 **축에 평행한 절단**만 만든다.
측정 결과 개별 특징은 저대비 구간(t 10~35)에서 판별력이 없었지만, 여러 약한
특징의 조합은 비스듬한 경계를 만들 수 있고 그건 AND로 표현 불가능하다.
즉 또 하나의 정밀도/재현율 교환이 아니라 다른 기전이다.

과적합 방지: 이미지 40장뿐이므로 **콜로니 단위가 아니라 이미지 단위로** 분리해
검증한다. 같은 접시의 콜로니는 조명·배지·균주를 공유하므로 콜로니 단위 분리는
검증을 무의미하게 만든다. img_id 를 함께 저장한다.
"""
from __future__ import annotations

import glob
import json
import math
import os
import sys

import cv2
import numpy as np

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from app import config  # noqa: E402
from app.blob_detector import log_candidates, plate_roi_with_scale  # noqa: E402

OUTDIR = ROOT / "output" / "learned"
OUTDIR.mkdir(parents=True, exist_ok=True)
OUT = str(OUTDIR / "cands.npz")

FEATURE_NAMES = [
    "t_stat",        # 면적 가중 t-통계량
    "contrast",      # 중심 - 주변 (극성 보정)
    "log_area",      # log(1+윤곽 면적)
    "rel_size",      # 반지름 / 접시 지름
    "rel_sat",       # |내부채도 - 주변채도|
    "hue_dist",      # hue 원형거리
    "circ",          # 4πA/P²
    "roundness",     # 면적 / 최소외접원 면적
    "solidity",      # 면적 / convex hull 면적
    "aspect",        # 종횡비
    "fill",          # 면적 / bbox
    "radial_mono",   # 방사형 단조성
    "edge_coher",    # 경계 기울기 일관성
    "log_s_out",     # log(1+주변 산포) — 국소 노이즈 수준
    "log_n_in",      # log(1+내부 픽셀 수)
    "is_bright",     # 극성 (밝은 콜로니면 1)
]

GROUPS = [
    "sample/lower-resolution",
    "sample/higher-resolution/bright",
    "sample/higher-resolution/dark",
    "sample/higher-resolution/vague",
]


def candidate_features(gray, hsv, roi, size_ref, x, y, r, bright):
    """후보 하나의 특징 벡터. 계산 불가면 None."""
    h, w = gray.shape
    r = max(2.0, r)
    pad = int(r * 2.4) + 3
    x0, y0 = max(0, int(x - pad)), max(0, int(y - pad))
    x1, y1 = min(w, int(x + pad) + 1), min(h, int(y + pad) + 1)
    patch = gray[y0:y1, x0:x1]
    if patch.size < 25:
        return None
    pr = roi[y0:y1, x0:x1]
    ph = hsv[y0:y1, x0:x1]
    cx, cy = x - x0, y - y0
    yy, xx = np.mgrid[0:patch.shape[0], 0:patch.shape[1]]
    d = np.hypot(xx - cx, yy - cy)

    inner = (d <= r * 0.65) & (pr > 0)
    outer = (d >= r * 1.4) & (d <= r * 2.1) & (pr > 0)
    n_in, n_out = int(inner.sum()), int(outer.sum())
    if n_in < 5 or n_out < 10:
        return None

    vi, vo = patch[inner], patch[outer]
    mi, mo = float(np.median(vi)), float(np.median(vo))
    floor = config.BLOB_NOISE_FLOOR
    s_in = max(1.4826 * float(np.median(np.abs(vi - mi))), floor)
    s_out = max(1.4826 * float(np.median(np.abs(vo - mo))), floor)
    se = math.sqrt(s_in * s_in / n_in + s_out * s_out / n_out)
    contrast = (mi - mo) if bright else (mo - mi)
    t_stat = contrast / se

    # 색
    rel_sat = abs(float(np.median(ph[..., 1][inner]))
                  - float(np.median(ph[..., 1][outer])))
    hi = float(np.median(ph[..., 0][inner]))
    ho = float(np.median(ph[..., 0][outer]))
    dh = abs(hi - ho)
    hue_dist = min(dh, 180.0 - dh)

    # 지역 이진화 후 모양
    lvl = (mi + mo) / 2.0
    binm = ((patch >= lvl) if bright else (patch <= lvl)).astype(np.uint8) * 255
    binm[pr == 0] = 0
    binm = cv2.morphologyEx(binm, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    cnts, _ = cv2.findContours(binm, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    pick = None
    for c in cnts:
        if cv2.pointPolygonTest(c, (float(cx), float(cy)), False) >= 0:
            pick = c
            break
    if pick is None:
        return None
    area = cv2.contourArea(pick)
    per = cv2.arcLength(pick, True)
    if area < 6 or per <= 0:
        return None
    circ = 4.0 * math.pi * area / (per * per)
    (_ex, _ey), r_enc = cv2.minEnclosingCircle(pick)
    roundness = area / (math.pi * r_enc * r_enc) if r_enc > 0 else 0.0
    hull_a = cv2.contourArea(cv2.convexHull(pick))
    solidity = area / hull_a if hull_a > 0 else 0.0
    _bx, _by, bw_, bh_ = cv2.boundingRect(pick)
    aspect = max(bw_, bh_) / max(1, min(bw_, bh_))
    fill = area / max(1, bw_ * bh_)
    r_fit = math.sqrt(area / math.pi)

    # 방사형 단조성
    edges = np.linspace(0, r * 2.1, 9)
    prof = []
    for i in range(len(edges) - 1):
        band = (d >= edges[i]) & (d < edges[i + 1]) & (pr > 0)
        if band.sum() >= 4:
            prof.append(float(np.median(patch[band])))
    if len(prof) >= 5:
        p = np.array(prof)
        if not bright:
            p = -p
        radial_mono = (-np.corrcoef(np.arange(len(p)), p)[0, 1]
                       if np.std(p) > 1e-6 else 0.0)
        if not np.isfinite(radial_mono):
            radial_mono = 0.0
    else:
        radial_mono = 0.0

    # 경계 기울기 일관성
    gx = cv2.Sobel(patch, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(patch, cv2.CV_32F, 0, 1, ksize=3)
    ring = (d >= r * 0.8) & (d <= r * 1.25) & (pr > 0)
    if ring.sum() >= 8:
        ux = (xx - cx) / np.maximum(d, 1e-6)
        uy = (yy - cy) / np.maximum(d, 1e-6)
        dot = gx[ring] * ux[ring] + gy[ring] * uy[ring]
        if not bright:
            dot = -dot
        edge_coher = float((dot < 0).mean())
    else:
        edge_coher = 0.5

    gcx = float(cv2.moments(pick)["m10"] / max(cv2.moments(pick)["m00"], 1e-9)) + x0
    gcy = float(cv2.moments(pick)["m01"] / max(cv2.moments(pick)["m00"], 1e-9)) + y0

    feat = [
        t_stat, contrast, math.log1p(area), r_fit / max(size_ref, 1.0),
        rel_sat, hue_dist, circ, roundness, solidity, aspect, fill,
        radial_mono, edge_coher, math.log1p(s_out), math.log1p(n_in),
        1.0 if bright else 0.0,
    ]
    return feat, gcx, gcy, r_fit, circ


def main():
    X, y, img_ids, meta = [], [], [], []
    img_id = 0
    for gi, grp in enumerate(GROUPS):
        for p in sorted(glob.glob(f"{grp}/*.jpg")):
            j = p.rsplit(".", 1)[0] + ".json"
            if not os.path.exists(j):
                continue
            labs = json.load(open(j, encoding="utf-8"))["labels"]
            if not labs:
                continue
            img = cv2.imread(p)
            h, w = img.shape[:2]
            s = min(1.0, config.BLOB_WORK_SIZE / max(h, w))
            sm = cv2.resize(img, (int(w * s), int(h * s)),
                            interpolation=cv2.INTER_AREA)
            g = cv2.GaussianBlur(cv2.cvtColor(sm, cv2.COLOR_BGR2GRAY), (3, 3), 0)
            gf = g.astype(np.float32)
            hsv = cv2.cvtColor(sm, cv2.COLOR_BGR2HSV).astype(np.float32)
            roi, size_ref = plate_roi_with_scale(g, "petri")
            boxes = [(l["x"] * s, l["y"] * s,
                      (l["x"] + l["width"]) * s, (l["y"] + l["height"]) * s)
                     for l in labs]

            n_before = len(X)
            for bright in (True, False):
                cands = log_candidates(
                    g, roi, bright, r_min=config.BLOB_R_MIN,
                    r_max=config.BLOB_R_MAX, n_scale=config.BLOB_N_SCALE,
                    log_thresh=config.BLOB_LOG_THRESH,
                    max_candidates=config.BLOB_MAX_CANDIDATES,
                )
                for cxx, cyy, crr in cands:
                    out = candidate_features(gf, hsv, roi, size_ref,
                                             cxx, cyy, crr, bright)
                    if out is None:
                        continue
                    feat, gcx, gcy, r_fit, circ = out
                    hit = any(bx0 <= gcx <= bx1 and by0 <= gcy <= by1
                              for bx0, by0, bx1, by1 in boxes)
                    X.append(feat)
                    y.append(1 if hit else 0)
                    img_ids.append(img_id)
                    meta.append([gcx, gcy, r_fit, circ, gi])
            print(f"  {os.path.basename(p):16s} 후보 {len(X)-n_before:6d} "
                  f"누적 {len(X):7d}", flush=True)
            img_id += 1

    X = np.array(X, np.float32)
    y = np.array(y, np.int8)
    img_ids = np.array(img_ids, np.int16)
    meta = np.array(meta, np.float32)
    np.savez_compressed(OUT, X=X, y=y, img_ids=img_ids, meta=meta,
                        names=np.array(FEATURE_NAMES))
    print()
    print(f"저장 {OUT}")
    print(f"후보 {len(X)}개  양성 {int(y.sum())}개 ({y.mean()*100:.2f}%)  "
          f"이미지 {img_id}장  특징 {X.shape[1]}개")


if __name__ == "__main__":
    main()
