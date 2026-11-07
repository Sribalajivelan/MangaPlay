"""Phase 0 / Track A: measure Kokoro (ONNX, int8) on this CPU.

Run:  .venv\\Scripts\\python.exe spike\\tts\\bench_kokoro.py
Writes WAVs to spike/tts/out/ and prints a small results table.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort
import soundfile as sf
from kokoro_onnx import Kokoro

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / ".cache" / "kokoro" / "kokoro-v1.0.int8.onnx"
VOICES = ROOT / ".cache" / "kokoro" / "voices-v1.0.bin"
OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(exist_ok=True)

# Original test lines covering the cases a webtoon needs: calm, shout, whisper,
# question, one-word reaction, narration, long sentence.
LINES = [
    ("calm", "I told you I would be here, and I am."),
    ("shout", "Get out of the way! It's going to collapse!"),
    ("whisper", "Don't make a sound. They're right behind the door."),
    ("question", "Wait, you knew about this the whole time?"),
    ("reaction", "Huh?"),
    ("reaction", "No way."),
    ("sad", "I just wanted one more summer with her."),
    ("angry", "You lied to me. Again."),
    ("excited", "We actually did it! We won the whole thing!"),
    ("narration", "Three days later, the city was quiet again."),
    ("narration", "Nobody in the village spoke of the stranger who had arrived at dawn."),
    ("calm", "Let's go home. There's nothing left to do here."),
    ("shout", "Stop right there!"),
    ("whisper", "Is it over?"),
    ("question", "Why would anyone leave a door like that unlocked?"),
    ("calm", "Thanks for the tea. It's exactly what I needed tonight."),
    ("angry", "Don't you dare walk away from me."),
    ("sad", "It's fine. Really. I'm used to it."),
    ("excited", "Look at that view! Can you believe it's all ours?"),
    ("long", "When the lights finally came back on, the whole room had changed, and none of us could remember who had moved the furniture."),
]


def make_kokoro(threads: int) -> Kokoro:
    so = ort.SessionOptions()
    so.intra_op_num_threads = threads
    so.inter_op_num_threads = 1
    sess = ort.InferenceSession(str(MODEL), sess_options=so, providers=["CPUExecutionProvider"])
    return Kokoro.from_session(sess, str(VOICES))


def bench(threads: int, voice: str) -> dict:
    k = make_kokoro(threads)
    k.create("Warm up.", voice=voice, speed=1.0, lang="en-us")  # exclude one-off init cost
    audio_s = 0.0
    compute_s = 0.0
    first = None
    for i, (_, text) in enumerate(LINES):
        t0 = time.perf_counter()
        samples, sr = k.create(text, voice=voice, speed=1.0, lang="en-us")
        dt = time.perf_counter() - t0
        if first is None:
            first = dt
        compute_s += dt
        audio_s += len(samples) / sr
        if threads == 4:  # only keep audio from one configuration
            sf.write(OUT / f"{voice}_{i:02d}_{LINES[i][0]}.wav", samples, sr)
    return {
        "threads": threads,
        "voice": voice,
        "audio_s": round(audio_s, 1),
        "compute_s": round(compute_s, 1),
        "rtf_x_realtime": round(audio_s / compute_s, 2),
        "first_line_s": round(first, 2),
    }


def main() -> None:
    k = make_kokoro(4)
    voices = sorted(k.get_voices())
    english = [v for v in voices if v[:2] in {"af", "am", "bf", "bm"}]
    print(f"total voices: {len(voices)}; english (US/UK): {len(english)}")
    print("english voices:", ", ".join(english))

    results = []
    for threads in (1, 4):
        results.append(bench(threads, "af_heart" if "af_heart" in voices else english[0]))
    # Check a few other voices at 4 threads so the audio can be compared by ear.
    for v in [x for x in ("am_michael", "bf_emma", "bm_george") if x in voices]:
        results.append(bench(4, v))

    print()
    print(f"{'voice':<12}{'threads':>8}{'audio_s':>9}{'compute_s':>11}{'x realtime':>12}{'first_s':>9}")
    for r in results:
        print(f"{r['voice']:<12}{r['threads']:>8}{r['audio_s']:>9}{r['compute_s']:>11}{r['rtf_x_realtime']:>12}{r['first_line_s']:>9}")

    (OUT / "results.json").write_text(json.dumps({"voices": voices, "runs": results}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
