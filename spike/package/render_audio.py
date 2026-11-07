"""Render every voiced beat in a bundle with Kokoro (ONNX, CPU) and write timings into script.json.

Run: .venv\\Scripts\\python.exe spike\\package\\render_audio.py <bundle_dir>

Two versions of every line are kept so they can be compared in the reader:
  plain       audio/<id>.ogg    Kokoro voice, emotion only nudges speed          (fields audio, audio_ms)
  expressive  audio_x/<id>.ogg  + character age (pitch/formants) + emotion pitch  (fields audio_x, audio_x_ms)

- 3 worker processes x 4 threads (best measured throughput on this CPU, see docs/04-TTS-CANDIDATES.md)
- content-hash cache per version: a line is re-synthesised only if (text, voice, speed, pitch) changed
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I does not add the script folder

import numpy as np  # noqa: E402
import onnxruntime as ort  # noqa: E402
import soundfile as sf  # noqa: E402
from kokoro_onnx import Kokoro  # noqa: E402

from pitch import pitch_shift  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / ".cache" / "kokoro" / "kokoro-v1.0.int8.onnx"
VOICES = ROOT / ".cache" / "kokoro" / "voices-v1.0.bin"
WORKERS, THREADS = 3, 4

VARIANTS = [
    {"name": "plain", "dir": "audio", "cache": "_cache.json", "file": "audio", "ms": "audio_ms", "speed": "speed", "pitch": None},
    {"name": "expressive", "dir": "audio_x", "cache": "_cache_x.json", "file": "audio_x", "ms": "audio_x_ms", "speed": "x_speed", "pitch": "x_pitch"},
]


def key(text: str, voice: str, speed: float, pitch: float = 0.0) -> str:
    # pitch 0 keeps the original key format, so audio rendered before pitch existed stays valid
    extra = f"|p{pitch:.2f}" if abs(pitch) >= 0.05 else ""
    return hashlib.sha1(f"{text}|{voice}|{speed}|kokoro-v1.0-int8{extra}".encode()).hexdigest()[:16]


def work(args: list[dict]) -> list[dict]:
    so = ort.SessionOptions()
    so.intra_op_num_threads = THREADS
    so.inter_op_num_threads = 1
    sess = ort.InferenceSession(str(MODEL), sess_options=so, providers=["CPUExecutionProvider"])
    k = Kokoro.from_session(sess, str(VOICES))
    out = []
    for j in args:
        try:
            samples, sr = k.create(j["text"], voice=j["voice"], speed=j["speed"], lang="en-us")
            samples = pitch_shift(np.asarray(samples, dtype=np.float32), sr, j["pitch"])
            sf.write(j["out"], samples, sr, format="OGG", subtype="VORBIS")
            out.append({"id": j["id"], "variant": j["variant"], "ms": int(len(samples) / sr * 1000), "key": j["key"], "error": None})
        except Exception as e:  # recorded per line, never swallowed
            out.append({"id": j["id"], "variant": j["variant"], "ms": 0, "key": j["key"], "error": f"{type(e).__name__}: {e}"})
    return out


def main(bundle: Path) -> int:
    script_path = bundle / "script.json"
    script = json.loads(script_path.read_text(encoding="utf-8"))
    caches: dict[str, dict] = {}
    jobs: list[dict] = []
    voiced = 0

    for v in VARIANTS:
        (bundle / v["dir"]).mkdir(exist_ok=True)
        cp = bundle / v["dir"] / v["cache"]
        caches[v["name"]] = json.loads(cp.read_text(encoding="utf-8")) if cp.exists() else {}

    for b in script["beats"]:
        if not b["tts_text"]:
            for v in VARIANTS:
                b[v["file"]], b[v["ms"]] = None, 0
            continue
        voiced += 1
        voice = script["voices"].get(b["speaker"]) or script["voices"]["unknown"]
        for v in VARIANTS:
            speed = b[v["speed"]]
            pitch = b[v["pitch"]] if v["pitch"] else 0.0
            k = key(b["tts_text"], voice, speed, pitch)
            out_path = bundle / v["dir"] / f"{b['id']}.ogg"
            hit = caches[v["name"]].get(b["id"])
            if hit and hit["key"] == k and out_path.exists():
                b[v["file"]], b[v["ms"]] = f"{v['dir']}/{b['id']}.ogg", hit["ms"]
            else:
                jobs.append({"id": b["id"], "variant": v["name"], "text": b["tts_text"], "voice": voice,
                             "speed": speed, "pitch": pitch, "key": k, "out": str(out_path)})
    print(f"{voiced} voiced lines x {len(VARIANTS)} versions; {len(jobs)} to synthesise")

    t0 = time.perf_counter()
    errors: list[tuple[str, str, str]] = []
    if jobs:
        n = min(WORKERS, len(jobs))  # each worker loads the model, so do not start idle ones
        chunks = [jobs[i::n] for i in range(n)]  # interleaved: similar mix of long and short lines per worker
        with ProcessPoolExecutor(max_workers=n) as ex:
            results = [r for part in ex.map(work, chunks) for r in part]
        by = {(r["variant"], r["id"]): r for r in results}
        for b in script["beats"]:
            for v in VARIANTS:
                r = by.get((v["name"], b["id"]))
                if not r:
                    continue
                if r["error"]:
                    errors.append((v["name"], b["id"], r["error"]))
                    b[v["file"]], b[v["ms"]] = None, 0
                else:
                    b[v["file"]], b[v["ms"]] = f"{v['dir']}/{b['id']}.ogg", r["ms"]
                    caches[v["name"]][b["id"]] = {"key": r["key"], "ms": r["ms"]}
    dt = time.perf_counter() - t0

    for v in VARIANTS:
        (bundle / v["dir"] / v["cache"]).write_text(json.dumps(caches[v["name"]]), encoding="utf-8")
    script_path.write_text(json.dumps(script, ensure_ascii=False), encoding="utf-8")
    for v in VARIANTS:
        total = sum(b[v["ms"]] for b in script["beats"])
        print(f"  {v['name']:<10} {total/60000:.1f} min of speech")
    print(f"rendered in {dt:.0f}s; errors {len(errors)}")
    for name, bid, e in errors:
        print("  ERROR", name, bid, e)
    return len(errors)


if __name__ == "__main__":
    sys.exit(1 if main(Path(sys.argv[1])) else 0)
