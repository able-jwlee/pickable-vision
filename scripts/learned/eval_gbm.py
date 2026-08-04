"""GBM 판정기를 콜로니 단위로 평가 (이미지 단위 5-fold)."""
import os, sys
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[2]
HERE = os.path.dirname(os.path.abspath(__file__))
SP = str(ROOT / "output" / "learned")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, HERE)
os.chdir(ROOT)

import eval_logreg as EL
from gbm import fit_gbm, predict_gbm
from app import config

d = np.load(f"{SP}/cands.npz", allow_pickle=True)
X = d["X"].astype(np.float64); y = d["y"].astype(np.float64)
img_ids = d["img_ids"]; meta = d["meta"]; names = [str(n) for n in d["names"]]
groups = meta[:, 4].astype(int)
cx, cy, rr, circ = meta[:,0], meta[:,1], meta[:,2], meta[:,3]
boxes = EL.gt_boxes_per_image()
uimg = np.unique(img_ids)

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

oof = np.zeros(len(X))
for k in range(5):
    tr, va = fold != k, fold == k
    print(f"  fold {k}: 학습 {int(tr.sum())} 검증 {int(va.sum())}", flush=True)
    m = fit_gbm(X[tr], y[tr], rounds=250, lr=0.1, max_depth=3, verbose=True)
    oof[va] = predict_gbm(m, X[va])

def colony_level(sel, score):
    import math
    TP = DET = GT = 0
    for i, im in enumerate(uimg):
        mm = (img_ids == im) & sel
        idx = np.where(mm)[0]
        GT += len(boxes[i])
        if len(idx) == 0: continue
        kl = EL.nms(cx[idx], cy[idx], rr[idx], score[idx])
        keep = [idx[j] for j in kl]
        DET += len(keep); TP += EL.match(cx, cy, keep, boxes[i])
    p = TP/DET*100 if DET else 0.0; r = TP/GT*100 if GT else 0.0
    return p, r, (2*p*r/(p+r) if p+r else 0.0), DET, TP

ti, si = names.index("t_stat"), names.index("rel_sat")
ci, soi = names.index("circ"), names.index("solidity")
ai, fi = names.index("aspect"), names.index("fill")
gate = ((X[:,ti]>=config.BLOB_MIN_T)&(X[:,si]>=config.BLOB_MIN_REL_SAT)
        &(X[:,ci]>=config.BLOB_MIN_CIRCULARITY)&(X[:,soi]>=config.BLOB_MIN_SOLIDITY)
        &(X[:,ai]<=config.BLOB_MAX_ASPECT)&(X[:,fi]>=config.BLOB_MIN_FILL))
print()
p,r,f,D,T = colony_level(gate, circ)
print(f"{'현재 AND 게이트':26s} 정밀도{p:6.1f}% 재현율{r:6.1f}% F1{f:6.1f}  (검출 {D}, 맞힘 {T})")
print(f"{'GBM (검증 fold)':26s}")
for thr in (0.5,0.7,0.8,0.9,0.95,0.98,0.99,0.995,0.999):
    p,r,f,D,T = colony_level(oof>=thr, oof)
    print(f"  문턱 {thr:<6.3f}                정밀도{p:6.1f}% 재현율{r:6.1f}% F1{f:6.1f}  (검출 {D}, 맞힘 {T})")
np.save(f"{SP}/gbm_oof.npy", oof)
