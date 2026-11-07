"""FastAPI app: library, uploads, reading state, bundle files, and the Wrong-voice endpoint.

Run (from the repo root):  .venv\\Scripts\\python.exe -m uvicorn server.main:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, field_validator
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import config, db, worker

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
SPECIAL_SPEAKERS = {"narrator", "system", "announcer", "unknown", "none"}
BEAT_RE = re.compile(r"^b\d{1,5}$")
MEDIA_TYPES = {".json": "application/json", ".webp": "image/webp", ".ogg": "audio/ogg", ".png": "image/png",
               ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


# ---------------------------------------------------------------------------------------------------
# security: this process can start commands and delete files, so it only answers the local page
# ---------------------------------------------------------------------------------------------------
class SameOriginOnly(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method not in SAFE_METHODS:
            origin = request.headers.get("origin")
            if origin and urlparse(origin).netloc != request.headers.get("host", ""):
                return JSONResponse({"detail": "cross-origin request refused"}, status_code=403)
        return await call_next(request)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    recovered = db.recover_after_restart()
    if recovered:
        print(f"[startup] {recovered} chapter(s) were mid-processing and went back to the queue")
    if not os.environ.get("MANGA_NO_WORKER"):
        worker.start()
    yield
    worker.stop()


app = FastAPI(title="MangaPlay", lifespan=lifespan)
app.add_middleware(SameOriginOnly)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=sorted(config.ALLOWED_HOSTS))


# ---------------------------------------------------------------------------------------------------
# models
# ---------------------------------------------------------------------------------------------------
class MangaIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)

    @field_validator("title")
    @classmethod
    def clean(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("title is empty")
        return v


class ChapterIn(BaseModel):
    title: str = Field(default="", max_length=200)
    number: Optional[float] = Field(default=None, ge=0, le=100000)

    @field_validator("title")
    @classmethod
    def clean(cls, v: str) -> str:
        return " ".join(v.split())


class ReadingStateIn(BaseModel):
    beat_id: Optional[str] = None
    y: float = Field(default=0, ge=0, le=5_000_000)
    rate: Optional[float] = Field(default=None, ge=0.25, le=4)
    pace: Optional[float] = Field(default=None, ge=50, le=3000)
    expressive: Optional[bool] = None

    @field_validator("beat_id")
    @classmethod
    def beat(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not BEAT_RE.match(v):
            raise ValueError("bad beat id")
        return v


class OverrideIn(BaseModel):
    beat: str
    speaker: Optional[str] = None
    muted: bool = False
    reset: bool = False

    @field_validator("beat")
    @classmethod
    def beat_ok(cls, v: str) -> str:
        if not BEAT_RE.match(v):
            raise ValueError("bad beat id")
        return v


# ---------------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------------
def row(r) -> dict:
    return dict(r) if r is not None else {}


def get_manga_or_404(con, manga_id: int):
    m = con.execute("SELECT * FROM manga WHERE id=?", (manga_id,)).fetchone()
    if not m:
        raise HTTPException(404, "no such manga")
    return m


def get_chapter_or_404(con, chapter_id: int):
    c = con.execute("SELECT * FROM chapter WHERE id=?", (chapter_id,)).fetchone()
    if not c:
        raise HTTPException(404, "no such chapter")
    return c


def chapter_json(c) -> dict:
    d = dict(c)
    d["bundle_url"] = f"/bundle/{d['id']}/" if d["status"] == "ready" else None
    return d


def bundle_dir(manga_id: int, chapter_id: int) -> Path:
    return db.chapter_dir(manga_id, chapter_id) / "bundle"


# ---------------------------------------------------------------------------------------------------
# library
# ---------------------------------------------------------------------------------------------------
@app.get("/api/health")
def health():
    return {"ok": True, "library": str(config.LIBRARY)}


@app.get("/api/manga")
def list_manga():
    with db.db() as con:
        rows = con.execute(
            """SELECT m.*,
                 (SELECT COUNT(*) FROM chapter c WHERE c.manga_id=m.id) AS chapters,
                 (SELECT COUNT(*) FROM chapter c WHERE c.manga_id=m.id AND c.status='ready') AS ready,
                 (SELECT COUNT(*) FROM chapter c WHERE c.manga_id=m.id AND c.status IN ('queued','processing')) AS processing,
                 (SELECT c.id FROM chapter c WHERE c.manga_id=m.id AND c.status='ready' ORDER BY c.number, c.id LIMIT 1) AS first_ready_chapter
               FROM manga m ORDER BY m.updated_at DESC, m.id DESC"""
        ).fetchall()
        last = con.execute("SELECT value FROM app_state WHERE key='last_chapter'").fetchone()
        cont = None
        if last:
            c = con.execute(
                """SELECT c.id, c.title, c.number, c.manga_id, m.title AS manga_title, rs.updated_at
                   FROM chapter c JOIN manga m ON m.id=c.manga_id LEFT JOIN reading_state rs ON rs.chapter_id=c.id
                   WHERE c.id=? AND c.status='ready'""", (int(last["value"]),)).fetchone()
            cont = row(c) if c else None
        return {"manga": [row(r) for r in rows], "continue": cont}


@app.post("/api/manga", status_code=201)
def create_manga(body: MangaIn):
    with db.db() as con:
        t = db.now()
        cur = con.execute("INSERT INTO manga(title, created_at, updated_at) VALUES(?,?,?)", (body.title, t, t))
        return row(con.execute("SELECT * FROM manga WHERE id=?", (cur.lastrowid,)).fetchone())


@app.get("/api/manga/{manga_id}")
def get_manga(manga_id: int):
    with db.db() as con:
        m = get_manga_or_404(con, manga_id)
        chapters = con.execute(
            "SELECT * FROM chapter WHERE manga_id=? ORDER BY COALESCE(number, 1e9), id", (manga_id,)).fetchall()
        return {"manga": row(m), "chapters": [chapter_json(c) for c in chapters]}


@app.get("/api/manga/{manga_id}/cover")
def manga_cover(manga_id: int):
    f = db.manga_dir(manga_id) / "cover.jpg"
    if not f.is_file():
        raise HTTPException(404)
    return FileResponse(f, media_type="image/jpeg", headers={"Cache-Control": "max-age=300"})


@app.patch("/api/manga/{manga_id}")
def rename_manga(manga_id: int, body: MangaIn):
    with db.db() as con:
        get_manga_or_404(con, manga_id)
        con.execute("UPDATE manga SET title=?, updated_at=? WHERE id=?", (body.title, db.now(), manga_id))
        return row(con.execute("SELECT * FROM manga WHERE id=?", (manga_id,)).fetchone())


@app.delete("/api/manga/{manga_id}", status_code=204)
def delete_manga(manga_id: int):
    with db.db() as con:
        get_manga_or_404(con, manga_id)
        ids = [r["id"] for r in con.execute("SELECT id FROM chapter WHERE manga_id=?", (manga_id,))]
    for cid in ids:  # stop any running work first, so nothing is writing into a directory we delete
        worker.cancel_and_wait(cid)
    with db.db() as con:
        con.execute("DELETE FROM manga WHERE id=?", (manga_id,))  # cascades to chapters, state, runs
        con.execute("DELETE FROM app_state WHERE key='last_chapter' AND value IN (%s)" % ",".join("?" * len(ids)), [str(i) for i in ids]) if ids else None
    db.remove_tree(db.manga_dir(manga_id))
    return Response(status_code=204)


# ---------------------------------------------------------------------------------------------------
# chapters and uploads
# ---------------------------------------------------------------------------------------------------
@app.post("/api/manga/{manga_id}/chapters", status_code=201)
def create_chapter(manga_id: int, body: ChapterIn):
    with db.db() as con:
        get_manga_or_404(con, manga_id)
        number = body.number
        if number is None:
            r = con.execute("SELECT MAX(number) AS n FROM chapter WHERE manga_id=?", (manga_id,)).fetchone()
            number = (r["n"] + 1) if r and r["n"] is not None else 1
        t = db.now()
        cur = con.execute(
            "INSERT INTO chapter(manga_id, number, title, status, created_at, updated_at) VALUES(?,?,?,?,?,?)",
            (manga_id, number, body.title, "uploading", t, t))
        con.execute("UPDATE manga SET updated_at=? WHERE id=?", (t, manga_id))
        cid = cur.lastrowid
        (db.chapter_dir(manga_id, cid) / "source").mkdir(parents=True, exist_ok=True)
        return chapter_json(con.execute("SELECT * FROM chapter WHERE id=?", (cid,)).fetchone())


@app.put("/api/chapters/{chapter_id}/pages/{n}")
async def upload_page(chapter_id: int, n: int, request: Request):
    if not 1 <= n <= config.MAX_PAGES_PER_CHAPTER:
        raise HTTPException(400, f"page number must be 1..{config.MAX_PAGES_PER_CHAPTER}")
    with db.db() as con:
        c = get_chapter_or_404(con, chapter_id)
        if c["status"] != "uploading":
            raise HTTPException(409, "chapter is not accepting uploads")
    declared = request.headers.get("content-length")
    if declared and int(declared) > config.MAX_PAGE_BYTES:
        raise HTTPException(413, "image too large")
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > config.MAX_PAGE_BYTES:
            raise HTTPException(413, "image too large")
    ext = next((e for sig, e in config.IMAGE_SIGNATURES.items() if data.startswith(sig)), None)
    if ext is None and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        ext = ".webp"
    if ext is None:
        raise HTTPException(415, "only PNG, JPEG or WebP images are accepted")
    src = db.chapter_dir(c["manga_id"], chapter_id) / "source"
    src.mkdir(parents=True, exist_ok=True)
    for old in src.glob(f"{n:03d}.*"):  # re-upload of the same page replaces it
        old.unlink()
    tmp = src / f"{n:03d}{ext}.part"
    tmp.write_bytes(bytes(data))
    tmp.replace(src / f"{n:03d}{ext}")
    return {"ok": True, "page": n, "bytes": len(data)}


@app.post("/api/chapters/{chapter_id}/finalize")
def finalize_chapter(chapter_id: int):
    with db.db() as con:
        c = get_chapter_or_404(con, chapter_id)
        if c["status"] != "uploading":
            raise HTTPException(409, "chapter was already submitted")
        src = db.chapter_dir(c["manga_id"], chapter_id) / "source"
        files = sorted(p for p in src.glob("*.*") if not p.name.endswith(".part"))
        nums = [int(p.stem) for p in files if p.stem.isdigit()]
        if not nums:
            raise HTTPException(400, "no pages were uploaded")
        if nums != list(range(1, len(nums) + 1)):
            raise HTTPException(400, "pages must be numbered 1..N without gaps; re-upload the missing ones")
        t = db.now()
        con.execute("UPDATE chapter SET status='queued', page_count=?, queued_at=?, updated_at=?, detail='waiting in the queue' WHERE id=?",
                    (len(nums), t, t, chapter_id))
        out = chapter_json(con.execute("SELECT * FROM chapter WHERE id=?", (chapter_id,)).fetchone())
    worker.wake()
    return out


@app.get("/api/chapters/{chapter_id}")
def get_chapter(chapter_id: int):
    with db.db() as con:
        c = get_chapter_or_404(con, chapter_id)
        runs = con.execute("SELECT stage,status,seconds,cost_usd,note FROM stage_run WHERE chapter_id=? ORDER BY id", (chapter_id,)).fetchall()
        return {**chapter_json(c), "stages": [row(r) for r in runs]}


@app.delete("/api/chapters/{chapter_id}", status_code=204)
def delete_chapter(chapter_id: int):
    with db.db() as con:
        c = get_chapter_or_404(con, chapter_id)
        manga_id = c["manga_id"]
    worker.cancel_and_wait(chapter_id)
    with db.db() as con:
        con.execute("DELETE FROM chapter WHERE id=?", (chapter_id,))
        con.execute("DELETE FROM app_state WHERE key='last_chapter' AND value=?", (str(chapter_id),))
    db.remove_tree(db.chapter_dir(manga_id, chapter_id))
    return Response(status_code=204)


@app.post("/api/chapters/{chapter_id}/cancel")
def cancel_chapter(chapter_id: int):
    with db.db() as con:
        c = get_chapter_or_404(con, chapter_id)
        if c["status"] not in ("queued", "processing"):
            raise HTTPException(409, "nothing to cancel")
    worker.cancel_and_wait(chapter_id)
    with db.db() as con:
        return chapter_json(get_chapter_or_404(con, chapter_id))


@app.post("/api/chapters/{chapter_id}/retry")
def retry_chapter(chapter_id: int):
    with db.db() as con:
        c = get_chapter_or_404(con, chapter_id)
        if c["status"] not in ("failed", "cancelled"):
            raise HTTPException(409, "only failed or cancelled chapters can be retried")
        t = db.now()
        con.execute("UPDATE chapter SET status='queued', error=NULL, stage=NULL, progress=0, queued_at=?, updated_at=?, detail='waiting in the queue' WHERE id=?", (t, t, chapter_id))
        out = chapter_json(con.execute("SELECT * FROM chapter WHERE id=?", (chapter_id,)).fetchone())
    worker.wake()
    return out


# ---------------------------------------------------------------------------------------------------
# reading state (survives restarts)
# ---------------------------------------------------------------------------------------------------
@app.get("/api/chapters/{chapter_id}/reading-state")
def get_reading_state(chapter_id: int):
    with db.db() as con:
        get_chapter_or_404(con, chapter_id)
        r = con.execute("SELECT * FROM reading_state WHERE chapter_id=?", (chapter_id,)).fetchone()
        return row(r) if r else None


@app.put("/api/chapters/{chapter_id}/reading-state")
def put_reading_state(chapter_id: int, body: ReadingStateIn):
    with db.db() as con:
        c = get_chapter_or_404(con, chapter_id)
        con.execute(
            """INSERT INTO reading_state(chapter_id, beat_id, y, rate, pace, expressive, updated_at) VALUES(?,?,?,?,?,?,?)
               ON CONFLICT(chapter_id) DO UPDATE SET beat_id=excluded.beat_id, y=excluded.y,
                 rate=COALESCE(excluded.rate, rate), pace=COALESCE(excluded.pace, pace),
                 expressive=COALESCE(excluded.expressive, expressive), updated_at=excluded.updated_at""",
            (chapter_id, body.beat_id, body.y, body.rate, body.pace, None if body.expressive is None else int(body.expressive), db.now()))
        con.execute("INSERT INTO app_state(key,value) VALUES('last_chapter',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(chapter_id),))
        con.execute("UPDATE manga SET updated_at=? WHERE id=?", (db.now(), c["manga_id"]))
    return {"ok": True}


# ---------------------------------------------------------------------------------------------------
# Wrong-voice corrections: write overrides.json, then re-apply and re-render only what changed
# ---------------------------------------------------------------------------------------------------
_override_lock = threading.Lock()  # one rebuild at a time


@app.post("/api/chapters/{chapter_id}/override")
def override_voice(chapter_id: int, body: OverrideIn):
    with db.db() as con:
        c = get_chapter_or_404(con, chapter_id)
    if c["status"] != "ready":
        raise HTTPException(409, "chapter is not ready")
    bdir = bundle_dir(c["manga_id"], chapter_id)
    script = json.loads((bdir / "script.json").read_text(encoding="utf-8"))
    target = next((b for b in script["beats"] if b["id"] == body.beat), None)
    if target is None:
        raise HTTPException(404, "no such beat")
    allowed = {x["id"] for x in script["cast"]} | SPECIAL_SPEAKERS
    if not body.reset and not body.muted and body.speaker not in allowed:
        raise HTTPException(400, "unknown speaker")
    with _override_lock:
        ov_path = bdir / "overrides.json"
        ov = json.loads(ov_path.read_text(encoding="utf-8")) if ov_path.exists() else {"version": 1, "beats": {}}
        prev = ov["beats"].get(body.beat, {})
        was = prev.get("was") or (target.get("override") or {}).get("was") or target["speaker"]
        if body.reset:
            ov["beats"].pop(body.beat, None)
        elif body.muted:
            ov["beats"][body.beat] = {"muted": True, "by": "user", "was": was, "at": db.now()}
        else:
            ov["beats"][body.beat] = {"speaker": body.speaker, "by": "user", "was": was, "at": db.now()}
        ov_path.write_text(json.dumps(ov, indent=1), encoding="utf-8")
        try:
            res = subprocess.run([config.PYTHON, "-I", str(config.ROOT / "spike" / "package" / "build_bundle.py"), "rebuild", str(bdir)],
                                 cwd=config.ROOT, capture_output=True, text=True, timeout=180)
        except subprocess.TimeoutExpired:
            raise HTTPException(504, "re-rendering took too long")
    if res.returncode != 0:
        raise HTTPException(500, f"rebuild failed: {res.stderr[-400:] or res.stdout[-400:]}")
    return {"ok": True, "changed": [body.beat]}


# ---------------------------------------------------------------------------------------------------
# reader files and the built app
# ---------------------------------------------------------------------------------------------------
@app.get("/bundle/{chapter_id}/{path:path}")
def bundle_file(chapter_id: int, path: str):
    with db.db() as con:
        c = get_chapter_or_404(con, chapter_id)
    root = bundle_dir(c["manga_id"], chapter_id).resolve()
    f = (root / path).resolve()
    if root not in f.parents or not f.is_file():
        raise HTTPException(404)
    # explicit types: Windows has no registry entry for .ogg/.webp, which made the server say octet-stream
    return FileResponse(f, media_type=MEDIA_TYPES.get(f.suffix.lower(), "application/octet-stream"),
                        headers={"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"})


@app.get("/{full_path:path}")
def spa(full_path: str):
    if full_path.startswith(("api/", "bundle/")):
        raise HTTPException(404)
    root = config.DIST.resolve()
    f = (root / full_path).resolve()
    if full_path and root in f.parents and f.is_file():
        return FileResponse(f)
    index = root / "index.html"
    if index.is_file():
        return FileResponse(index)
    raise HTTPException(404, "app not built: run `pnpm build` in app/, or use the Vite dev server")
