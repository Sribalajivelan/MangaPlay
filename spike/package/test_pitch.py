"""Check that pitch_shift moves the pitch by the requested amount and keeps the duration.

Run: .venv\\Scripts\\python.exe -I spike\\package\\test_pitch.py
Uses two real clips from the bundle (a male and a female voice) plus a synthetic tone.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).parent))
from pitch import median_f0, pitch_shift  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
failures = 0


def check(name: str, ok: bool, detail: str) -> None:
    global failures
    failures += not ok
    print(f"[{'ok' if ok else 'FAIL'}] {name}: {detail}")


# synthetic 150 Hz harmonic tone: known ground truth
sr = 24000
t = np.arange(sr * 2) / sr
tone = sum(np.sin(2 * np.pi * 150 * k * t) / k for k in (1, 2, 3, 4)).astype(np.float32) * 0.2
f_before = median_f0(tone, sr)
for st in (+3.0, -3.0, +1.5):
    out = pitch_shift(tone, sr, st)
    expect = f_before * 2 ** (st / 12)
    got = median_f0(out, sr)
    check(f"tone {st:+.1f} st", abs(got / expect - 1) < 0.03 and abs(len(out) / len(tone) - 1) < 0.02,
          f"f0 {f_before:.0f} -> {got:.0f} Hz (expected {expect:.0f}); length ratio {len(out)/len(tone):.3f}")

# real speech clips
for beat, label in (("b025", "male c2"), ("b085", "female c3")):
    f = ROOT / "bundles" / "ep01" / "audio" / f"{beat}.ogg"
    if not f.exists():
        print(f"(skip {label}: {f.name} missing)")
        continue
    x, rate = sf.read(f, dtype="float32")
    base = median_f0(x, rate)
    for st in (+2.5, -1.5):
        y = pitch_shift(x, rate, st)
        got = median_f0(y, rate)
        exp = base * 2 ** (st / 12)
        check(f"{label} {st:+.1f} st", base > 0 and abs(got / exp - 1) < 0.08 and abs(len(y) / len(x) - 1) < 0.03,
              f"f0 {base:.0f} -> {got:.0f} Hz (expected {exp:.0f}); length ratio {len(y)/len(x):.3f}")

# clamping: asking for a huge shift must not exceed the safe limit
big = pitch_shift(tone, sr, 12.0)
check("clamp +12 -> 4.5 st", abs(median_f0(big, sr) / (f_before * 2 ** (4.5 / 12)) - 1) < 0.03, f"f0 {median_f0(big, sr):.0f} Hz")
check("no-op below 0.05 st", pitch_shift(tone, sr, 0.01) is tone, "returned input unchanged")
sys.exit(1 if failures else 0)
