"""히스토그램 기반 경사부스팅 결정트리 — numpy만으로 구현.

왜 트리인가: 로지스틱 회귀는 특징 공간에 직선 경계 하나만 그려서, 현재 AND
게이트("이 조건들이 **모두** 성립")를 표현조차 못 한다. 실제로 콜로니 단위
비교에서 AND 게이트(90.4%/51.2%)가 로지스틱(87.0%/43.0%)을 이겼다.
결정트리는 논리곱을 자연스럽게 표현하므로 AND 게이트를 포함하는 더 넓은
가설 공간이다 — 이기지 못하면 수작업 게이트가 최적에 가깝다는 결론이 된다.

의존성은 늘리지 않는다. 학습은 오프라인이고, 배포는 트리 구조를 JSON으로만
내보내 순수 numpy로 추론한다.

구현: XGBoost 식 뉴턴 부스팅.
  gain  = sum(g)^2 / (sum(h) + lambda)
  leaf  = -sum(g) / (sum(h) + lambda)
특징을 분위수 32구간으로 미리 이산화해 분할 탐색을 bincount 한 번으로 끝낸다
(220k 샘플 × 16 특징이라 이산화 없이는 느리다).
"""
from __future__ import annotations

import json
import math

import numpy as np

N_BINS = 32


def make_bins(X, n_bins=N_BINS):
    """학습 fold 에서만 분위수 경계를 구한다 (검증 정보 누출 방지)."""
    edges = []
    for j in range(X.shape[1]):
        q = np.quantile(X[:, j], np.linspace(0, 1, n_bins + 1)[1:-1])
        edges.append(np.unique(q))
    return edges


def apply_bins(X, edges):
    B = np.empty(X.shape, np.uint8)
    for j in range(X.shape[1]):
        B[:, j] = np.searchsorted(edges[j], X[:, j], side="right")
    return B


class Node:
    __slots__ = ("feat", "bin", "left", "right", "value")

    def __init__(self):
        self.feat = -1
        self.bin = 0
        self.left = None
        self.right = None
        self.value = 0.0


def _build(B, g, h, idx, depth, max_depth, lam, min_child):
    node = Node()
    G, H = g[idx].sum(), h[idx].sum()
    node.value = -G / (H + lam)
    if depth >= max_depth or len(idx) < 2 * min_child:
        return node

    parent_gain = G * G / (H + lam)
    best = (0.0, -1, 0)
    nb = N_BINS + 1
    for j in range(B.shape[1]):
        b = B[idx, j]
        gs = np.bincount(b, weights=g[idx], minlength=nb)
        hs = np.bincount(b, weights=h[idx], minlength=nb)
        cg, ch = np.cumsum(gs), np.cumsum(hs)
        cnt = np.cumsum(np.bincount(b, minlength=nb))
        gl, hl, nl = cg[:-1], ch[:-1], cnt[:-1]
        gr, hr = G - gl, H - hl
        nr = len(idx) - nl
        ok = (nl >= min_child) & (nr >= min_child)
        if not ok.any():
            continue
        gain = gl * gl / (hl + lam) + gr * gr / (hr + lam) - parent_gain
        gain = np.where(ok, gain, -np.inf)
        k = int(np.argmax(gain))
        if gain[k] > best[0]:
            best = (float(gain[k]), j, k)

    if best[1] < 0 or best[0] <= 1e-9:
        return node
    node.feat, node.bin = best[1], best[2]
    m = B[idx, node.feat] <= node.bin
    node.left = _build(B, g, h, idx[m], depth + 1, max_depth, lam, min_child)
    node.right = _build(B, g, h, idx[~m], depth + 1, max_depth, lam, min_child)
    return node


def _predict_tree(node, B, out, idx):
    if node.feat < 0:
        out[idx] += node.value
        return
    m = B[idx, node.feat] <= node.bin
    _predict_tree(node.left, B, out, idx[m])
    _predict_tree(node.right, B, out, idx[~m])


def _to_dict(node):
    if node.feat < 0:
        return {"v": node.value}
    return {"f": int(node.feat), "b": int(node.bin),
            "l": _to_dict(node.left), "r": _to_dict(node.right)}


def sigmoid(z):
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


def fit_gbm(X, y, rounds=250, lr=0.1, max_depth=3, lam=1.0, min_child=50,
            pos_weight=None, verbose=False):
    """(트리 리스트, bin 경계, base_score) 반환."""
    edges = make_bins(X)
    B = apply_bins(X, edges)
    n = len(y)
    if pos_weight is None:
        pos_weight = float((y == 0).sum()) / max(1.0, float((y == 1).sum()))
    sw = np.where(y == 1, pos_weight, 1.0)
    sw = sw / sw.mean()

    p0 = float(np.clip((sw * y).sum() / sw.sum(), 1e-6, 1 - 1e-6))
    base = math.log(p0 / (1 - p0))
    F = np.full(n, base)
    trees = []
    all_idx = np.arange(n)
    for it in range(rounds):
        p = sigmoid(F)
        g = sw * (p - y)
        h = sw * np.maximum(p * (1 - p), 1e-6)
        t = _build(B, g, h, all_idx, 0, max_depth, lam, min_child)
        upd = np.zeros(n)
        _predict_tree(t, B, upd, all_idx)
        F += lr * upd
        trees.append(t)
        if verbose and (it + 1) % 50 == 0:
            pp = sigmoid(F)
            ll = -(sw * (y * np.log(pp + 1e-9)
                         + (1 - y) * np.log(1 - pp + 1e-9))).mean()
            print(f"    round {it+1:4d}  weighted logloss {ll:.4f}", flush=True)
    return trees, edges, base, lr


def predict_gbm(model, X):
    trees, edges, base, lr = model
    B = apply_bins(X, edges)
    F = np.full(len(X), base)
    idx = np.arange(len(X))
    for t in trees:
        upd = np.zeros(len(X))
        _predict_tree(t, B, upd, idx)
        F += lr * upd
    return sigmoid(F)


def dump_gbm(model, names, path):
    trees, edges, base, lr = model
    obj = {
        "names": [str(n) for n in names],
        "bin_edges": [e.tolist() for e in edges],
        "base_score": base,
        "learning_rate": lr,
        "trees": [_to_dict(t) for t in trees],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    return obj
