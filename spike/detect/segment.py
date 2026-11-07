"""Split a strip into segments at gutters: runs of near-uniform rows."""
from __future__ import annotations

import numpy as np

from strip import Strip


def uniform_rows(strip: Strip, chunk: int = 4000, std_thr: float = 4.0) -> np.ndarray:
    """Boolean per strip row: True when the row is (nearly) a single flat colour."""
    flags = np.zeros(strip.height, dtype=bool)
    for y0 in range(0, strip.height, chunk):
        a = strip.crop(y0, y0 + chunk).astype(np.float32)
        # a flat row has tiny colour variation across its width
        flags[y0 : y0 + a.shape[0]] = a.std(axis=1).max(axis=1) < std_thr
    return flags


def find_gutters(flags: np.ndarray, min_h: int = 60) -> list[tuple[int, int]]:
    """(y0, y1) runs of True at least min_h tall."""
    runs, start = [], None
    for y, f in enumerate(flags):
        if f and start is None:
            start = y
        elif not f and start is not None:
            if y - start >= min_h:
                runs.append((start, y))
            start = None
    if start is not None and len(flags) - start >= min_h:
        runs.append((start, len(flags)))
    return runs


def segments_from_gutters(height: int, gutters: list[tuple[int, int]], min_seg: int = 120) -> list[tuple[int, int]]:
    segs, cur = [], 0
    for g0, g1 in gutters:
        if g0 - cur >= min_seg:
            segs.append((cur, g0))
        cur = g1
    if height - cur >= min_seg:
        segs.append((cur, height))
    return segs
