"""후보 판정용 로지스틱 회귀를 numpy만으로 학습한다.

의존성을 늘리지 않는 것이 중요하다 — FastAPI 서비스에 torch/sklearn을 들이지
않고, 학습 결과는 계수 몇 개(JSON)로만 배포한다.

검증 규칙 (엄격하게):
  - **이미지 단위 분리.** 같은 접시의 콜로니는 조명·배지·균주를 공유하므로
    콜로니 단위로 나누면 검증이 무의미해진다. 이미지 40장을 그룹별로 층화해
    K-fold 로 나눈다.
  - 학습 fold 에서만 표준화 통계와 계수를 구하고, 검증 fold 에 적용한다.
  - 보고 수치는 검증 fold 만 합산한 것이다.

비교 대상은 현재 AND 게이트 사슬이다. 같은 후보 집합에 대해 같은 운영점
(재현율 또는 정밀도)을 맞춰 놓고 다른 쪽을 비교해야 의미가 있다.
"""
from __future__ import annotations

import json
import sys

import numpy as np

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SP = str(ROOT / "output" / "learned")


def sigmoid(z):
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


def fit_logreg(X, y, l2=1e-3, iters=400, lr=0.5, pos_weight=None):
    """L2 로지스틱 회귀. 클래스 불균형이 크므로 양성에 가중을 준다.

    후보의 약 10%만 양성이라, 가중 없이 학습하면 전부 음성으로 예측하는
    해에 수렴한다.
    """
    n, d = X.shape
    w = np.zeros(d + 1, np.float64)
    Xb = np.hstack([X, np.ones((n, 1))])
    if pos_weight is None:
        pos_weight = float((y == 0).sum()) / max(1.0, float((y == 1).sum()))
    sw = np.where(y == 1, pos_weight, 1.0)
    sw = sw / sw.mean()
    for it in range(iters):
        p = sigmoid(Xb @ w)
        grad = Xb.T @ (sw * (p - y)) / n
        grad[:-1] += l2 * w[:-1]
        # 대각 근사 뉴턴 (등방 lr 보다 훨씬 빠르게 수렴)
        h = Xb.T @ (sw * p * (1 - p) * Xb.T).T / n
        h_diag = np.diag(h).copy()
        h_diag[:-1] += l2
        h_diag = np.maximum(h_diag, 1e-6)
        w -= lr * grad / h_diag
    return w


def pr_curve(scores, y):
    """점수 내림차순으로 훑으며 (정밀도, 재현율) 곡선."""
    order = np.argsort(-scores)
    ys = y[order]
    tp = np.cumsum(ys)
    fp = np.cumsum(1 - ys)
    prec = tp / np.maximum(tp + fp, 1)
    rec = tp / max(1, ys.sum())
    return prec, rec, scores[order]


def prec_at_recall(scores, y, target_rec):
    prec, rec, thr = pr_curve(scores, y)
    idx = np.searchsorted(rec, target_rec)
    if idx >= len(rec):
        return prec[-1], thr[-1]
    return prec[idx], thr[idx]


def main():
    d = np.load(f"{SP}/cands.npz", allow_pickle=True)
    X, y, img_ids = d["X"], d["y"].astype(np.float64), d["img_ids"]
    names = list(d["names"])
    meta = d["meta"]
    groups = meta[:, 4].astype(int)

    print(f"후보 {len(X)}개  양성 {int(y.sum())}개 ({y.mean()*100:.2f}%)  "
          f"이미지 {len(np.unique(img_ids))}장  특징 {X.shape[1]}개")
    print()

    # 이미지 단위 5-fold, 그룹(촬영조건)별 층화
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

    # 현재 AND 게이트가 이 후보들에 대해 내는 운영점 (비교 기준)
    from app import config
    ti = names.index("t_stat")
    si = names.index("rel_sat")
    ci = names.index("circ")
    soi = names.index("solidity")
    ai = names.index("aspect")
    fi = names.index("fill")
    gate = ((X[:, ti] >= config.BLOB_MIN_T)
            & (X[:, si] >= config.BLOB_MIN_REL_SAT)
            & (X[:, ci] >= config.BLOB_MIN_CIRCULARITY)
            & (X[:, soi] >= config.BLOB_MIN_SOLIDITY)
            & (X[:, ai] <= config.BLOB_MAX_ASPECT)
            & (X[:, fi] >= config.BLOB_MIN_FILL))
    g_prec = y[gate].mean() if gate.sum() else 0.0
    g_rec = y[gate].sum() / y.sum()
    print(f"현재 AND 게이트 (후보 단위): 정밀도 {g_prec*100:.1f}% "
          f"재현율 {g_rec*100:.1f}%  통과 {int(gate.sum())}개")
    print()

    # 교차검증
    oof = np.zeros(len(X))
    for k in range(5):
        tr, va = fold != k, fold == k
        mu, sd = X[tr].mean(0), X[tr].std(0) + 1e-6
        w = fit_logreg((X[tr] - mu) / sd, y[tr])
        oof[va] = sigmoid(((X[va] - mu) / sd) @ w[:-1] + w[-1])

    print("검증(out-of-fold) 후보 단위 성적")
    print(f"{'재현율 목표':>10s} {'학습판정기 정밀도':>16s} {'AND게이트 정밀도':>16s}")
    for tr_ in (g_rec, 0.5, 0.6, 0.7, 0.8):
        p, _ = prec_at_recall(oof, y, tr_)
        mark = "  <- AND과 같은 재현율" if abs(tr_ - g_rec) < 1e-9 else ""
        print(f"{tr_*100:9.1f}% {p*100:15.1f}% "
              f"{g_prec*100 if abs(tr_-g_rec)<1e-9 else float('nan'):15.1f}%{mark}")
    print()

    # 전체 데이터로 최종 계수 (배포용)
    mu, sd = X.mean(0), X.std(0) + 1e-6
    w = fit_logreg((X - mu) / sd, y)
    _, thr = prec_at_recall(oof, y, g_rec)
    coef = {
        "names": [str(n) for n in names],
        "mean": mu.tolist(),
        "scale": sd.tolist(),
        "weights": w[:-1].tolist(),
        "bias": float(w[-1]),
        "threshold_at_gate_recall": float(thr),
    }
    with open(f"{SP}/logreg.json", "w", encoding="utf-8") as f:
        json.dump(coef, f, indent=1)
    print(f"계수 저장: {SP}/logreg.json")

    order = np.argsort(-np.abs(w[:-1]))
    print()
    print("기여도 큰 특징 (표준화 계수 절댓값)")
    for i in order[:10]:
        print(f"  {names[i]:14s} {w[i]:+7.3f}")


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    import os
    os.chdir(ROOT)
    main()
