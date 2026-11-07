"""The processing queue: one chapter at a time, stage by stage, cancellable, restart-safe.

The chapter row IS the queue entry (status 'queued'). A crash or restart leaves 'processing' rows that
db.recover_after_restart() puts back in the queue; each stage checks its own outputs, so work resumes
where it stopped instead of starting over (and without paying for the model steps twice).
"""
from __future__ import annotations

import subprocess
import sys
import threading
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import db

# stage name -> share of the progress bar (ocr and the audio render are the slow ones)
STAGES = [("ingest", 0.02), ("detect", 0.12), ("ocr", 0.25), ("fuse", 0.01), ("packets", 0.02),
          ("cast", 0.05), ("direct", 0.35), ("voices", 0.01), ("package", 0.17)]


class Cancelled(Exception):
    pass


@dataclass
class _Active:
    chapter_id: int
    cancelled: bool = False
    procs: set = field(default_factory=set)
    lock: threading.Lock = field(default_factory=threading.Lock)


_stop = threading.Event()
_wake = threading.Event()
_thread: threading.Thread | None = None
_current: _Active | None = None
_current_lock = threading.Lock()
_idle = threading.Condition(_current_lock)


# ---- process control ---------------------------------------------------------------------------------
def kill_tree(p: subprocess.Popen) -> None:
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True, timeout=15)
        else:
            p.kill()
    except Exception:
        pass


def _make_run_proc(active: _Active) -> Callable[..., subprocess.CompletedProcess]:
    def run_proc(cmd, *, cwd=None, input_text=None, timeout=600, env=None):
        if active.cancelled:
            raise Cancelled()
        p = subprocess.Popen(
            cmd, cwd=cwd, env=env, text=True, encoding="utf-8", errors="replace",
            stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        with active.lock:
            active.procs.add(p)
        try:
            out, err = p.communicate(input=input_text, timeout=timeout)
        except subprocess.TimeoutExpired:
            kill_tree(p)
            p.communicate()
            raise RuntimeError(f"timed out after {timeout}s: {Path(str(cmd[1] if len(cmd) > 1 else cmd[0])).name}")
        finally:
            with active.lock:
                active.procs.discard(p)
        if active.cancelled:
            raise Cancelled()
        return subprocess.CompletedProcess(cmd, p.returncode, out, err)

    return run_proc


# ---- public API used by the web app ------------------------------------------------------------------
def wake() -> None:
    _wake.set()


def cancel_and_wait(chapter_id: int, wait_s: float = 45) -> None:
    """Stop work on a chapter (queued or running) and wait until the worker has let go of its files."""
    with db.db() as con:
        con.execute(
            "UPDATE chapter SET status='cancelled', stage=NULL, detail='cancelled', updated_at=? WHERE id=? AND status IN ('queued','processing')",
            (db.now(), chapter_id))
    with _current_lock:
        active = _current if _current and _current.chapter_id == chapter_id else None
    if active:
        active.cancelled = True
        with active.lock:
            procs = list(active.procs)
        for p in procs:
            kill_tree(p)
        deadline = time.time() + wait_s
        with _idle:
            while _current is active and time.time() < deadline:
                _idle.wait(timeout=0.5)


def start() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="queue-worker", daemon=True)
    _thread.start()
    _wake.set()


def stop() -> None:
    _stop.set()
    _wake.set()
    with _current_lock:
        active = _current
    if active:
        active.cancelled = True
        with active.lock:
            for p in list(active.procs):
                kill_tree(p)
    if _thread:
        _thread.join(timeout=10)


# ---- the loop ----------------------------------------------------------------------------------------
def _next_queued() -> int | None:
    with db.db() as con:
        r = con.execute("SELECT id FROM chapter WHERE status='queued' ORDER BY queued_at, id LIMIT 1").fetchone()
        return r["id"] if r else None


def _loop() -> None:
    while not _stop.is_set():
        cid = _next_queued()
        if cid is None:
            _wake.wait(timeout=5)
            _wake.clear()
            continue
        try:
            _process(cid)
        except Exception:  # never let the worker thread die
            traceback.print_exc()
            _fail(cid, "internal error in the queue worker (see server log)")


def _set(cid: int, **fields) -> bool:
    """Update the chapter only while it is still 'processing' (a cancel or delete must win)."""
    cols = ", ".join(f"{k}=?" for k in fields)
    with db.db() as con:
        cur = con.execute(f"UPDATE chapter SET {cols}, updated_at=? WHERE id=? AND status='processing'",
                          (*fields.values(), db.now(), cid))
        return cur.rowcount > 0


