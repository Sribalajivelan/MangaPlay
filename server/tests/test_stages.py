"""Real stage code against small fixtures; the Claude CLI is replaced by tests/fake_claude.py."""
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

from server import config, stages, voices

FAKE = Path(__file__).with_name("fake_claude.py")


def run_proc(cmd, *, cwd=None, input_text=None, timeout=600, env=None):
    return subprocess.run(cmd, cwd=cwd, input=input_text, capture_output=True, text=True, timeout=timeout, env=env, encoding="utf-8")


@pytest.fixture(autouse=True)
def fake_claude(monkeypatch):
    monkeypatch.setenv("MANGA_CLAUDE_CMD", json.dumps([sys.executable, str(FAKE)]))


def make_ctx(tmp_path, pages=0) -> stages.Ctx:
    root = tmp_path / "chapter"
    (root / "source").mkdir(parents=True)
    (root / "run").mkdir()
    (tmp_path / "manga").mkdir()
    return stages.Ctx(chapter_id=1, manga_id=1, page_count=pages, source=root / "source", run=root / "run",
                      bundle=root / "bundle", manga_dir=tmp_path / "manga", run_proc=run_proc, cancelled=lambda: False)


# ---- ingest --------------------------------------------------------------------------------------------
def save(path: Path, mode, size, color, fmt):
    Image.new(mode, size, color).save(path, fmt)


def test_ingest_normalises_widths_alpha_and_formats(tmp_path):
    ctx = make_ctx(tmp_path, pages=3)
    save(ctx.source / "001.png", "RGBA", (600, 800), (0, 0, 0, 0), "PNG")      # fully transparent -> must become white
    save(ctx.source / "002.png", "RGB", (690, 900), (10, 20, 30), "PNG")
    save(ctx.source / "003.jpg", "RGB", (690, 700), (200, 100, 50), "JPEG")
    res = stages.ingest(ctx)
    meta = json.loads((ctx.run / "ingest.json").read_text())
    assert meta["width"] == 690 and meta["pages"] == 3                      # the most common width wins
    sizes = [Image.open(p).size for p in sorted(ctx.images.glob("*.png"))]
    assert all(w == 690 for w, _ in sizes) and len(sizes) == 3
    assert sizes[0][1] == round(800 * 690 / 600)                            # aspect ratio kept when resizing
    assert Image.open(ctx.images / "001.png").getpixel((5, 5)) == (255, 255, 255)
    assert "3 pages" in res.note
    assert stages.ingest(ctx).note == "already done"                        # idempotent


def test_ingest_caps_very_wide_pages(tmp_path):
    ctx = make_ctx(tmp_path, pages=1)
    save(ctx.source / "001.png", "RGB", (1800, 600), (1, 2, 3), "PNG")
    stages.ingest(ctx)
    assert Image.open(ctx.images / "001.png").size == (stages.MAX_WIDTH, 300)


def test_ingest_refuses_decompression_bombs(tmp_path, monkeypatch):
    monkeypatch.setattr(stages, "MAX_PIXELS", 1000)
    ctx = make_ctx(tmp_path, pages=1)
    save(ctx.source / "001.png", "RGB", (100, 100), (0, 0, 0), "PNG")
    with pytest.raises(RuntimeError, match="too large"):
        stages.ingest(ctx)


def test_ingest_detects_missing_pages(tmp_path):
    ctx = make_ctx(tmp_path, pages=3)
    save(ctx.source / "001.png", "RGB", (690, 100), (0, 0, 0), "PNG")
    with pytest.raises(RuntimeError, match="expected 3"):
        stages.ingest(ctx)


# ---- voices --------------------------------------------------------------------------------------------
CAST = {"characters": [
    {"id": "c1", "gender": "male", "age_band": "adult", "voice_hint": "gruff"},
    {"id": "c2", "gender": "female", "age_band": "teen", "voice_hint": "bright"},
    {"id": "c3", "gender": "male", "age_band": "child"},
    {"id": "c4", "gender": "unknown", "age_band": "elder"},
]}


