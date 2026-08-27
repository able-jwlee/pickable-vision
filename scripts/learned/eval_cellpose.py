"""사전학습 Cellpose 를 우리 blob 검출기와 **같은 기준으로** 비교한다.

왜 이걸 재보는가: 오늘 계측에서 병목이 후보 검출이 아니라 판정임을 확인했고
(LoG 후보 커버리지 97.5% 대 게이트 생존 55%), 손으로 만든 특징 위의 학습
판정기(로지스틱·GBM)는 졌다. Cellpose 는 픽셀에서 특징을 직접 학습하고
**붙어 있는 객체 분리**가 설계 목표라, 우리가 못 푼 두 문제를 정면으로 겨냥한다.

공정한 비교를 위해 맞춘 것:
  - 같은 이미지 39장, 같은 라벨
  - 같은 매칭 규칙: 검출 중심이 정답 박스 안이면 TP, 정답 하나당 하나만 인정
  - 같은 처리 해상도(1024) — Cellpose 도 원본 4000px 를 그대로 넣으면 매우 느리다
  - 같은 접시 ROI: 접시 밖 검출은 양쪽 모두 제외 (프레임·배경을 세지 않도록)

학습은 하지 않는다 — 사전학습 그대로의 성능을 본다. 이게 넘으면 방향이 정해지고,
못 넘으면 이 데이터 자체의 한계가 확인된다.

사용:
    .venv-dl\\Scripts\\python scripts/learned/eval_cellpose.py
    .venv-dl\\Scripts\\python scripts/learned/eval_cellpose.py --model cyto2 --diameter 24
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

WORK = 1024
GROUPS = [
    "sample/lower-resolution",
    "sample/higher-resolution/bright",
    "sample/higher-resolution/dark",
    "sample/higher-resolution/vague",
]


def load_truth(img_path: str, scale: float):
    """정답 박스를 작업 좌표로. blob 평가와 같은 형식."""
    j = img_path.rsplit(".", 1)[0] + ".json"
    if not os.path.exists(j):
        return []
    data = json.load(open(j, encoding="utf-8"))
    return [
        (l["x"] * scale, l["y"] * scale,
         (l["x"] + l["width"]) * scale, (l["y"] + l["height"]) * scale)
        for l in (data.get("labels") or [])
    ]


def match(centres, truth):
    """blob 평가와 동일한 탐욕적 1:1 매칭."""
    used = [False] * len(truth)
    tp = 0
    for x, y in centres:
        best, bd = -1, None
        for k, (x0, y0, x1, y1) in enumerate(truth):
            if used[k] or not (x0 <= x <= x1 and y0 <= y <= y1):
                continue
            d = (x - (x0 + x1) / 2) ** 2 + (y - (y0 + y1) / 2) ** 2
            if bd is None or d < bd:
                best, bd = k, d
        if best >= 0:
            used[best] = True
            tp += 1
    return tp


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="",
                    help="사전학습 모델 이름. 비우면 라이브러리 기본값"
                         "(cellpose 4.x = cpsam_v2, SAM 기반)")
    ap.add_argument("--work", type=int, default=WORK,
                    help="처리 해상도(최대변). SAM 모델은 CPU에서 느려 낮출 수 있다")
    ap.add_argument("--limit", type=int, default=0,
                    help="그룹별 이미지 수 제한 (빠른 확인용, 0 = 전체)")
    ap.add_argument("--diameter", type=float, default=0.0,
                    help="예상 지름(작업 픽셀). 0이면 cellpose 자동 추정")
    ap.add_argument("--flow", type=float, default=0.4, help="flow_threshold")
    ap.add_argument("--cellprob", type=float, default=0.0,
                    help="cellprob_threshold — 낮추면 더 많이 검출")
    args = ap.parse_args()

    from cellpose import models
    from app.blob_detector import plate_roi  # 같은 접시 ROI 를 쓴다

    # cellpose 4.x 는 pretrained_model 기본값이 cpsam_v2(SAM 기반)이다.
    # 이름을 비우면 그 기본값을 쓴다.
    model = (models.CellposeModel(gpu=False, pretrained_model=args.model)
             if args.model else models.CellposeModel(gpu=False))

    print(f"모델 {args.model} · 지름 {args.diameter or '자동'} · "
          f"flow {args.flow} · cellprob {args.cellprob}")
    print(f"{'group':18s} {'정답':>5s} {'검출':>6s} {'TP':>5s} "
          f"{'정밀도':>8s} {'재현율':>8s} {'초/장':>6s}")

    TT = TD = TG = 0
    for grp in GROUPS:
        gt = det = tp = 0
        bgt = bdet = btp = 0
        t0 = time.time()
        n = 0
        paths = sorted(glob.glob(f"{grp}/*.jpg"))
        if args.limit:
            paths = paths[:args.limit]
        for p in paths:
            img = cv2.imread(p)
            h, w = img.shape[:2]
            s = min(1.0, args.work / max(h, w))
            small = cv2.resize(img, (int(w * s), int(h * s)),
                               interpolation=cv2.INTER_AREA)
            truth = load_truth(p, s)
            if not truth:
                continue
            n += 1

            gray = cv2.GaussianBlur(
                cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (3, 3), 0)
            roi = plate_roi(gray, "petri")

            out = model.eval(
                small,
                diameter=(args.diameter or None),
                flow_threshold=args.flow,
                cellprob_threshold=args.cellprob,
            )
            masks = out[0]

            # 마스크 라벨별 중심. 접시 ROI 밖은 blob 경로와 같게 제외.
            centres = []
            for lbl in range(1, int(masks.max()) + 1):
                ys, xs = np.nonzero(masks == lbl)
                if len(xs) < 4:
                    continue
                cx, cy = float(xs.mean()), float(ys.mean())
                yi = int(min(max(cy, 0), roi.shape[0] - 1))
                xi = int(min(max(cx, 0), roi.shape[1] - 1))
                if roi[yi, xi] == 0:
                    continue
                centres.append((cx, cy))

            gt += len(truth)
            det += len(centres)
            tp += match(centres, truth)

            # 같은 이미지에 blob 경로도 돌려 나란히 비교한다
            from app.blob_detector import detect_blobs
            b = detect_blobs(img)
            bt = match([(x * s, y * s) for x, y, _r, _c, _f in b], truth)
            bgt += len(truth); bdet += len(b); btp += bt
            print(f"    {os.path.basename(p):14s} 정답{len(truth):4d} | "
                  f"cellpose {len(centres):4d}/{match(centres, truth):4d} | "
                  f"blob {len(b):4d}/{bt:4d}", flush=True)

        pr = tp / det * 100 if det else 0.0
        rc = tp / gt * 100 if gt else 0.0
        el = (time.time() - t0) / max(1, n)
        bpr = btp / bdet * 100 if bdet else 0.0
        brc = btp / bgt * 100 if bgt else 0.0
        print(f"{os.path.basename(grp):18s} {gt:5d} {det:6d} {tp:5d} "
              f"{pr:7.1f}% {rc:7.1f}% {el:6.1f}"
              f"   | blob {bpr:5.1f}%/{brc:5.1f}%")
        TT += tp
        TD += det
        TG += gt

    pr = TT / TD * 100 if TD else 0.0
    rc = TT / TG * 100 if TG else 0.0
    f1 = 2 * pr * rc / (pr + rc) if pr + rc else 0.0
    print()
    print(f"전체  정답 {TG} / 검출 {TD} / 맞힘 {TT}")
    print(f"정밀도 {pr:.2f}%   재현율 {rc:.1f}%   F1 {f1:.1f}")
    print()
    print("비교 대상 (같은 39장·같은 매칭): blob 경로 정밀도 92.89% / 재현율 55.4% / F1 69.4")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
