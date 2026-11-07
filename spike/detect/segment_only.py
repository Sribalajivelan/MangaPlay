"""Gutter segmentation only (no ML, no model loading). Writes segments.json and overlay chunks.

Run: .venv\\Scripts\\python.exe spike\\detect\\segment_only.py <images_folder> <out_dir>
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from segment import find_gutters, segments_from_gutters, uniform_rows  # noqa: E402
from strip import Strip  # noqa: E402


def main(images: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    strip = Strip(images)
    t0 = time.perf_counter()
    flags = uniform_rows(strip)
    gutters = find_gutters(flags)
    segments = segments_from_gutters(strip.height, gutters)
    dt = time.perf_counter() - t0
    heights = sorted(b - a for a, b in segments)
    print(f"strip {strip.width}x{strip.height}, {len(strip.slices)} slices")
    print(f"uniform rows: {int(flags.sum())} ({flags.mean()*100:.1f}%)")
    print(f"gutters: {len(gutters)}; segments: {len(segments)}; {dt:.1f}s")
    if heights:
        print(f"segment height min/median/max: {heights[0]}/{heights[len(heights)//2]}/{heights[-1]}")
    (out / "segments.json").write_text(json.dumps(
        {"strip": strip.manifest(), "gutters": gutters, "segments": segments}, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