def _fail(cid: int, message: str) -> None:
    with db.db() as con:
        con.execute("UPDATE chapter SET status='failed', error=?, detail=NULL, updated_at=? WHERE id=? AND status IN ('processing','queued')",
                    (message[:600], db.now(), cid))


def _process(cid: int) -> None:
    global _current
    from . import stages  # imported here so the web app starts without the heavy stage dependencies

    with db.db() as con:
        cur = con.execute("UPDATE chapter SET status='processing', error=NULL, updated_at=? WHERE id=? AND status='queued'", (db.now(), cid))
        if cur.rowcount == 0:
            return
        ch = con.execute("SELECT * FROM chapter WHERE id=?", (cid,)).fetchone()

    active = _Active(cid)
    with _current_lock:
        _current = active
    try:
        cdir = db.chapter_dir(ch["manga_id"], cid)
        ctx = stages.Ctx(
            chapter_id=cid, manga_id=ch["manga_id"], page_count=ch["page_count"],
            source=cdir / "source", run=cdir / "run", bundle=cdir / "bundle", manga_dir=db.manga_dir(ch["manga_id"]),
            run_proc=_make_run_proc(active), cancelled=lambda: active.cancelled,
        )
        ctx.run.mkdir(parents=True, exist_ok=True)
        done = 0.0
        total_cost = 0.0
        now_ts = datetime.now().strftime("%H:%M:%S")
        print(f"\n[{now_ts}] [worker] >>> Processing started for chapter {cid} (total stages: {len(STAGES)})", flush=True)
        for stage_idx, (name, weight) in enumerate(STAGES, 1):
            if active.cancelled:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] [worker] Chapter {cid} cancelled by user.", flush=True)
                return
            ctx.progress = lambda frac, detail=None, _d=done, _w=weight, _n=name: _set(
                cid, stage=_n, progress=round(min(0.999, _d + _w * max(0.0, min(1.0, frac))), 4), detail=detail or f"{_n}")
            _set(cid, stage=name, progress=round(done, 4), detail=f"{name}")
            t0 = time.time()
            now_ts = datetime.now().strftime("%H:%M:%S")
            print(f"[{now_ts}] [worker] [ch {cid}] [Stage {stage_idx}/{len(STAGES)}] Starting stage '{name}'...", flush=True)
            try:
                res = stages.STAGE_FUNCS[name](ctx)
            except Cancelled:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] [worker] [ch {cid}] Stage '{name}' cancelled.", flush=True)
                return
            except Exception as e:
                if active.cancelled:
                    return
                dur = round(time.time() - t0, 1)
                now_ts = datetime.now().strftime("%H:%M:%S")
                print(f"[{now_ts}] [worker] [ch {cid}] !!! Stage '{name}' FAILED after {dur}s: {e}", flush=True)
                traceback.print_exc()
                with db.db() as con:
                    con.execute("INSERT INTO stage_run(chapter_id,stage,status,started_at,seconds,note) VALUES(?,?,?,?,?,?)",
                                (cid, name, "failed", db.now(), dur, str(e)[:300]))
                _fail(cid, f"{name}: {e}")
                return
            dur = round(time.time() - t0, 1)
            total_cost += res.cost_usd
            now_ts = datetime.now().strftime("%H:%M:%S")
            print(f"[{now_ts}] [worker] [ch {cid}] [Stage {stage_idx}/{len(STAGES)}] Stage '{name}' DONE in {dur}s ({res.note}, cost: ${res.cost_usd:.4f})", flush=True)
            with db.db() as con:
                con.execute("INSERT INTO stage_run(chapter_id,stage,status,started_at,seconds,cost_usd,note) VALUES(?,?,?,?,?,?,?)",
                            (cid, name, "done", db.now(), dur, res.cost_usd, res.note))
                con.execute("UPDATE chapter SET cost_usd=COALESCE((SELECT SUM(cost_usd) FROM stage_run WHERE chapter_id=? AND status='done'),0) WHERE id=?", (cid, cid))
            done += weight
        now_ts = datetime.now().strftime("%H:%M:%S")
        print(f"[{now_ts}] [worker] >>> Processing COMPLETE for chapter {cid} (total cost: ${total_cost:.4f})\n", flush=True)
        _set(cid, status="ready", stage=None, progress=1.0, detail=None, ready_at=db.now())
    finally:
        with _idle:
            _current = None
            _idle.notify_all()
