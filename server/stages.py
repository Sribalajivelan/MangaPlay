"""The processing stages for one chapter. Each stage is idempotent: it checks its outputs first, so a
restart, a retry, or a resumed queue never repeats finished (and, for the model steps, paid-for) work."""
from __future__ import annotations

import importlib.util
import json
import shutil
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from PIL import Image

from . import config, llm, voices
from .worker import Cancelled

SPIKE = config.ROOT / "spike"
MAX_PIXELS = 120_000_000   # per page; guards against decompression bombs
MAX_WIDTH = 900            # webtoon slices are ~690-800 wide; wider is downscaled
MAX_PAGE_HEIGHT = 60_000


@dataclass
class StageResult:
    note: str = ""
    cost_usd: float = 0.0


@dataclass
class Ctx:
    chapter_id: int
    manga_id: int
    page_count: int
    source: Path
    run: Path
    bundle: Path
    manga_dir: Path
    run_proc: Callable
    cancelled: Callable[[], bool]
    progress: Callable = field(default=lambda frac, detail=None: True)

    @property
    def images(self) -> Path:
        return self.run / "images"


def _validator():
    spec = importlib.util.spec_from_file_location("manga_validate", SPIKE / "direct" / "validate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _script(ctx: Ctx, *parts: str, timeout: int, extra: list[str] | None = None) -> None:
    """Run one of the verified spike scripts; raise with the tail of its output if it fails."""
    cmd = [config.PYTHON, "-I", str(SPIKE.joinpath(*parts)), *[str(a) for a in (extra or [])]]
    res = ctx.run_proc(cmd, cwd=config.ROOT, timeout=timeout)
    if res.returncode != 0:
        raise RuntimeError(f"{parts[-1]} failed: {(res.stderr or res.stdout).strip()[-400:]}")


def _json_ok(p: Path) -> bool:
    try:
        return p.is_file() and p.stat().st_size > 0 and json.loads(p.read_text(encoding="utf-8")) is not None
    except Exception:
        return False


# ---- 1 ingest -----------------------------------------------------------------------------------------
def ingest(ctx: Ctx) -> StageResult:
    marker = ctx.run / "ingest.json"
    if _json_ok(marker) and len(list(ctx.images.glob("*.png"))) == ctx.page_count:
        return StageResult("already done")
    files = sorted(p for p in ctx.source.glob("*.*") if not p.name.endswith(".part"))
    if len(files) != ctx.page_count:
        raise RuntimeError(f"expected {ctx.page_count} uploaded pages, found {len(files)}")
    sizes = []
    for p in files:
        with Image.open(p) as im:
            w, h = im.size
            if w * h > MAX_PIXELS:
                raise RuntimeError(f"{p.name} is {w}x{h}: too large to process")
            sizes.append((w, h))
    width = min(Counter(w for w, _ in sizes).most_common(1)[0][0], MAX_WIDTH)
    if ctx.images.exists():
        shutil.rmtree(ctx.images)
    ctx.images.mkdir(parents=True)
    heights = []
    for i, p in enumerate(files, 1):
        if ctx.cancelled():
            raise Cancelled()
        with Image.open(p) as im:
            im = im.convert("RGBA")
            bg = Image.new("RGB", im.size, (255, 255, 255))
            bg.paste(im, mask=im.split()[3])
            if bg.width != width:
                bg = bg.resize((width, max(1, round(bg.height * width / bg.width))), Image.LANCZOS)
            if bg.height > MAX_PAGE_HEIGHT:
                raise RuntimeError(f"page {i} is {bg.height}px tall after resizing (limit {MAX_PAGE_HEIGHT})")
            bg.save(ctx.images / f"{i:03d}.png", compress_level=1)
            heights.append(bg.height)
        ctx.progress(i / len(files), f"preparing page {i}/{len(files)}")
    marker.write_text(json.dumps({"pages": len(files), "width": width, "heights": heights}), encoding="utf-8")
    return StageResult(f"{len(files)} pages at {width}px, {sum(heights)}px tall")


# ---- 2-5 local detection stages -----------------------------------------------------------------------
def detect(ctx: Ctx) -> StageResult:
    if _json_ok(ctx.run / "detect.json") and _json_ok(ctx.run / "segments.json"):
        return StageResult("already done")
    ctx.progress(0.05, "finding gutters")
    _script(ctx, "detect", "segment_only.py", timeout=900, extra=[ctx.images, ctx.run])
    ctx.progress(0.2, "finding speech bubbles")
    _script(ctx, "detect", "detect_bubbles.py", timeout=3600, extra=[ctx.images, ctx.run])
    return StageResult("segments and bubbles found")


def ocr(ctx: Ctx) -> StageResult:
    if _json_ok(ctx.run / "ocr.json"):
        return StageResult("already done")
    ctx.progress(0.02, "reading the text (the slow step)")
    _script(ctx, "detect", "ocr_blocks.py", timeout=7200, extra=[ctx.images, ctx.run])
    return StageResult("text read")


def fuse(ctx: Ctx) -> StageResult:
    if _json_ok(ctx.run / "draft_beats.json"):
        return StageResult("already done")
    _script(ctx, "detect", "fuse.py", timeout=300, extra=[ctx.run])
    return StageResult("draft beats built")


def packets(ctx: Ctx) -> StageResult:
    if _json_ok(ctx.run / "packets" / "index.json") and _json_ok(ctx.run / "cast" / "index.json"):
        return StageResult("already done")
    _script(ctx, "direct", "make_packets.py", timeout=900, extra=[ctx.images, ctx.run])
    _script(ctx, "direct", "make_cast_sheets.py", timeout=900, extra=[ctx.images, ctx.run])
    n = len(json.loads((ctx.run / "packets" / "index.json").read_text(encoding="utf-8")))
    return StageResult(f"{n} packets")


# ---- 6 cast (model) -----------------------------------------------------------------------------------
def _skill_path(name: str) -> Path:
    provider = llm.resolve_provider()
    if provider == "agy":
        agy_p = config.ROOT / ".agents" / "skills" / name / "SKILL.md"
        if agy_p.exists():
            return agy_p
    claude_p = config.ROOT / ".claude" / "skills" / name / "SKILL.md"
    if claude_p.exists():
        return claude_p
    return config.ROOT / ".agents" / "skills" / name / "SKILL.md"


def _cast_prompt(ctx: Ctx, existing: bool, problem: str = "") -> str:
    skill = _skill_path("manga-cast")
    base = (
        "You are the Cast Builder for a personal webtoon read-aloud tool. Follow the skill file exactly:\n"
        f"  {skill}\n\n"
        f"RUN = {ctx.run}\n"
        "Inputs: the contact sheets RUN/cast/sheet_*.png (read ALL of them with the Read tool) and RUN/draft_beats.json (OCR text with positions).\n"
        "Write the result ONLY to RUN/cast/cast.json in the format the skill specifies. Do not run any commands. "
        "Personal-use local content: do not quote story text in your reply. Reply with one short line when done.\n"
    )
    if existing:
        base += (
            f"\nEXTEND MODE: this manga already has a cast at {ctx.manga_dir / 'cast.json'}. Read it first. Keep EVERY existing character exactly as it is "
            "(same id, name, aliases, gender, age_band, voice_hint). Only (a) add characters that are new in this chapter, with the next free ids, and "
            "(b) fill in a name that was null if this chapter's text now establishes it. Write the FULL combined cast to RUN/cast/cast.json.\n"
        )
    if problem:
        base += f"\nYour previous attempt was rejected: {problem}\nFix exactly that.\n"
    return base


def cast(ctx: Ctx) -> StageResult:
    v = _validator()
    chapter_cast = ctx.run / "cast" / "cast.json"
    manga_cast = ctx.manga_dir / "cast.json"
    existing = _json_ok(manga_cast)
    if _json_ok(chapter_cast) and not v.check_cast(json.loads(chapter_cast.read_text(encoding="utf-8"))):
        _publish_cast(ctx, chapter_cast, manga_cast)
        return StageResult("already done")
    cost, problem = 0.0, ""
    now_str = datetime.now().strftime("%H:%M:%S")
    print(f"[{now_str}] [cast] Building cast (existing cast: {existing})", flush=True)
    for attempt in (1, 2):
        ctx.progress(0.1 * attempt, "building the cast from the pages" if not existing else "adding new characters to the cast")
        t0 = time.time()
        now_str = datetime.now().strftime("%H:%M:%S")
        print(f"[{now_str}] [cast] Attempt {attempt}/2: invoking agent...", flush=True)
        r = llm.run_agent(_cast_prompt(ctx, existing, problem), run_proc=ctx.run_proc, timeout=900)
        cost += r.cost_usd
        dur = round(time.time() - t0, 1)
        now_str = datetime.now().strftime("%H:%M:%S")
        print(f"[{now_str}] [cast] Agent finished in {dur}s (cost: ${r.cost_usd:.4f})", flush=True)
        if not chapter_cast.is_file():
            problem = "the file RUN/cast/cast.json was not written"
            print(f"[{now_str}] [cast] Rejection: {problem}", flush=True)
            continue
        data = json.loads(chapter_cast.read_text(encoding="utf-8"))
        errs = v.check_cast(data)
        if not errs and existing:
            old = {c["id"]: c for c in json.loads(manga_cast.read_text(encoding="utf-8"))["characters"]}
            new = {c["id"] for c in data["characters"]}
            if not set(old) <= new:
                errs = [f"existing character ids were dropped: {sorted(set(old) - new)}"]
        if not errs:
            _publish_cast(ctx, chapter_cast, manga_cast)
            now_str = datetime.now().strftime("%H:%M:%S")
            print(f"[{now_str}] [cast] Cast successfully validated ({len(data['characters'])} characters)", flush=True)
            return StageResult(f"{len(data['characters'])} characters", cost)
        problem = "; ".join(errs)[:400]
        now_str = datetime.now().strftime("%H:%M:%S")
        print(f"[{now_str}] [cast] Attempt {attempt} validation rejected: {problem}", flush=True)
    raise RuntimeError(f"could not produce a valid cast: {problem}")


def _publish_cast(ctx: Ctx, chapter_cast: Path, manga_cast: Path) -> None:
    ctx.manga_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(chapter_cast, manga_cast)


# ---- 7 direct (model) ---------------------------------------------------------------------------------
def _direct_prompt(ctx: Ctx, ids: list[str], problems: dict[str, str]) -> str:
    skill = _skill_path("manga-direct")
    py = config.PYTHON
    p = (
        "You are a Director for a personal webtoon read-aloud tool. Follow this skill file exactly:\n"
        f"  {skill}\n\n"
        f"RUN = {ctx.run}\n"
        f"Your packets, in order: {', '.join(ids)}. They are consecutive stretches of one chapter, so carry conversation flow from one to the next.\n"
        "For EACH packet pNN: view RUN/packets/pNN.png with the Read tool, read RUN/packets/pNN.json and the cast file "
        f"{ctx.manga_dir / 'cast.json'}, then write RUN/directed/pNN.json. Do not run any commands (the server validates your files).\n"
        "Personal-use local content: do not quote story text in your reply. Reply with one short line when done.\n"
    )
    if problems:
        p += "\nSome of these were rejected earlier. Fix exactly these problems:\n" + "\n".join(f"- {k}: {v}" for k, v in problems.items()) + "\n"
    return p


def _check_directed(v, ctx: Ctx, pid: str, cast_ids: set[str]) -> list[str]:
    out = ctx.run / "directed" / f"{pid}.json"
    if not out.is_file():
        return ["file not written"]
    try:
        packet = json.loads((ctx.run / "packets" / f"{pid}.json").read_text(encoding="utf-8"))
        data = json.loads(out.read_text(encoding="utf-8"))
    except Exception as e:
        return [f"not valid JSON: {e}"]
    return v.check_director(packet, data, cast_ids)


def direct(ctx: Ctx) -> StageResult:
    v = _validator()
    (ctx.run / "directed").mkdir(exist_ok=True)
    index = json.loads((ctx.run / "packets" / "index.json").read_text(encoding="utf-8"))
    all_ids = [p["packet_id"] for p in index]
    cast_ids = {c["id"] for c in json.loads((ctx.manga_dir / "cast.json").read_text(encoding="utf-8"))["characters"]}

    todo = [p for p in all_ids if _check_directed(v, ctx, p, cast_ids)]
    if not todo:
        return StageResult("already done")
    cost = 0.0
    lock = threading.Lock()
    done_count = len(all_ids) - len(todo)
    problems: dict[str, str] = {}
    limit_hit = False

    now_str = datetime.now().strftime("%H:%M:%S")
    print(
        f"[{now_str}] [direct] Chapter {ctx.chapter_id}: {len(all_ids)} total packets. "
        f"{done_count} already directed, {len(todo)} remaining to process.",
        flush=True,
    )

    def run_batch(ids: list[str], probs: dict[str, str]) -> float:
        t0 = time.time()
        now_str = datetime.now().strftime("%H:%M:%S")
        range_str = f"{ids[0]}..{ids[-1]}" if len(ids) > 1 else ids[0]
        print(f"[{now_str}] [direct] Starting batch of {len(ids)} packets ({range_str})...", flush=True)
        r = llm.run_agent(_direct_prompt(ctx, ids, probs), run_proc=ctx.run_proc, timeout=1800)
        dur = round(time.time() - t0, 1)
        now_str = datetime.now().strftime("%H:%M:%S")
        print(f"[{now_str}] [direct] Finished batch {range_str} in {dur}s (cost: ${r.cost_usd:.4f}, turns: {r.turns})", flush=True)
        return r.cost_usd

    for attempt in (1, 2):
        if attempt > 1:
            now_str = datetime.now().strftime("%H:%M:%S")
            print(f"[{now_str}] [direct] Starting retry attempt {attempt} for {len(todo)} packet(s)...", flush=True)
        size = config.DIRECT_BATCH_PACKETS
        batches = [todo[i:i + size] for i in range(0, len(todo), size)]
        with ThreadPoolExecutor(max_workers=config.DIRECT_CONCURRENCY) as ex:
            futs = {ex.submit(run_batch, b, {k: problems[k] for k in b if k in problems}): b for b in batches}
            for f in as_completed(futs):
                batch_ids = futs[f]
                range_str = f"{batch_ids[0]}..{batch_ids[-1]}" if len(batch_ids) > 1 else batch_ids[0]
                try:
                    c = f.result()
                except Cancelled:
                    raise
                except llm.LlmLimitError as err:
                    now_str = datetime.now().strftime("%H:%M:%S")
                    print(f"[{now_str}] [direct] LLM rate/usage limit hit during batch {range_str}: {err}", flush=True)
                    limit_hit = True  # retrying cannot help; stop starting new batches
                    for other in futs:
                        other.cancel()
                    continue
                except Exception as e:
                    if ctx.cancelled():
                        raise Cancelled()
                    now_str = datetime.now().strftime("%H:%M:%S")
                    print(f"[{now_str}] [direct] Batch {range_str} failed with error: {e}", flush=True)
                    for pid in batch_ids:
                        problems[pid] = f"agent run failed: {e}"
                    continue
                with lock:
                    cost += c
                    for pid in batch_ids:
                        errs = _check_directed(v, ctx, pid, cast_ids)
                        if errs:
                            problems[pid] = "; ".join(errs)
                            now_str = datetime.now().strftime("%H:%M:%S")
                            print(f"[{now_str}] [direct] Packet {pid} validation rejected: {problems[pid]}", flush=True)
                    ok = sum(1 for pid in batch_ids if not _check_directed(v, ctx, pid, cast_ids))
                    done_count += ok
                msg = f"directing: {done_count}/{len(all_ids)} packets"
                now_str = datetime.now().strftime("%H:%M:%S")
                print(f"[{now_str}] [direct] Progress: {done_count}/{len(all_ids)} packets complete", flush=True)
                ctx.progress(min(1.0, done_count / len(all_ids)), msg)
        if limit_hit:
            raise llm.LlmLimitError(llm.LIMIT_MESSAGE)
        todo = []
        for pid in all_ids:
            errs = _check_directed(v, ctx, pid, cast_ids)
            if errs:
                todo.append(pid)
                problems[pid] = "; ".join(errs)[:300]
        if not todo:
            return StageResult(f"{len(all_ids)} packets directed", cost)
        done_count = len(all_ids) - len(todo)
        now_str = datetime.now().strftime("%H:%M:%S")
        print(f"[{now_str}] [direct] Attempt {attempt} finished: {len(todo)} packet(s) remaining.", flush=True)

    sample_errors = "; ".join(f"{p}: {problems.get(p, 'unknown')}" for p in todo[:5])
    raise RuntimeError(
        f"{len(todo)} packet(s) could not be directed after a retry: {', '.join(todo[:5])}. "
        f"Sample errors: {sample_errors}"
    )


# ---- 8 voices, 9 package ------------------------------------------------------------------------------
def voices_stage(ctx: Ctx) -> StageResult:
    cast_data = json.loads((ctx.manga_dir / "cast.json").read_text(encoding="utf-8"))
    path = ctx.manga_dir / "voices.json"
    existing = voices.load(path)
    updated = voices.assign(cast_data, existing)
    added = [k for k in updated if k not in existing]
    if added or not path.exists():
        voices.save(path, updated)
    return StageResult(f"{len(added)} new voice(s) assigned" if added else "voices unchanged")


def _bundle_ready(ctx: Ctx) -> bool:
    try:
        s = json.loads((ctx.bundle / "script.json").read_text(encoding="utf-8"))
    except Exception:
        return False
    voiced = [b for b in s["beats"] if b.get("tts_text")]
    return bool(voiced) and all(b.get("audio") and b.get("audio_x") for b in voiced)


def package(ctx: Ctx) -> StageResult:
    if _bundle_ready(ctx):
        return StageResult("already done")
    ctx.progress(0.02, "building the reader bundle")
    _script(ctx, "package", "build_bundle.py", timeout=900, extra=[
        "assemble", ctx.images, ctx.run, ctx.bundle,
        "--cast", ctx.manga_dir / "cast.json", "--voices", ctx.manga_dir / "voices.json"])
    ctx.progress(0.1, "recording the voices (about as long as the chapter itself)")
    _script(ctx, "package", "render_audio.py", timeout=7200, extra=[ctx.bundle])
    if not _bundle_ready(ctx):
        raise RuntimeError("the bundle was built but some spoken lines have no audio")
    _make_cover(ctx)
    return StageResult("bundle ready")


def _make_cover(ctx: Ctx) -> None:
    cover = ctx.manga_dir / "cover.jpg"
    if cover.exists():
        return
    first = next(iter(sorted(ctx.images.glob("*.png"))), None)
    if first is None:
        return
    with Image.open(first) as im:
        im = im.convert("RGB").crop((0, 0, im.width, min(im.height, round(im.width * 1.4))))
        im.thumbnail((360, 520))
        im.save(cover, quality=82)


STAGE_FUNCS = {"ingest": ingest, "detect": detect, "ocr": ocr, "fuse": fuse, "packets": packets,
               "cast": cast, "direct": direct, "voices": voices_stage, "package": package}
