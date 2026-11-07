"""Windowed bubble detection over a virtual strip, with seam merging.

Run: .venv\\Scripts\\python.exe spike\\detect\\detect_bubbles.py <images_folder> <out_dir>
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ultralytics import YOLO  # noqa: E402

from segment import find_gutters, segments_from_gutters, uniform_rows  # noqa: E402
from strip import Strip  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / ".cache" / "detector" / "comic-speech-bubble-detector.pt"

WINDOW = 1600
OVERLAP = 300
CONF = 0.25
IMGSZ = 1024


def area(b):
    return max(0, b[2] - b[0]) * max(0, b[3] - b[1])


def inter(a, b):
    return area((max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])))


def merge_boxes(dets: list[dict]) -> list[dict]:
    """Union boxes that substantially overlap (same bubble seen in two windows, or cut by a seam)."""
    dets = sorted(dets, key=lambda d: d["box"][1])
    merged: list[dict] = []
    for d in dets:
        for m in merged:
            i = inter(d["box"], m["box"])
            if i and i / min(area(d["box"]), area(m["box"])) > 0.5:
                m["box"] = [
                    min(m["box"][0], d["box"][0]), min(m["box"][1], d["box"][1]),
                    max(m["box"][2], d["box"][2]), max(m["box"][3], d["box"][3]),
                ]
                m["conf"] = max(m["conf"], d["conf"])
                break
        else:
            merged.append(dict(d))
    return sorted(merged, key=lambda d: (d["box"][1], d["box"][0]))


def main(images: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    strip = Strip(images)
    print(f"strip {strip.width}x{strip.height}, {len(strip.slices)} slices")

    t0 = time.perf_counter()
    flags = uniform_rows(strip)
    gutters = find_gutters(flags)
    segments = segments_from_gutters(strip.height, gutters)
    print(f"gutters: {len(gutters)}, segments: {len(segments)}  ({time.perf_counter()-t0:.1f}s)")

    model = YOLO(str(MODEL))
    print("classes:", model.names)

    raw: list[dict] = []
    t0 = time.perf_counter()
    y = 0
    n_windows = 0
    while y < strip.height:
        y1 = min(strip.height, y + WINDOW)
        img = strip.crop(y, y1)[:, :, ::-1]  # RGB -> BGR for ultralytics numpy input
        res = model.predict(img, imgsz=IMGSZ, conf=CONF, device="cpu", verbose=False)[0]
        for b, c, k in zip(res.boxes.xyxy.tolist(), res.boxes.conf.tolist(), res.boxes.cls.tolist()):
            raw.append({"box": [b[0], b[1] + y, b[2], b[3] + y], "conf": c, "cls": int(k)})
        n_windows += 1
        if y1 >= strip.height:
            break
        y = y1 - OVERLAP
    dt = time.perf_counter() - t0
    bubbles = merge_boxes(raw)
    for i, b in enumerate(bubbles, 1):
        b["id"] = f"b{i:03d}"
        b["box"] = [round(v) for v in b["box"]]
        b["conf"] = round(b["conf"], 3)
    print(f"{n_windows} windows in {dt:.1f}s ({dt/(strip.height/1000):.2f}s per 1000px); raw={len(raw)} merged={len(bubbles)}")

    (out / "detect.json").write_text(json.dumps({
        "strip": strip.manifest(),
        "gutters": gutters,
        "segments": segments,
        "bubbles": bubbles,
        "params": {"window": WINDOW, "overlap": OVERLAP, "conf": CONF, "imgsz": IMGSZ, "seconds": round(dt, 1)},
    }, indent=1), encoding="utf-8")
    print("wrote", out / "detect.json")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
