"""sample/ 전체를 검출 결과와 함께 그려 output/annotated/ 에 저장한다.

두 가지 뷰를 만든다.

**진단 뷰** (`output/annotated/`) — 정답과 대조한다.
    초록 사각형   = 맞힌 정답 (검출과 매칭됨)
    마젠타 사각형 = 놓친 정답 (FN) — 굵게 그려 눈에 띄게 한다
    노란 원       = 맞힌 검출 (TP)
    빨간 원       = 오검출 (FP)

정답 박스를 매칭 여부와 무관하게 한 색으로 그리면, 놓친 콜로니도 박스가 씌워져
있어 검출된 것처럼 보인다. 실제로 그 때문에 오검출과 미검출을 혼동하는 일이
있었으므로 놓친 것을 반드시 다른 색으로 구분한다.

**검출 전용 뷰** (`output/annotated/plain/`) — 오퍼레이터 UI 와 같은 화면.
초록 원만 그린다. 정답을 모르는 상태에서 결과가 어떻게 보이는지 확인하는 용도이고,
다른 도구(OpenCFU 등)의 출력과 나란히 비교할 때 이쪽을 쓴다.

`--gallery` 를 주면 두 뷰를 나란히 놓고 재현율이 나쁜 순으로 정렬한
`output/annotated/index.html` 을 만든다. 40장을 폴더에서 하나씩 여는 것보다
문제 있는 접시를 훨씬 빨리 찾을 수 있다.

사용:
    .venv\\Scripts\\python scripts/annotate_samples.py
    .venv\\Scripts\\python scripts/annotate_samples.py --thumb 420   # 축소본도 저장
    .venv\\Scripts\\python scripts/annotate_samples.py --thumb 460 --gallery
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from app import config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from main import app  # noqa: E402

# 검출기를 직접 부르지 않고 실제 엔드포인트를 거친다. 직접 호출하면 API 가
# 적용하는 파라미터 해석(_resolve_params)을 건너뛰어, 여기서 본 그림과
# 오퍼레이터가 UI 에서 보는 그림이 달라질 수 있다. scripts/evaluate_labeled.py
# 와 같은 경로라 두 스크립트의 수치가 항상 일치한다.
CLIENT = TestClient(app)

GROUPS = [
    "sample/lower-resolution",
    "sample/higher-resolution/bright",
    "sample/higher-resolution/dark",
    "sample/higher-resolution/vague",
]


def load_truth(img_path: str):
    j = img_path.rsplit(".", 1)[0] + ".json"
    if not os.path.exists(j):
        return []
    data = json.load(open(j, encoding="utf-8"))
    return [
        (l["x"], l["y"], l["x"] + l["width"], l["y"] + l["height"])
        for l in (data.get("labels") or [])
    ]


def split_tp_fp(dets, truth):
    """검출 중심이 정답 박스 안이면 TP. 정답 하나당 하나만 인정(가까운 것 우선)."""
    used = [False] * len(truth)
    is_tp = [False] * len(dets)
    for i, (x, y, *_rest) in enumerate(dets):
        best, bd = -1, None
        for k, (x0, y0, x1, y1) in enumerate(truth):
            if used[k] or not (x0 <= x <= x1 and y0 <= y <= y1):
                continue
            d = (x - (x0 + x1) / 2) ** 2 + (y - (y0 + y1) / 2) ** 2
            if bd is None or d < bd:
                best, bd = k, d
        if best >= 0:
            used[best] = True
            is_tp[i] = True
    return is_tp, used


def parse_params(pairs: list[str]) -> dict:
    """`--param key=value` 들을 요청 dict 으로. 숫자/불리언은 형변환한다."""
    out: dict = {}
    for pair in pairs:
        k, _, v = pair.partition("=")
        if v.lower() in ("true", "false"):
            out[k] = v.lower() == "true"
        else:
            try:
                out[k] = int(v) if v.lstrip("-").isdigit() else float(v)
            except ValueError:
                out[k] = v
    return out


def detect_via_api(rel_path: str, params: dict) -> list[tuple]:
    """POST /detect 로 검출해 (x, y, radius, circularity) 리스트를 돌려준다.

    좌표는 원본 픽셀 기준이다(응답 규약). 실패하면 예외를 올린다 — 조용히
    빈 리스트를 돌려주면 "검출 0개"로 보여서 알고리즘 문제로 오해하게 된다.
    """
    r = CLIENT.post("/detect", json={"image_path": rel_path, **params})
    if r.status_code != 200:
        raise RuntimeError(f"{rel_path}: HTTP {r.status_code} {r.text[:200]}")
    return [(c["x"], c["y"], c["radius"], c.get("circularity") or 0.0)
            for c in r.json()["colonies"]]


def write_gallery(outdir: Path, rows: list[dict], params: dict) -> None:
    """재현율이 나쁜 순으로 정렬한 비교 갤러리를 만든다.

    나쁜 순 정렬이 핵심이다. 파일명 순으로 두면 잘 되는 접시부터 보게 되어
    "대체로 괜찮네"라는 인상을 받고 정작 문제를 못 본다.
    """
    gt = sum(r["gt"] for r in rows)
    det = sum(r["det"] for r in rows)
    tp = sum(r["tp"] for r in rows)

    cards = []
    for r in sorted(rows, key=lambda r: r["recall"]):
        f = f"{r['group']}__{r['name']}"
        cards.append(f"""
  <figure class="card">
    <figcaption>
      <b>{r['name']}</b> <span class="grp">{r['group']}</span>
      <span class="rc {'bad' if r['recall'] < 50 else 'mid' if r['recall'] < 75 else 'ok'}">
        재현율 {r['recall']}%</span>
      <span class="nums">정답 {r['gt']} · 검출 {r['det']} · 맞힘 {r['tp']}
        · 오검출 {r['fp']} · <b class="fn">놓침 {r['fn']}</b>
        · 정밀도 {r['precision']}%</span>
    </figcaption>
    <div class="pair">
      <a href="plain/{f}" target="_blank"><img src="plain/thumb/{f}" loading="lazy">
        <span>검출 전용 (UI 화면)</span></a>
      <a href="{f}" target="_blank"><img src="thumb/{f}" loading="lazy">
        <span>정답 대조</span></a>
    </div>
  </figure>""")

    html = f"""<!doctype html><meta charset="utf-8">