def test_voices_are_distinct_gendered_and_age_shaped():
    v = voices.assign(CAST)
    chars = [v[c] for c in ("c1", "c2", "c3", "c4")]
    assert len({c["voice"] for c in chars}) == 4                              # nobody shares a voice
    assert v["c1"]["voice"][1] == "m" and v["c2"]["voice"][1] == "f" and v["c3"]["voice"][1] == "m"
    assert v["c2"]["pitch_st"] > 0 and v["c1"]["pitch_st"] < 0                # teen higher, adult lower
    assert v["c3"]["pitch_st"] > v["c2"]["pitch_st"]                          # child higher than teen
    assert v["c4"]["pitch_st"] < v["c1"]["pitch_st"]                          # elder lowest
    reserved = {v[k]["voice"] for k in ("narrator", "system", "announcer", "unknown")}
    assert not reserved & {c["voice"] for c in chars}                         # specials keep their own voices


def test_existing_voices_are_never_changed_and_new_characters_slot_in():
    first = voices.assign(CAST)
    cast2 = {"characters": CAST["characters"] + [{"id": "c5", "gender": "female", "age_band": "young_adult"}]}
    second = voices.assign(cast2, first)
    assert {k: second[k] for k in first} == first
    assert second["c5"]["voice"] not in {first[c]["voice"] for c in ("c1", "c2", "c3", "c4")}


def test_voice_pool_exhaustion_does_not_crash():
    cast = {"characters": [{"id": f"c{i}", "gender": "female", "age_band": "teen"} for i in range(40)]}
    v = voices.assign(cast)
    assert all(f"c{i}" in v for i in range(40))


# ---- cast (model step) ---------------------------------------------------------------------------------
def test_cast_first_chapter_builds_and_publishes(tmp_path):
    ctx = make_ctx(tmp_path)
    res = stages.cast(ctx)
    assert res.cost_usd == pytest.approx(0.25) and "1 characters" in res.note
    assert json.loads((ctx.manga_dir / "cast.json").read_text())["characters"][0]["id"] == "c1"
    assert stages.cast(ctx).note == "already done"                            # no second model call


def test_cast_later_chapter_extends_and_keeps_ids(tmp_path):
    ctx = make_ctx(tmp_path)
    stages.cast(ctx)
    (ctx.run / "cast" / "cast.json").unlink()                                 # next chapter: new run folder, same manga
    res = stages.cast(ctx)
    ids = [c["id"] for c in json.loads((ctx.manga_dir / "cast.json").read_text())["characters"]]
    assert ids == ["c1", "c2"] and "2 characters" in res.note


def test_cast_that_drops_existing_characters_is_rejected(tmp_path, monkeypatch):
    ctx = make_ctx(tmp_path)
    stages.cast(ctx)
    (ctx.run / "cast" / "cast.json").unlink()
    monkeypatch.setenv("FAKE_DROP", "1")
    with pytest.raises(RuntimeError, match="existing character ids were dropped"):
        stages.cast(ctx)
    ids = [c["id"] for c in json.loads((ctx.manga_dir / "cast.json").read_text())["characters"]]
    assert ids == ["c1"]                                                      # the manga's cast was not damaged


