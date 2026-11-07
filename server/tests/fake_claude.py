"""A stand-in for the `claude` CLI, so the cast/direct logic can be tested without spending usage.

Reads the prompt from stdin like `claude -p` does, writes the files the real agent would write, and
prints the same kind of JSON result. Failure modes are switched on with environment variables:
  FAKE_SKIP_MARKER=<file>   first call leaves packet p02 unwritten (creates the marker), later calls write it
  FAKE_BAD_MARKER=<file>    first call writes an invalid speaker for p03, later calls write it correctly
  FAKE_DROP=1               cast: drop existing characters (must be rejected)
  FAKE_ERROR=1              exit with an error result
"""
import json
import os
import re
import sys
from pathlib import Path

prompt = sys.stdin.read()
run = Path(re.search(r"RUN = (.+)", prompt).group(1).strip())


def result(cost=0.25):
    if os.environ.get("FAKE_PROVIDER") == "agy":
        print(json.dumps({
            "conversation_id": "fake-conversation-123",
            "status": "SUCCESS",
            "response": "done",
            "duration_seconds": 1.5,
            "num_turns": 3,
            "usage": {"input_tokens": 1000, "output_tokens": 500, "total_tokens": 1500}
        }))
    else:
        print(json.dumps({"result": "done", "total_cost_usd": cost, "num_turns": 3, "is_error": False}))


if os.environ.get("FAKE_LIMIT"):
    if os.environ.get("FAKE_PROVIDER") == "agy":
        print(json.dumps({"status": "ERROR", "response": "RESOURCE_EXHAUSTED: quota exceeded"}))
    else:
        print(json.dumps({"result": "Claude AI usage limit reached|1731000000", "is_error": True}))
    sys.exit(0)

if os.environ.get("FAKE_ERROR"):
    if os.environ.get("FAKE_PROVIDER") == "agy":
        print(json.dumps({"status": "ERROR", "response": "overloaded"}))
    else:
        print(json.dumps({"result": "overloaded", "is_error": True}))
    sys.exit(0)

if "Cast Builder" in prompt:
    chars = [{"id": "c1", "name": "Hero", "aliases": [], "visual": "dark hair", "icon": None, "role": "protagonist",
              "gender": "male", "age_band": "young_adult", "voice_hint": "calm", "seen_at_y": [10, 20]}]
    if "EXTEND MODE" in prompt:
        existing = json.loads(Path(re.search(r"cast at (.+?cast\.json)", prompt).group(1)).read_text(encoding="utf-8"))["characters"]
        new = {"id": f"c{len(existing) + 1}", "name": None, "aliases": [], "visual": "red scarf", "icon": None, "role": "rival",
               "gender": "female", "age_band": "teen", "voice_hint": "sharp", "seen_at_y": [30, 40]}
        chars = [new] if os.environ.get("FAKE_DROP") else existing + [new]
    out = run / "cast" / "cast.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"episode": "x", "characters": chars,
                               "special_speakers": {"narrator": "n", "system": "s", "announcer": "a"}, "uncertain": []}), encoding="utf-8")
    result()
else:
    ids = [s.strip() for s in re.search(r"Your packets, in order: ([^.]+)\.", prompt).group(1).split(",")]
    (run / "directed").mkdir(exist_ok=True)
    for pid in ids:
        skip, bad = os.environ.get("FAKE_SKIP_MARKER"), os.environ.get("FAKE_BAD_MARKER")
        if skip and pid == "p02" and not Path(skip).exists():
            Path(skip).write_text("x")
            continue
        packet = json.loads((run / "packets" / f"{pid}.json").read_text(encoding="utf-8"))
        speaker = "c1"
        if bad and pid == "p03" and not Path(bad).exists():
            Path(bad).write_text("x")
            speaker = "c99"  # not in the cast: the validator must reject this
        beats = [{"id": b["id"], "type": "speech", "text": "HI", "tts_text": "Hi.", "speaker": speaker, "speaker_basis": "tail",
                  "emotion": "neutral", "delivery": "flat", "confidence": 0.9, "text_changed": False} for b in packet["beats"]]
        (run / "directed" / f"{pid}.json").write_text(json.dumps({"packet_id": pid, "beats": beats, "missed_text": []}), encoding="utf-8")
    result()