<title>sample/ 검출 결과 — {len(rows)}장</title>
<style>
 body{{background:#0f1115;color:#e6e8ee;font:14px/1.5 system-ui,sans-serif;margin:0;padding:24px}}
 h1{{font-size:19px;margin:0 0 4px}}
 .tot{{color:#9aa3b2;margin-bottom:20px}}
 .tot b{{color:#e6e8ee}}
 .legend{{background:#171a21;border:1px solid #262b36;border-radius:8px;
   padding:10px 14px;margin-bottom:22px;color:#9aa3b2;font-size:13px}}
 .legend i{{font-style:normal;font-weight:600}}
 .card{{margin:0 0 26px;background:#171a21;border:1px solid #262b36;border-radius:10px;padding:12px}}
 figcaption{{margin-bottom:9px}}
 .grp{{color:#7c8698;margin-left:6px}}
 .rc{{margin-left:10px;padding:1px 8px;border-radius:99px;font-weight:600}}
 .rc.bad{{background:#4a1520;color:#ff9db0}}
 .rc.mid{{background:#4a3a15;color:#ffd79d}}
 .rc.ok{{background:#14401f;color:#93e6a8}}
 .nums{{display:block;color:#9aa3b2;margin-top:3px;font-size:13px}}
 .fn{{color:#ff9db0}}
 .pair{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}
 .pair a{{color:#7c8698;text-decoration:none;font-size:12px}}
 .pair img{{width:100%;border-radius:6px;display:block;background:#000}}
 .pair span{{display:block;margin-top:5px}}
 @media(max-width:900px){{.pair{{grid-template-columns:1fr}}}}
</style>
<h1>sample/ 검출 결과 — {len(rows)}장</h1>
<p class="tot">정답 <b>{gt}</b> · 검출 <b>{det}</b> · 맞힘 <b>{tp}</b> ·
 정밀도 <b>{tp / det * 100:.1f}%</b> · 재현율 <b>{tp / gt * 100:.1f}%</b>
 &nbsp;— 재현율이 나쁜 순으로 정렬</p>
<div class="legend">
 <i style="color:#ff5cf0">마젠타 사각형</i> = 놓친 정답 ·
 <i style="color:#3cff3c">초록 사각형</i> = 맞힌 정답 ·
 <i style="color:#ffe23c">노란 원</i> = 맞힌 검출 ·
 <i style="color:#ff5c5c">빨간 원</i> = 오검출
 &nbsp;· 이미지를 클릭하면 원본 해상도로 열립니다
</div>
<div class="legend">
 <i>POST /detect 요청 (40장 전부 동일)</i><br>
 <code style="color:#93e6a8">{json.dumps(params, ensure_ascii=False) or '{}'}</code>
 &nbsp;— 비워둔 필드는 서버 기본값
 (<code>method=blob · polarity=auto · plate_type=petri · sensitivity=50(min_t 35)
  · work_size=1024 · 크기 제한 없음 · colour_credit=1.0</code>)
</div>
{''.join(cards)}
"""
    (outdir / "index.html").write_text(html, encoding="utf-8")
    print(f"갤러리: {outdir / 'index.html'}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--thumb", type=int, default=0,
                    help="이 폭(px)으로 축소본도 저장 (0이면 저장 안 함)")
    ap.add_argument("--quality", type=int, default=85)
    ap.add_argument("--gallery", action="store_true",
                    help="output/annotated/index.html 생성 (--thumb 필요)")
    ap.add_argument("--param", action="append", default=[], metavar="KEY=VALUE",
                    help="모든 이미지에 동일하게 적용할 /detect 파라미터")
    args = ap.parse_args()
    params = parse_params(args.param)
    if args.gallery and not args.thumb:
        args.thumb = 460   # 갤러리는 축소본을 쓴다 — 원본은 브라우저가 못 버틴다

    outdir = ROOT / "output" / "annotated"
    outdir.mkdir(parents=True, exist_ok=True)
    thumbdir = outdir / "thumb"
    plaindir = outdir / "plain"
    plainthumb = plaindir / "thumb"
    for d in (thumbdir, plainthumb) if args.thumb else ():
        d.mkdir(parents=True, exist_ok=True)
    plaindir.mkdir(parents=True, exist_ok=True)

    print(f"POST /detect 요청 파라미터 (전 이미지 동일): "
          f"{json.dumps(params, ensure_ascii=False) if params else '{} (전부 서버 기본값)'}")
    print()

    rows = []
    for grp in GROUPS:
        gname = os.path.basename(grp)
        for p in sorted(glob.glob(f"{grp}/*.jpg")):
            truth = load_truth(p)
            if not truth:
                continue
            img = cv2.imread(p)
            dets = detect_via_api(p, params)
            is_tp, matched = split_tp_fp(dets, truth)

            vis = img.copy()
            # 선 두께를 이미지 크기에 비례시켜 축소해도 보이게 한다
            th = max(2, int(max(img.shape[:2]) / 500))
            for (x0, y0, x1, y1), ok in zip(truth, matched):
                # 놓친 정답은 마젠타로 굵게 — 초록 하나로 그리면 놓친 것도
                # 검출된 것처럼 보인다
                cv2.rectangle(vis, (int(x0), int(y0)), (int(x1), int(y1)),
                              (0, 255, 0) if ok else (255, 0, 255),
                              th if ok else th + 4)
            for (x, y, r, _c), tp in zip(dets, is_tp):
                colour = (0, 255, 255) if tp else (0, 0, 255)
                cv2.circle(vis, (int(x), int(y)),
                           max(int(r), th * 3), colour, th)

            # 검출 전용 뷰 — 정답 없이 UI 가 보여주는 그대로.
            # app/annotate.py 의 draw_for_response 와 **같은 모양**으로 그린다.
            # 여기만 원으로 두면 갤러리와 UI 가 달라 보여 비교가 어긋난다.
            plain = img.copy()
            for (x, y, r, _c) in dets:
                rad = max(int(r * config.DRAW_MARKER_PAD), th * 3)
                cv2.rectangle(plain, (int(x) - rad, int(y) - rad),
                              (int(x) + rad, int(y) + rad), (0, 255, 0), th)

            name = os.path.basename(p)
            cv2.imwrite(str(outdir / f"{gname}__{name}"), vis,
                        [cv2.IMWRITE_JPEG_QUALITY, args.quality])
            cv2.imwrite(str(plaindir / f"{gname}__{name}"), plain,
                        [cv2.IMWRITE_JPEG_QUALITY, args.quality])
            if args.thumb:
                h, w = vis.shape[:2]
                s = args.thumb / w
                for src, dst in ((vis, thumbdir), (plain, plainthumb)):
                    small = cv2.resize(src, (args.thumb, int(h * s)),
                                       interpolation=cv2.INTER_AREA)
                    cv2.imwrite(str(dst / f"{gname}__{name}"), small,
                                [cv2.IMWRITE_JPEG_QUALITY, 62])

            tp = sum(is_tp)
            rows.append({
                "group": gname, "name": name,
                "gt": len(truth), "det": len(dets), "tp": tp,
                "fp": len(dets) - tp, "fn": len(truth) - sum(matched),
                "precision": round(tp / len(dets) * 100, 1) if dets else 0.0,
                "recall": round(tp / len(truth) * 100, 1),
            })
            print(f"{gname:22s} {name:14s} 정답{len(truth):4d} 검출{len(dets):4d} "
                  f"TP{tp:4d} FP{len(dets)-tp:4d} "
                  f"재현율{tp/len(truth)*100:5.1f}%", flush=True)

    with open(outdir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=1, ensure_ascii=False)

    if args.gallery:
        write_gallery(outdir, rows, params)

    gt = sum(r["gt"] for r in rows)
    det = sum(r["det"] for r in rows)
    tp = sum(r["tp"] for r in rows)
    print()
    print(f"=== {len(rows)}장 합계 ===")
    print(f"정답 {gt} / 검출 {det} / 맞힘 {tp}")
    print(f"정밀도 {tp/det*100:.2f}%   재현율 {tp/gt*100:.1f}%")
    print(f"저장 위치: {outdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
