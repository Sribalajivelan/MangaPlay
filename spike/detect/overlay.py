"""Render overlay images: gutters (red), segment index (blue), bubbles (green, if detect.json exists).

Run: .venv\\Scripts\\python.exe spike\\detect\\overlay.py <images_folder> <run_dir> <y0> <y1> [scale]
Writes <run_dir>/overlay_<y0>_<y1>.png
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from strip import Strip  # noqa: E402


def main(images: Path, run: Path, y0: int, y1: int, scale: float) -> None:
    strip = Strip(images)
    seg = json.loads((run / "segments.json").read_text(encoding="utf-8"))
    det_path = run / "detect.json"
    bubbles = json.loads(det_path.read_text(encoding="utf-8"))["bubbles"] if det_path.exists() else []

    img = np.ascontiguousarray(strip.crop(y0, y1)[:, :, ::-1])
    over = img.copy()
    for g0, g1 in seg["gutters"]:
        if g1 > y0 and g0 < y1:
            cv2.rectangle(over, (0, max(g0, y0) - y0), (strip.width, min(g1, y1) - y0), (0, 0, 255), -1)
    img = cv2.addWeighted(over, 0.35, img, 0.65, 0)
    for i, (s0, s1) in enumerate(seg["segments"]):
        if s1 > y0 and s0 < y1:
            cv2.line(img, (0, max(s0, y0) - y0), (strip.width, max(s0, y0) - y0), (255, 0, 0), 2)
            cv2.putText(img, f"S{i}", (4, max(s0, y0) - y0 + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 0, 0), 2)
    for b in bubbles:
        x0, by0, x1, by1 = b["box"]
        if by1 > y0 and by0 < y1:
            cv2.rectangle(img, (x0, by0 - y0), (x1, by1 - y0), (0, 180, 0), 2)
            cv2.putText(img, f'{b["id"]} {b["conf"]:.2f}', (x0, max(14, by0 - y0 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 140, 0), 1)
    ocr_path = run / "ocr.json"
    blocks = json.loads(ocr_path.read_text(encoding="utf-8"))["blocks"] if ocr_path.exists() else []
    for t in blocks:
        x0, ty0, x1, ty1 = t["box"]
        if ty1 > y0 and ty0 < y1:
            cv2.rectangle(img, (x0 - 3, ty0 - y0 - 3), (x1 + 3, ty1 - y0 + 3), (0, 140, 255), 2)
            cv2.putText(img, t["id"], (x0, ty1 - y0 + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 100, 220), 2)
    if scale != 1.0:
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    out = run / f"overlay_{y0}_{y1}.png"
    cv2.imwrite(str(out), img)
    print(out)


if __name__ == "__main__":
    a = sys.argv
    main(Path(a[1]), Path(a[2]), int(a[3]), int(a[4]), float(a[5]) if len(a) > 5 else 0.6)
