"""Phase 0 / Track A follow-up: does more threads or more processes raise throughput?"""
from __future__ import annotations

import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import onnxruntime as ort
from kokoro_onnx import Kokoro

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_kokoro import LINES, MODEL, VOICES  # noqa: E402

VOICE = "af_heart"


def make(threads: int) -> Kokoro:
    so = ort.SessionOptions()
    so.intra_op_num_threads = threads
    so.inter_op_num_threads = 1
    sess = ort.InferenceSession(str(MODEL), sess_options=so, providers=["CPUExecutionProvider"])
    return Kokoro.from_session(sess, str(VOICES))


def run_chunk(args: tuple[int, list[str]]) -> tuple[float, float]:
    threads, texts = args
    k = make(threads)
    k.create("Warm up.", voice=VOICE, speed=1.0, lang="en-us")
    t0 = time.perf_counter()
    audio = 0.0
    for t in texts:
        s, sr = k.create(t, voice=VOICE, speed=1.0, lang="en-us")
        audio += len(s) / sr
    return audio, time.perf_counter() - t0


def threads_sweep() -> None:
    texts = [t for _, t in LINES]
    print("single process, intra-op thread sweep")
    for th in (2, 6, 8, 12):
        audio, dt = run_chunk((th, texts))
        print(f"  threads={th:<2} audio={audio:5.1f}s compute={dt:5.1f}s  {audio/dt:4.2f}x realtime")


def process_pool(workers: int, threads: int) -> None:
    texts = [t for _, t in LINES] * 2  # 40 lines so each worker has real work
    chunks = [(threads, texts[i::workers]) for i in range(workers)]
    t0 = time.perf_counter()
    with ProcessPoolExecutor(max_workers=workers) as ex:
        res = list(ex.map(run_chunk, chunks))
    wall = time.perf_counter() - t0
    audio = sum(a for a, _ in res)
    # wall includes per-process model load + warmup; also report steady-state
    steady = max(dt for _, dt in res)
    print(f"  workers={workers} x threads={threads}: audio={audio:5.1f}s steady={steady:5.1f}s "
          f"-> {audio/steady:4.2f}x realtime (wall incl. startup {wall:5.1f}s)")


if __name__ == "__main__":
    threads_sweep()
    print("process pool (throughput for batch rendering)")
    process_pool(2, 6)
    process_pool(3, 4)
    process_pool(4, 3)
    process_pool(6, 2)
