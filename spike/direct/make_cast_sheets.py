"""Contact sheets for the cast pass: the whole strip, gutters collapsed, tiled, labelled with strip y.

Run: .venv\\Scripts\\python.exe spike\\direct\\make_cast_sheets.py <images_folder> <run_dir>
Writes <run_dir>/cast/sheet_NN.png and <run_dir>/cast/index.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "detect"))
from strip import Strip  # noqa: E402

TILE_H = 3000      # collapsed-strip rows per tile
TILES_PER_SHEET = 6
SCALE = 0.45
SEP = 24


def main(images: Path, run: Path) -> None:
    strip = Strip(images)
    seg = json.loads((run / "segments.json").read_text(encoding="utf-8"))["segments"]
    out = run / "cast"
    out.mkdir(exist_ok=True)

    # collapsed strip as a list of (orig_y0, orig_y1) pieces, read lazily per tile
    pieces: list[tuple[int, int]] = [(a, b) for a, b in seg]
    total = sum(b - a for a, b in pieces)

    def collapsed_rows(c0: int, c1: int) -> tuple[np.ndarray, int, int]:
        parts, o_first, o_last, pos = [], None, None, 0
        for a, b in pieces:
            h = b - a
            lo, hi = max(c0, pos), min(c1, pos + h)
            if lo < hi:
                ya, yb = a + (lo - pos), a + (hi - pos)
                parts.append(strip.crop(ya, yb))
                parts.append(np.full((SEP, strip.width, 3), 200, np.uint8))
                o_first = ya if o_first is None else o_first
                o_last = yb
            pos += h
            if pos >= c1:
                break
        return np.vstack(parts)[:, :, ::-1], o_first or 0, o_last or 0

    tiles = []
    for c0 in range(0, total, TILE_H):
        img, o0, o1 = collapsed_rows(c0, c0 + TILE_H)
        img = cv2.resize(np.ascontiguousarray(img), None, fx=SCALE, fy=SCALE, interpolation=cv2.INTER_AREA)
        label = f"y {o0}-{o1}"
        bar = np.full((22, img.shape[1], 3), 255, np.uint8)
        cv2.putText(bar, label, (2, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1)
        tiles.append((np.vstack([bar, img]), label))

    index = []
    for s, i in enumerate(range(0, len(tiles), TILES_PER_SHEET), 1):
        group = tiles[i : i + TILES_PER_SHEET]
        h = max(t.shape[0] for t, _ in group)
        row = [np.vstack([t, np.full((h - t.shape[0], t.shape[1], 3), 255, np.uint8)]) for t, _ in group]
        gap = np.full((h, 8, 3), 120, np.uint8)
        sheet = row[0]
        for r in row[1:]:
            sheet = np.hstack([sheet, gap, r])
        name = f"sheet_{s:02d}.png"
        cv2.imwrite(str(out / name), sheet)
        index.append({"sheet": name, "tiles": [lab for _, lab in group], "size": [sheet.shape[1], sheet.shape[0]]})
    (out / "index.json").write_text(json.dumps(index, indent=1), encoding="utf-8")
    print(f"{len(tiles)} tiles -> {len(index)} sheets; sheet size {index[0]['size']}")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
