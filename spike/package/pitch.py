"""Pitch shifting with the ffmpeg that ships in the venv (imageio-ffmpeg): rubberband, high quality.

formant=shifted moves the formants together with the pitch, which is what makes a voice sound
younger (up) or older (down). Duration is preserved. Fixed command, no shell, audio over pipes.
"""
from __future__ import annotations

import subprocess

import imageio_ffmpeg
import numpy as np

_FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
MAX_ABS_SEMITONES = 4.5  # beyond this rubberband artefacts become audible on speech


def pitch_shift(samples: np.ndarray, sr: int, semitones: float) -> np.ndarray:
    """Return `samples` shifted by `semitones` (float32 mono, same length +/- a few ms)."""
    semitones = max(-MAX_ABS_SEMITONES, min(MAX_ABS_SEMITONES, float(semitones)))
    if abs(semitones) < 0.05:
        return samples
    ratio = 2 ** (semitones / 12)
    cmd = [
        _FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin",
        "-f", "f32le", "-ar", str(sr), "-ac", "1", "-i", "pipe:0",
        "-af", f"rubberband=pitch={ratio:.5f}:formant=shifted:pitchq=quality",
        "-f", "f32le", "-ar", str(sr), "-ac", "1", "pipe:1",
    ]
    out = subprocess.run(cmd, input=np.asarray(samples, dtype="<f4").tobytes(), capture_output=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError(f"ffmpeg pitch shift failed: {out.stderr.decode(errors='replace')[:200]}")
    return np.frombuffer(out.stdout, dtype="<f4").astype(np.float32)


def median_f0(samples: np.ndarray, sr: int, fmin: float = 70.0, fmax: float = 400.0) -> float:
    """Rough fundamental frequency (median over voiced frames) by autocorrelation. For tests only."""
    frame, hop = int(0.04 * sr), int(0.02 * sr)
    lo, hi = int(sr / fmax), int(sr / fmin)
    f0s = []
    for i in range(0, len(samples) - frame, hop):
        x = samples[i : i + frame] - np.mean(samples[i : i + frame])
        if np.sqrt(np.mean(x**2)) < 0.02:  # skip silence / unvoiced
            continue
        ac = np.correlate(x, x, mode="full")[frame - 1 :]
        if ac[0] <= 0:
            continue
        lag = lo + int(np.argmax(ac[lo:hi]))
        if ac[lag] / ac[0] > 0.45:  # clearly periodic
            f0s.append(sr / lag)
    return float(np.median(f0s)) if f0s else 0.0
