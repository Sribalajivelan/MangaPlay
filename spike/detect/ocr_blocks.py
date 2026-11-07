"""Track B (safe path): text lines via ONNX OCR over a virtual strip, grouped into text blocks.

Run: .venv\\Scripts\\python.exe spike\\detect\\ocr_blocks.py <images_folder> <out_dir>
Writes <out_dir>/ocr.json with raw lines and grouped blocks (strip coordinates).
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import numpy as np
from rapidocr_onnxruntime import RapidOCR

sys.path.insert(0, str(Path(__file__).resolve().parent))
from strip import Strip  # noqa: E402

WINDOW = 1600
OVERLAP = 300
EDGE = 6          # px: a line touching a window edge may be cut, drop it if another window will see it whole
MIN_SCORE = 0.55


def bbox_of(poly) -> list[int]:
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return [int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))]


def is_english_like(text: str) -> bool:
    """Keep lines that look like English; drop CJK/garbage from untranslated SFX."""
    if re.search(r"[　-鿿가-힯]", text):
        return False
    letters = re.findall(r"[A-Za-z]", text)
    return len(letters) >= 2 or bool(re.fullmatch(r"[A-Za-z][?!.\-—…]*", text.strip()))


def iou(a, b) -> float:
    ix0, iy0, ix1, iy1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, ix1 - ix0) * max(0, iy1 - iy0)
    if not inter:
        return 0.0
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua


def dedupe(lines: list[dict]) -> list[dict]:
    lines = sorted(lines, key=lambda d: -d["score"])
    kept: list[dict] = []
    for d in lines:
        if not any(iou(d["box"], k["box"]) > 0.5 for k in kept):
            kept.append(d)
    return sorted(kept, key=lambda d: (d["box"][1], d["box"][0]))


def group_blocks(lines: list[dict]) -> list[dict]:
    """Union stacked, horizontally-overlapping lines whose vertical gap is small."""
    n = len(lines)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        a = lines[i]["box"]
        ha = a[3] - a[1]
        for j in range(i + 1, n):
            b = lines[j]["box"]
            if b[1] - a[3] > 1.2 * ha + 6:
                break  # sorted by y: nothing further can be close
            hb = b[3] - b[1]
            gap = b[1] - a[3]
            h = (ha + hb) / 2
            overlap_x = min(a[2], b[2]) - max(a[0], b[0])
            ca, cb = (a[0] + a[2]) / 2, (b[0] + b[2]) / 2
            width = max(a[2] - a[0], b[2] - b[0])
            similar_height = 0.6 < ha / max(hb, 1) < 1.67
            if gap < 0.9 * h and overlap_x > 0 and abs(ca - cb) < 0.45 * width and similar_height:
                parent[find(j)] = find(i)

    groups: dict[int, list[dict]] = {}
    for i, d in enumerate(lines):
        groups.setdefault(find(i), []).append(d)
    blocks = []
    for g in groups.values():
        g = sorted(g, key=lambda d: (d["box"][1], d["box"][0]))
        box = [min(d["box"][0] for d in g), min(d["box"][1] for d in g), max(d["box"][2] for d in g), max(d["box"][3] for d in g)]
        blocks.append({
            "box": box,
            "text": " ".join(d["text"].strip() for d in g),
            "n_lines": len(g),
            "score": round(float(np.mean([d["score"] for d in g])), 3),
        })
    blocks.sort(key=lambda b: (b["box"][1], b["box"][0]))
    for i, b in enumerate(blocks, 1):
        b["id"] = f"t{i:03d}"
    return blocks


def main(images: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    strip = Strip(images)
    ocr = RapidOCR()
    raw: list[dict] = []
    n_windows = 0
    t0 = time.perf_counter()
    y = 0
    while y < strip.height:
        y1 = min(strip.height, y + WINDOW)
        img = np.ascontiguousarray(strip.crop(y, y1)[:, :, ::-1])
        res, _ = ocr(img, use_cls=False)
        n_windows += 1
        for poly, text, score in (res or []):
            score = float(score)
            b = bbox_of(poly)
            touches_top = b[1] <= EDGE and y > 0
            touches_bot = b[3] >= (y1 - y) - EDGE and y1 < strip.height
            if touches_top or touches_bot:
                continue
            if score < MIN_SCORE or not is_english_like(text):
                continue
            raw.append({"box": [b[0], b[1] + y, b[2], b[3] + y], "text": text, "score": round(score, 3)})
        if y1 >= strip.height:
            break
        y = y1 - OVERLAP
        if n_windows % 10 == 0:
            print(f"  {n_windows} windows, {time.perf_counter()-t0:.0f}s, y={y}")
    dt = time.perf_counter() - t0
    lines = dedupe(raw)
    blocks = group_blocks(lines)
    print(f"{n_windows} windows in {dt:.0f}s ({dt/(strip.height/1000):.2f}s per 1000px); raw lines {len(raw)} -> {len(lines)}; blocks {len(blocks)}")
    (out / "ocr.json").write_text(json.dumps({
        "strip": strip.manifest(), "lines": lines, "blocks": blocks,
        "params": {"window": WINDOW, "overlap": OVERLAP, "min_score": MIN_SCORE, "seconds": round(dt, 1)},
    }, indent=1, ensure_ascii=False), encoding="utf-8")
    print("wrote", out / "ocr.json")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
