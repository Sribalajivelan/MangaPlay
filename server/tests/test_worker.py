"""The queue's state machine, with the real stages replaced by fast fakes."""
import threading
import time

import pytest

from server import db, stages, worker
from server.worker import Cancelled, STAGES

from .conftest import make_chapter

NAMES = [n for n, _ in STAGES]


def queued_chapter(client, **kw):
    mid, cid = make_chapter(client, **kw)
    client.post(f"/api/chapters/{cid}/finalize")
    return mid, cid


def status(cid):
    with db.db() as con:
        return dict(con.execute("SELECT * FROM chapter WHERE id=?", (cid,)).fetchone())


def fakes(**overrides):
    f = {n: (lambda ctx, n=n: stages.StageResult(f"{n} ok", 0.01)) for n in NAMES}
    f.update(overrides)
    return f


def test_full_run_marks_chapter_ready(client, monkeypatch):
    monkeypatch.setattr(stages, "STAGE_FUNCS", fakes())
    _, cid = queued_chapter(client)
    worker._process(cid)
    s = status(cid)
    assert (s["status"], s["progress"], s["stage"], s["error"]) == ("ready", 1.0, None, None)
    assert s["ready_at"]
    with db.db() as con:
        runs = con.execute("SELECT stage,status FROM stage_run WHERE chapter_id=? ORDER BY id", (cid,)).fetchall()
    assert [r["stage"] for r in runs] == NAMES and all(r["status"] == "done" for r in runs)
    assert s["cost_usd"] == pytest.approx(0.01 * len(NAMES))  # model cost is totalled per chapter


def test_failure_names_the_stage_and_retry_resumes(client, monkeypatch):
    calls = {"ocr": 0}

    def flaky(ctx):
        calls["ocr"] += 1
        if calls["ocr"] == 1:
            raise RuntimeError("the text reader crashed")
        return stages.StageResult("ok")

    monkeypatch.setattr(stages, "STAGE_FUNCS", fakes(ocr=flaky))
    _, cid = queued_chapter(client)
    worker._process(cid)
    s = status(cid)
    assert s["status"] == "failed" and s["error"].startswith("ocr:") and "crashed" in s["error"]
    assert client.post(f"/api/chapters/{cid}/retry").json()["status"] == "queued"
    worker._process(cid)
    assert status(cid)["status"] == "ready" and calls["ocr"] == 2


def test_progress_stays_in_bounds_and_advances(client, monkeypatch):
    seen = []

    def watcher(ctx):
        ctx.progress(0.5, "halfway")
        seen.append(status(ctx.chapter_id))
        return stages.StageResult()

    monkeypatch.setattr(stages, "STAGE_FUNCS", fakes(ocr=watcher))
    _, cid = queued_chapter(client)
    worker._process(cid)
    p = seen[0]
    done_before = sum(w for n, w in STAGES if n in ("ingest", "detect"))
    ocr_w = dict(STAGES)["ocr"]
    assert p["detail"] == "halfway" and p["stage"] == "ocr"
    assert p["progress"] == pytest.approx(done_before + ocr_w * 0.5, abs=1e-3) and 0 < p["progress"] < 1


def _run_in_thread(cid):
    t = threading.Thread(target=worker._process, args=(cid,))
    t.start()
    return t


def _blocking(started: threading.Event):
    def stage(ctx):
        started.set()
        for _ in range(400):  # stands in for a long subprocess; real stages are killed instead
            if ctx.cancelled():
                raise Cancelled()
            time.sleep(0.02)
        return stages.StageResult()

    return stage


def test_cancel_stops_running_chapter(client, monkeypatch):
    started = threading.Event()
    monkeypatch.setattr(stages, "STAGE_FUNCS", fakes(detect=_blocking(started)))
    _, cid = queued_chapter(client)
    t = _run_in_thread(cid)
    assert started.wait(5)
    assert status(cid)["status"] == "processing"
    worker.cancel_and_wait(cid)
    t.join(5)
    assert not t.is_alive() and worker._current is None
    assert status(cid)["status"] == "cancelled"  # a cancel is never overwritten by the worker finishing up


def test_delete_while_processing_stops_work_then_removes_everything(client, monkeypatch):
    started = threading.Event()
    monkeypatch.setattr(stages, "STAGE_FUNCS", fakes(detect=_blocking(started)))
    mid, cid = queued_chapter(client)
    t = _run_in_thread(cid)
    assert started.wait(5)
    assert client.delete(f"/api/chapters/{cid}").status_code == 204
    t.join(5)
    assert not t.is_alive()
    assert client.get(f"/api/chapters/{cid}").status_code == 404
    assert not db.chapter_dir(mid, cid).exists()


def test_queue_is_first_in_first_out(client):
    _, a = queued_chapter(client)
    _, b = queued_chapter(client)
    assert worker._next_queued() == a
    with db.db() as con:
        con.execute("UPDATE chapter SET status='ready' WHERE id=?", (a,))
    assert worker._next_queued() == b


def test_restart_puts_interrupted_chapters_back_in_the_queue(client):
    _, cid = queued_chapter(client)
    with db.db() as con:
        con.execute("UPDATE chapter SET status='processing', stage='ocr', progress=0.3 WHERE id=?", (cid,))
    assert db.recover_after_restart() == 1
    s = status(cid)
    assert s["status"] == "queued" and "resumed" in s["detail"]
    assert db.recover_after_restart() == 0  # nothing left to recover


def test_a_stage_that_cannot_be_imported_does_not_kill_the_worker(client, monkeypatch):
    def boom(ctx):
        raise ValueError("unexpected")

    monkeypatch.setattr(stages, "STAGE_FUNCS", fakes(ingest=boom))
    _, cid = queued_chapter(client)
    worker._process(cid)  # must not raise
    assert status(cid)["status"] == "failed"
