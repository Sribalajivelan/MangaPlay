"""Virtual webtoon strip: many tall slices addressed as one image in strip coordinates."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

IMG_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


def natural_key(p: Path) -> list:
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", p.name)]


@dataclass(frozen=True)
class Slice:
    path: Path
    y: int  # top of this slice in strip coordinates
    h: int


class Strip:
    def __init__(self, folder: Path):
        files = sorted((p for p in folder.iterdir() if p.suffix.lower() in IMG_EXTS), key=natural_key)
        if not files:
            raise FileNotFoundError(f"no images in {folder}")
        self.slices: list[Slice] = []
        y = 0
        width = None
        for p in files:
            with Image.open(p) as im:
                w, h = im.size
            if width is None:
                width = w
            elif w != width:
                raise ValueError(f"{p.name} is {w}px wide, expected {width}; mixed widths need resizing first")
            self.slices.append(Slice(p, y, h))
            y += h
        self.width: int = width
        self.height: int = y

    def crop(self, y0: int, y1: int) -> np.ndarray:
        """RGB uint8 array for strip rows [y0, y1), composed from whichever slices overlap."""
        y0, y1 = max(0, y0), min(self.height, y1)
        out = np.full((y1 - y0, self.width, 3), 255, dtype=np.uint8)
        for s in self.slices:
            if s.y >= y1 or s.y + s.h <= y0:
                continue
            a, b = max(y0, s.y), min(y1, s.y + s.h)
            with Image.open(s.path) as im:
                arr = np.asarray(im.convert("RGB").crop((0, a - s.y, self.width, b - s.y)))
            out[a - y0 : b - y0] = arr
        return out

    def manifest(self) -> dict:
        return {
            "width": self.width,
            "height": self.height,
            "slices": [{"file": s.path.name, "y": s.y, "h": s.h} for s in self.slices],
        }
