"""Validate agent output files. Exits non-zero and prints every problem.

Usage:
  validate.py cast <cast.json>
  validate.py director <packet.json> <directed.json> <cast.json>
  validate.py review <packet.json> <reviewed.json> <cast.json>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

TYPES = {"speech", "thought", "narration", "system", "reaction", "sfx", "credit", "note", "skip"}
NON_SPOKEN = {"sfx", "credit", "note", "skip"}
EMOTIONS = {"neutral", "happy", "excited", "sad", "angry", "afraid", "surprised",
            "embarrassed", "resolute", "sarcastic", "tired", "tender", "menacing"}
SPECIAL = {"narrator", "system", "announcer", "none", "unknown"}


def load(p: str):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def cast_ids(cast: dict) -> set[str]:
    return {c["id"] for c in cast["characters"]}


def check_cast(cast: dict) -> list[str]:
    errs = []
    if not cast.get("characters"):
        errs.append("no characters")
    seen = set()
    for c in cast.get("characters", []):
        for k in ("id", "visual", "gender", "age_band", "voice_hint"):
            if not c.get(k):
                errs.append(f"{c.get('id', '?')}: missing {k}")
        if c.get("id") in seen:
            errs.append(f"duplicate id {c.get('id')}")
        seen.add(c.get("id"))
        if c.get("gender") not in {"male", "female", "unknown"}:
            errs.append(f"{c.get('id')}: bad gender {c.get('gender')}")
        if c.get("age_band") not in {"child", "teen", "young_adult", "adult", "elder"}:
            errs.append(f"{c.get('id')}: bad age_band {c.get('age_band')}")
    if "special_speakers" not in cast:
        errs.append("missing special_speakers")
    return errs


def check_director(packet: dict, out: dict, ids: set[str]) -> list[str]:
    errs = []
    want = [b["id"] for b in packet["beats"]]
    got = [b.get("id") for b in out.get("beats", [])]
    if sorted(want) != sorted(got):
        errs.append(f"beat ids differ: missing {sorted(set(want) - set(got))}, extra {sorted(set(got) - set(want))}")
    if len(got) != len(set(got)):
        errs.append("duplicate beat ids")
    for b in out.get("beats", []):
        i = b.get("id", "?")
        if b.get("type") not in TYPES:
            errs.append(f"{i}: bad type {b.get('type')}")
        if b.get("emotion") not in EMOTIONS:
            errs.append(f"{i}: bad emotion {b.get('emotion')}")
        sp = b.get("speaker")
        if sp not in ids | SPECIAL:
            errs.append(f"{i}: speaker {sp!r} not in cast or special speakers")
        if b.get("type") in NON_SPOKEN and b.get("tts_text"):
            errs.append(f"{i}: non-spoken type {b.get('type')} has tts_text")
        if b.get("type") in {"speech", "thought", "narration", "system"} and not (b.get("tts_text") or "").strip():
            errs.append(f"{i}: spoken type with empty tts_text")
        c = b.get("confidence")
        if not isinstance(c, (int, float)) or not 0 <= c <= 1:
            errs.append(f"{i}: bad confidence {c!r}")
        for k in ("text", "tts_text", "speaker_basis", "delivery", "text_changed"):
            if k not in b:
                errs.append(f"{i}: missing {k}")
    if "missed_text" not in out:
        errs.append("missing missed_text")
    return errs


def check_review(packet: dict, out: dict, ids: set[str]) -> list[str]:
    errs = []
    want = {b["id"] for b in packet["beats"]}
    got = [b.get("id") for b in out.get("beats", [])]
    if want != set(got):
        errs.append(f"beat ids differ: missing {sorted(want - set(got))}, extra {sorted(set(got) - want)}")
    for b in out.get("beats", []):
        i = b.get("id", "?")
        if b.get("reviewer_type") not in TYPES:
            errs.append(f"{i}: bad reviewer_type {b.get('reviewer_type')}")
        if b.get("reviewer_speaker") not in ids | SPECIAL:
            errs.append(f"{i}: bad reviewer_speaker {b.get('reviewer_speaker')!r}")
        for k in ("type_ok", "text_ok"):
            if not isinstance(b.get(k), bool):
                errs.append(f"{i}: {k} must be true/false")
        if b.get("speaker_ok") not in (True, False, None):
            errs.append(f"{i}: speaker_ok must be true/false/null")
    for k in ("missed_text", "false_beats"):
        if k not in out:
            errs.append(f"missing {k}")
    return errs


def main(argv: list[str]) -> int:
    mode = argv[1]
    if mode == "cast":
        errs = check_cast(load(argv[2]))
    elif mode == "director":
        errs = check_director(load(argv[2]), load(argv[3]), cast_ids(load(argv[4])))
    elif mode == "review":
        errs = check_review(load(argv[2]), load(argv[3]), cast_ids(load(argv[4])))
    else:
        print(__doc__)
        return 2
    if errs:
        print("INVALID:")
        for e in errs:
            print("  -", e)
        return 1
    print("valid")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
