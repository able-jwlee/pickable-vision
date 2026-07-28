"""원형 페트리 접시 ROI 검출 + 명암 극성 추정 프로토타입.

`app/plates/petri.py` 로 옮길 예정인 로직의 검증본이다. 스펙 §3.4 참조:
docs/superpowers/specs/2026-07-28-plate-strategy-design.md

라벨 39장 실측 (2026-07-28):
  - 접시 검출 성공 26/39, 실패 시 전체 이미지 폴백
  - 성공 시 배경 41~64% 제거, ROI 밖으로 잘린 정답 콜로니 대부분 0%
  - 극성 추정 정확도 30/39 (틀린 9장은 전부 대비 ±1 계조 이하)
  - 검출에 적용 시 정밀도 0.55% -> 0.82%, 재현율 44.1% -> 43.6%

사용:
    .venv\\Scripts\\python scripts/petri_roi_prototype.py sample
    .venv\\Scripts\\python scripts/petri_roi_prototype.py sample --dump out/roi
"""
from __future__ import annotations

import argparse
import glob
import json
import os

import cv2
import numpy as np

# 접시 채택 조건
FILL_MIN = 0.85          # 윤곽 면적 / 최소외접원 면적 — 원에 얼마나 꽉 찼나
RADIUS_MIN_RATIO = 0.15  # 반지름이 긴 변의 이 비율보다 커야 함
RADIUS_MAX_RATIO = 0.75  # 이 비율보다 작아야 함
RIM_MARGIN_RATIO = 0.93  # 테두리 링 제외를 위해 반지름을 이만큼으로 수축
DOWNSCALE_TO = 1000      # 원 탐색용 다운스케일 (긴 변)


def petri_roi(gray: np.ndarray) -> tuple[np.ndarray, bool, tuple | None]:
    """원형 접시 내부 마스크를 만든다.

    반환: (마스크 255=대상, 접시를 찾았는지, (cx, cy, r) 또는 None)

    접시를 못 찾으면 전체 이미지 마스크를 반환한다 — ROI 없는 현재 동작과
    같아지므로 손해가 없다. 호출자는 두 번째 반환값으로 판별한다.
    """
    h, w = gray.shape
    scale = DOWNSCALE_TO / max(h, w)
    small = cv2.resize(gray, (int(w * scale), int(h * scale)))
    small = cv2.GaussianBlur(small, (5, 5), 0)
    _, binary = cv2.threshold(small, 0, 255,
                              cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # 접시가 배경보다 밝을 수도 어두울 수도 있으므로 양 극성 모두 시도해
    # 더 원에 가까운 쪽을 고른다.
    best = None
    for candidate in (binary, cv2.bitwise_not(binary)):
        closed = cv2.morphologyEx(candidate, cv2.MORPH_CLOSE,
                                  np.ones((15, 15), np.uint8))
        contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            continue
        contour = max(contours, key=cv2.contourArea)
        (cx, cy), r = cv2.minEnclosingCircle(contour)
        circle_area = np.pi * r * r
        fill = cv2.contourArea(contour) / circle_area if circle_area else 0.0
        if best is None or fill > best[0]:
            best = (fill, cx, cy, r)

    full = np.full(gray.shape, 255, np.uint8)
    if best is None:
        return full, False, None

    fill, cx, cy, r = best
    cx, cy, r = cx / scale, cy / scale, r / scale
    long_side = max(h, w)
    found = (fill > FILL_MIN
             and long_side * RADIUS_MIN_RATIO < r < long_side * RADIUS_MAX_RATIO)
    if not found:
        return full, False, (cx, cy, r)

    mask = np.zeros(gray.shape, np.uint8)
    cv2.circle(mask, (int(cx), int(cy)), int(r * RIM_MARGIN_RATIO), 255, -1)
    return mask, True, (cx, cy, r)


def estimate_invert(gray: np.ndarray, roi: np.ndarray) -> bool:
    """ROI 안 밝기 분포의 치우침으로 명암 극성을 추정한다.

    콜로니는 소수 픽셀이므로, 콜로니가 배경보다 밝으면 분포가 오른쪽으로
    꼬리를 달아 mean > median 이 된다. 그 경우 밝은 것을 살리는 top-hat
    (invert=False)이 맞다.

    실측 정확도 30/39. 대비가 ±1 계조 이하인 이미지에서는 신뢰할 수 없으므로,
    확실한 경로는 요청에서 invert 를 명시하는 것이다.
    """
    values = gray[roi > 0]
    if values.size == 0:
        return True
    return not (float(values.mean()) > float(np.median(values)))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("directory", help="이미지 디렉터리 (재귀 탐색)")
    ap.add_argument("--dump", help="ROI 를 그린 확인용 이미지를 저장할 디렉터리")
    args = ap.parse_args()

    if args.dump:
        os.makedirs(args.dump, exist_ok=True)

    paths = sorted(p.replace(os.sep, "/")
                   for p in glob.glob(f"{args.directory}/**/*.jpg", recursive=True))
    found_count = 0
    print(f"{'image':16s} {'접시':>5s} {'배경제거':>9s} {'극성추정':>9s} {'ROI밖 정답':>11s}")

    for path in paths:
        gray = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        if gray is None:
            continue
        mask, found, circle = petri_roi(gray)
        found_count += found
        invert = estimate_invert(gray, mask)
        shrink = 1 - (mask > 0).sum() / mask.size

        # 라벨이 있으면 ROI 가 콜로니를 잘라먹는지 확인
        outside = "-"
        json_path = path[:-4] + ".json"
        if os.path.exists(json_path):
            labels = json.load(open(json_path, encoding="utf-8")).get("labels") or []
            if labels:
                out = sum(
                    1 for L in labels
                    if mask[min(max(L["y"] + L["height"] // 2, 0), gray.shape[0] - 1),
                            min(max(L["x"] + L["width"] // 2, 0), gray.shape[1] - 1)] == 0
                )
                outside = f"{out / len(labels) * 100:.1f}%"

        print(f"{os.path.basename(path):16s} {('O' if found else 'X'):>5s} "
              f"{shrink * 100:8.0f}% {('어두움' if invert else '밝음'):>9s} "
              f"{outside:>11s}")

        if args.dump:
            vis = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
            vis[mask == 0] = (vis[mask == 0] * 0.35).astype(np.uint8)
            if circle:
                cx, cy, r = circle
                cv2.circle(vis, (int(cx), int(cy)), int(r), (0, 0, 255), 6)
            s = 900 / max(vis.shape[:2])
            cv2.imwrite(f"{args.dump}/{os.path.basename(path)}",
                        cv2.resize(vis, (int(vis.shape[1] * s), int(vis.shape[0] * s))),
                        [cv2.IMWRITE_JPEG_QUALITY, 85])

    print(f"\n접시 검출 성공 {found_count}/{len(paths)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
