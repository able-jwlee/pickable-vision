"""라벨된 이미지 디렉터리에 대해 검출 정밀도/재현율을 측정한다.

라벨 형식: 이미지와 같은 이름의 .json 에 아래 구조.
    {
      "colonies_number": 19,
      "labels": [{"class": "B.subtilis", "x": 300, "y": 915,
                  "width": 244, "height": 244}, ...]
    }
`x`, `y` 는 바운딩 박스의 **좌상단** (시각 확인 완료).

검출 중심이 정답 박스 안에 들어오면 true positive. 정답 하나당 검출 하나만
인정한다(가장 가까운 것 우선, 탐욕적 1:1 매칭).

사용:
    .venv\\Scripts\\python scripts/evaluate_labeled.py sample
    .venv\\Scripts\\python scripts/evaluate_labeled.py sample --json out.json
    .venv\\Scripts\\python scripts/evaluate_labeled.py sample --param min_size=80
    .venv\\Scripts\\python scripts/evaluate_labeled.py sample --param plate_type=petri

반드시 vision/ 디렉터리에서 실행한다 (서버에 image_path 를 상대 경로로 넘김).
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_labels(json_path: str) -> list[dict]:
    """정답 박스를 (중심, 경계) 형태로 읽는다. labels 가 비면 빈 리스트."""
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)
    out = []
    for label in data.get("labels") or []:
        x, y = label["x"], label["y"]
        w, h = label["width"], label["height"]
        out.append({
            "x0": x, "y0": y, "x1": x + w, "y1": y + h,
            "cx": x + w / 2, "cy": y + h / 2, "r": w / 2,
            "cls": label.get("class", ""),
        })
    return out


def match(detections: list[dict], truth: list[dict]) -> dict:
    """검출 중심이 정답 박스 안이면 매칭. 정답 하나당 하나만 인정."""
    used = [False] * len(truth)
    tp = 0
    for det in detections:
        best, best_dist = -1, None
        for i, g in enumerate(truth):
            if used[i]:
                continue
            if not (g["x0"] <= det["x"] <= g["x1"] and g["y0"] <= det["y"] <= g["y1"]):
                continue
            dist = (det["x"] - g["cx"]) ** 2 + (det["y"] - g["cy"]) ** 2
            if best_dist is None or dist < best_dist:
                best, best_dist = i, dist
        if best >= 0:
            used[best] = True
            tp += 1

    precision = tp / len(detections) if detections else 0.0
    recall = tp / len(truth) if truth else 0.0
    f1 = (2 * precision * recall / (precision + recall)
          if precision + recall else 0.0)
    return {"tp": tp, "fp": len(detections) - tp, "fn": len(truth) - tp,
            "precision": precision, "recall": recall, "f1": f1}


def random_baseline(detections: int, truth: list[dict], w: int, h: int) -> float:
    """같은 개수의 점을 균등하게 뿌렸을 때 적중이 기대되는 정답 개수.

    검출기가 무작위보다 나은지 판단하는 기준. 이 값보다 TP가 낮으면
    검출기가 정답을 체계적으로 피하고 있다는 뜻이다.
    """
    area = w * h
    return sum(
        1 - (1 - (g["x1"] - g["x0"]) * (g["y1"] - g["y0"]) / area) ** detections
        for g in truth
    )


def parse_params(pairs: list[str]) -> dict:
    """--param key=value 를 요청 dict 로. true/false/숫자를 변환한다."""
    out: dict = {}
    for pair in pairs:
        if "=" not in pair:
            raise SystemExit(f"--param 은 key=value 형식이어야 합니다: {pair}")
        key, raw = pair.split("=", 1)
        low = raw.lower()
        if low in ("true", "false"):
            out[key] = low == "true"
        else:
            try:
                out[key] = int(raw) if raw.isdigit() else float(raw)
            except ValueError:
                out[key] = raw
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("directory", help="이미지+라벨 json 이 있는 디렉터리 (재귀 탐색)")
    ap.add_argument("--param", action="append", default=[],
                    metavar="KEY=VALUE", help="검출 요청에 추가할 파라미터")
    ap.add_argument("--json", dest="json_out", help="이미지별 결과를 저장할 경로")
    args = ap.parse_args()

    extra = parse_params(args.param)

    from fastapi.testclient import TestClient  # 서버 없이 인프로세스 호출
    from main import app
    client = TestClient(app)

    paths = sorted(
        p.replace(os.sep, "/")
        for ext in ("jpg", "jpeg", "png")
        for p in glob.glob(f"{args.directory}/**/*.{ext}", recursive=True)
    )
    if not paths:
        print(f"이미지를 찾을 수 없습니다: {args.directory}")
        return 1

    rows = []
    skipped = 0
    print(f"파라미터: {extra or '기본값'}")
    print(f"{'image':16s} {'정답':>5s} {'검출':>6s} {'TP':>5s} "
          f"{'정밀도':>8s} {'재현율':>8s} {'무작위':>7s} {'초':>5s}")

    for path in paths:
        truth = load_labels(path.rsplit(".", 1)[0] + ".json") \
            if os.path.exists(path.rsplit(".", 1)[0] + ".json") else []
        if not truth:
            skipped += 1
            continue

        started = time.time()
        resp = client.post("/detect", json={"image_path": path, **extra})
        elapsed = time.time() - started
        if resp.status_code != 200:
            print(f"{os.path.basename(path):16s} HTTP {resp.status_code} "
                  f"{resp.text[:120]}")
            continue

        data = resp.json()
        m = match(data["colonies"], truth)
        exp = random_baseline(data["count"], truth, data["width"], data["height"])
        rows.append({"name": os.path.basename(path), "gt": len(truth),
                     "det": data["count"], "random_expected_tp": exp,
                     "width": data["width"], "height": data["height"], **m})
        print(f"{os.path.basename(path):16s} {len(truth):5d} {data['count']:6d} "
              f"{m['tp']:5d} {m['precision'] * 100:7.2f}% {m['recall'] * 100:7.1f}% "
              f"{exp:7.0f} {elapsed:5.1f}", flush=True)

    if not rows:
        print("라벨된 이미지가 없습니다.")
        return 1

    tp = sum(r["tp"] for r in rows)
    det = sum(r["det"] for r in rows)
    gt = sum(r["gt"] for r in rows)
    exp = sum(r["random_expected_tp"] for r in rows)

    print(f"\n=== {len(rows)}장 합계 (라벨 없어 건너뜀: {skipped}장) ===")
    print(f"정답 {gt}개 / 검출 {det}개 / 맞힘 {tp}개")
    print(f"정밀도 {tp / det * 100:.2f}%   재현율 {tp / gt * 100:.1f}%")
    print(f"무작위 산포 기대 재현율 {exp / gt * 100:.1f}% "
          f"({'검출기가 무작위보다 나쁨' if tp < exp else '검출기가 무작위보다 나음'})")

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(rows, f, indent=2, ensure_ascii=False)
        print(f"이미지별 결과 저장: {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
