"""Per-manga voice assignment: every cast member keeps one voice in every chapter."""
from __future__ import annotations

import json
from pathlib import Path

# Kokoro voices (see docs/04): reserved for the non-character speakers so a character never shares them.
SPECIAL = {
    "narrator": {"voice": "am_adam", "pitch_st": 0.0, "speed": 1.0, "note": "outside narrator"},
    "system": {"voice": "af_alloy", "pitch_st": 0.0, "speed": 1.0, "note": "game system windows"},
    "announcer": {"voice": "af_jessica", "pitch_st": 0.0, "speed": 1.0, "note": "in-world broadcast"},
    "unknown": {"voice": "af_sarah", "pitch_st": 0.0, "speed": 1.0, "note": "no directed speaker"},
}
POOL = {
    "female": ["af_heart", "bf_emma", "af_bella", "af_nicole", "af_sky", "af_nova", "af_river", "af_kore", "af_aoede", "bf_isabella", "bf_alice", "bf_lily"],
    "male": ["am_michael", "bm_george", "am_liam", "am_eric", "am_onyx", "am_echo", "am_fenrir", "am_puck", "bm_lewis", "bm_daniel", "bm_fable"],
}
# age band -> (pitch semitones, speed). Pitch is shifted with the formants, so up reads younger, down older.
AGE = {"child": (4.0, 1.08), "teen": (2.5, 1.05), "young_adult": (0.0, 1.0), "adult": (-1.0, 0.97), "elder": (-2.5, 0.92)}


def assign(cast: dict, existing: dict | None = None) -> dict:
    """Return voices for every cast id and special speaker. Entries that already exist are never changed."""
    voices = {k: v for k, v in (existing or {}).items() if not k.startswith("_")}
    for k, v in SPECIAL.items():
        voices.setdefault(k, dict(v))
    reserved = {v["voice"] for k, v in SPECIAL.items()}
    used = {v["voice"] for v in voices.values()}
    flip = 0
    for ch in cast.get("characters", []):
        if ch["id"] in voices:
            continue
        gender = ch.get("gender")
        if gender not in POOL:  # unknown: alternate so a group of unknowns is not all one gender
            gender = ["female", "male"][flip % 2]
            flip += 1
        free = [v for v in POOL[gender] if v not in used and v not in reserved]
        voice = free[0] if free else POOL[gender][len(used) % len(POOL[gender])]  # pool exhausted: reuse, pitch differs
        pitch, speed = AGE.get(ch.get("age_band", "young_adult"), AGE["young_adult"])
        voices[ch["id"]] = {"voice": voice, "pitch_st": pitch, "speed": speed,
                            "note": f"{ch.get('gender','?')} {ch.get('age_band','?')}: {ch.get('voice_hint','')}"}
        used.add(voice)
    return voices


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save(path: Path, voices: dict) -> None:
    out = {"_comment": "Cast id -> Kokoro voice + age profile. Edit freely; existing entries are never overwritten automatically."}
    out.update(voices)
    path.write_text(json.dumps(out, indent=1), encoding="utf-8")