def test_cast_agent_error_surfaces(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_ERROR", "1")
    with pytest.raises(Exception, match="agent reported an error"):
        stages.cast(make_ctx(tmp_path))


# ---- direct (model step) -------------------------------------------------------------------------------
def direct_fixture(tmp_path, n_packets=8):
    ctx = make_ctx(tmp_path)
    stages.cast(ctx)
    (ctx.run / "packets").mkdir()
    index = []
    for i in range(1, n_packets + 1):
        pid = f"p{i:02d}"
        beats = [{"id": f"b{i}{k}", "draft_type": "speech", "draft_text": "x"} for k in range(2)]
        (ctx.run / "packets" / f"{pid}.json").write_text(json.dumps({"packet_id": pid, "beats": beats}))
        index.append({"packet_id": pid, "beat_ids": [b["id"] for b in beats]})
    (ctx.run / "packets" / "index.json").write_text(json.dumps(index))
    return ctx


def test_direct_directs_every_packet_in_batches(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DIRECT_BATCH_PACKETS", 3)
    ctx = direct_fixture(tmp_path, n_packets=8)
    calls = []
    real = stages.llm.run_agent
    monkeypatch.setattr(stages.llm, "run_agent", lambda *a, **k: (calls.append(a[0]), real(*a, **k))[1])
    res = stages.direct(ctx)
    assert len(list((ctx.run / "directed").glob("p*.json"))) == 8
    assert len(calls) == 3                                                    # 8 packets in batches of 3
    assert res.cost_usd == pytest.approx(0.75) and "8 packets" in res.note
    assert stages.direct(ctx).note == "already done"                          # nothing re-run, nothing re-paid


def test_direct_retries_only_what_is_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_SKIP_MARKER", str(tmp_path / "skip.marker"))
    ctx = direct_fixture(tmp_path, n_packets=4)
    prompts = []
    real = stages.llm.run_agent
    monkeypatch.setattr(stages.llm, "run_agent", lambda *a, **k: (prompts.append(a[0]), real(*a, **k))[1])
    stages.direct(ctx)
    assert (ctx.run / "directed" / "p02.json").is_file()
    assert len(prompts) == 2 and "p02" in prompts[1] and "file not written" in prompts[1]
    assert "p01" not in prompts[1].split("Your packets, in order:")[1].split(".")[0]   # p01 was not redone


def test_direct_rejects_invalid_output_and_asks_again(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_BAD_MARKER", str(tmp_path / "bad.marker"))
    ctx = direct_fixture(tmp_path, n_packets=4)
    stages.direct(ctx)
    data = json.loads((ctx.run / "directed" / "p03.json").read_text())
    assert {b["speaker"] for b in data["beats"]} == {"c1"}                    # the c99 answer never survived


def test_direct_gives_up_with_a_clear_message(tmp_path, monkeypatch):
    ctx = direct_fixture(tmp_path, n_packets=2)
    monkeypatch.setattr(stages.llm, "run_agent", lambda *a, **k: stages.llm.LlmResult("done", 0.1, 1))  # writes nothing
    with pytest.raises(RuntimeError, match="could not be directed after a retry: p01, p02"):
        stages.direct(ctx)


def test_usage_limit_stops_the_cast_step_with_a_clear_message(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_LIMIT", "1")
    with pytest.raises(stages.llm.LlmLimitError, match="usage limit reached"):
        stages.cast(make_ctx(tmp_path))


def test_usage_limit_stops_direct_without_retrying(tmp_path, monkeypatch):
    ctx = direct_fixture(tmp_path, n_packets=6)
    monkeypatch.setattr(config, "DIRECT_BATCH_PACKETS", 2)   # 3 batches
    monkeypatch.setenv("FAKE_LIMIT", "1")
    calls = []
    real = stages.llm.run_agent
    monkeypatch.setattr(stages.llm, "run_agent", lambda *a, **k: (calls.append(1), real(*a, **k))[1])
    with pytest.raises(stages.llm.LlmLimitError, match="press Retry after your limit resets"):
        stages.direct(ctx)
    assert len(calls) <= 3                                    # at most one attempt per batch: no second round
    assert not list((ctx.run / "directed").glob("p*.json"))   # and nothing half-written is left behind


def test_other_agent_errors_are_not_mistaken_for_limits(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_ERROR", "1")                     # "overloaded": transient, a retry is allowed
    with pytest.raises(stages.llm.LlmError) as e:
        stages.cast(make_ctx(tmp_path))
    assert not isinstance(e.value, stages.llm.LlmLimitError)


def test_voices_stage_creates_and_keeps_manga_voices(tmp_path):
    ctx = make_ctx(tmp_path)
    stages.cast(ctx)
    first_note = stages.voices_stage(ctx).note
    assert "new voice(s) assigned" in first_note and first_note.startswith("5 ")   # c1 + the 4 special speakers
    path = ctx.manga_dir / "voices.json"
    first = json.loads(path.read_text())
    assert "c1" in first and "narrator" in first
    assert stages.voices_stage(ctx).note == "voices unchanged"
    assert json.loads(path.read_text()) == first


def test_cast_and_direct_with_agy_provider(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "agy")
    monkeypatch.setenv("MANGA_AGY_CMD", json.dumps([sys.executable, str(FAKE)]))
    monkeypatch.setenv("FAKE_PROVIDER", "agy")
    ctx = direct_fixture(tmp_path, n_packets=2)
    res = stages.direct(ctx)
    assert len(list((ctx.run / "directed").glob("p*.json"))) == 2
    assert "2 packets" in res.note

