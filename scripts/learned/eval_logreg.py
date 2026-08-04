"""학습 판정기를 **콜로니 단위**로 평가한다 (NMS + 매칭까지 포함).

후보 단위 지표는 오해를 부른다: 콜로니 하나에 후보가 평균 20여 개 붙으므로
후보 재현율 5.2%가 콜로니 재현율 50%에 대응한다. 콜로니 하나당 후보 하나만
살아남으면 검출 성공이기 때문이다. 따라서 비교는 NMS와 1:1 매칭을 거친 뒤에만
의미가 있다.

검증은 이미지 단위 5-fold. 각 fold에서 학습 이미지로만 표준화·계수를 구하고
검증 이미지의 후보를 점수화한다. 보고 수치는 검증 fold 합산이다.
"""
from __future__ import annotations

import glob
import json
import math
import os
import sys

import numpy as np

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

from app import config  # noqa: E402
from train_logreg import fit_logreg, sigmoid  # noqa: E402

SP = str(ROOT / "output" / "learned")
GROUPS = [
    "sample/lower-resolution",
    "sample/higher-resolution/bright",
    "sample/higher-resolution/dark",
    "sample/higher-resolution/vague",
]


def gt_boxes_per_image():
    """extract.py 와 **같은 순서**로 이미지별 정답 박스(작업 좌표)를 복원한다."""
    import cv2
    out = []
    for grp in GROUPS:
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
            out.append([
                (l["x"] * s, l["y"] * s,
                 (l["x"] + l["width"]) * s, (l["y"] + l["height"]) * s)
                for l in labs
            ])
    return out


def nms(cx, cy, r, score):
    """점수 내림차순으로 훑으며 겹치는 것을 억제. detect_blobs 와 같은 규칙."""
    order = np.argsort(-score)
    keep = []
    for i in order:
        ok = True
        for j in keep:
            if math.hypot(cx[i] - cx[j], cy[i] - cy[j]) < \
                    max(r[i], r[j]) * config.BLOB_NMS_FRAC:
                ok = False
                break
        if ok:
            keep.append(i)
    return keep


def match(cx, cy, keep, boxes):
    used = [False] * len(boxes)
    tp = 0
    for i in keep:
        best, bd = -1, None
        for k, (x0, y0, x1, y1) in enumerate(boxes):
            if used[k] or not (x0 <= cx[i] <= x1 and y0 <= cy[i] <= y1):
                continue
            d = (cx[i] - (x0 + x1) / 2) ** 2 + (cy[i] - (y0 + y1) / 2) ** 2
            if bd is None or d < bd:
                best, bd = k, d
        if best >= 0:
            used[best] = True
            tp += 1
    return tp


def main():
    d = np.load(f"{SP}/cands.npz", allow_pickle=True)
    X = d["X"].astype(np.float64)
    y = d["y"].astype(np.float64)
    img_ids = d["img_ids"]
    meta = d["meta"]
    names = [str(n) for n in d["names"]]
    groups = meta[:, 4].astype(int)
    cx, cy, rr = meta[:, 0], meta[:, 1], meta[:, 2]
    circ = meta[:, 3]

    boxes = gt_boxes_per_image()
    uimg = np.unique(img_ids)
    assert len(boxes) == len(uimg), f"이미지 수 불일치 {len(boxes)} vs {len(uimg)}"

    # train.py 와 동일한 fold 분할 (같은 시드)
    img_group = np.array([groups[img_ids == i][0] for i in uimg])
    rng = np.random.RandomState(0)
    fold_of_img = np.zeros(len(uimg), int)
    for g in np.unique(img_group):
        idx = np.where(img_group == g)[0]
        idx = idx[rng.permutation(len(idx))]
        for k, ii in enumerate(idx):
            fold_of_img[ii] = k % 5
    fold = np.zeros(len(X), int)
    for i, im in enumerate(uimg):
        fold[img_ids == im] = fold_of_img[i]

    # out-of-fold 점수
    oof = np.zeros(len(X))
    for k in range(5):
        tr, va = fold != k, fold == k
        mu, sd = X[tr].mean(0), X[tr].std(0) + 1e-6
        w = fit_logreg((X[tr] - mu) / sd, y[tr])
        oof[va] = sigmoid(((X[va] - mu) / sd) @ w[:-1] + w[-1])

    # 현재 AND 게이트를 같은 후보 집합에 적용 (기준선)
    ti, si = names.index("t_stat"), names.index("rel_sat")
    ci, soi = names.index("circ"), names.index("solidity")
    ai, fi = names.index("aspect"), names.index("fill")
    gate = ((X[:, ti] >= config.BLOB_MIN_T)
            & (X[:, si] >= config.BLOB_MIN_REL_SAT)
            & (X[:, ci] >= config.BLOB_MIN_CIRCULARITY)
            & (X[:, soi] >= config.BLOB_MIN_SOLIDITY)
            & (X[:, ai] <= config.BLOB_MAX_ASPECT)
            & (X[:, fi] >= config.BLOB_MIN_FILL))

    def colony_level(sel, score):
        """선택된 후보 → NMS → 매칭 → (정밀도, 재현율, F1)."""
        TP = DET = GT = 0
        for i, im in enumerate(uimg):
            m = (img_ids == im) & sel
            idx = np.where(m)[0]
            GT += len(boxes[i])
            if len(idx) == 0:
                continue
            keep_local = nms(cx[idx], cy[idx], rr[idx], score[idx])
            keep = [idx[j] for j in keep_local]
            DET += len(keep)
            TP += match(cx, cy, keep, boxes[i])
        p = TP / DET * 100 if DET else 0.0
        r = TP / GT * 100 if GT else 0.0
        f = 2 * p * r / (p + r) if p + r else 0.0
        return p, r, f, DET, TP, GT

    print("콜로니 단위 성적 (NMS + 1:1 매칭 후)")
    print()
    p, r, f, DET, TP, GT = colony_level(gate, circ)
    print(f"{'현재 AND 게이트':28s} 정밀도{p:6.1f}% 재현율{r:6.1f}% F1{f:6.1f}"
          f"   (검출 {DET}, 맞힘 {TP}, 정답 {GT})")
    print()
    print(f"{'학습 판정기 (검증 fold)':28s}")
    for thr in (0.5, 0.7, 0.8, 0.9, 0.95, 0.98, 0.99, 0.995):
        p, r, f, DET, TP, GT = colony_level(oof >= thr, oof)
        print(f"  문턱 {thr:<6.3f}                  정밀도{p:6.1f}% "
              f"재현율{r:6.1f}% F1{f:6.1f}   (검출 {DET}, 맞힘 {TP})")


if __name__ == "__main__":
    main()
