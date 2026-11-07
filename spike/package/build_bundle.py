"""Assemble a Chapter Bundle: script.json + web images + (separately) audio.

  build_bundle.py assemble <images_folder> <run_dir> <bundle_dir>
      merges Director output (where it exists) over the OCR/detector draft beats, copies the
      strip slices as webp, writes script.json (no audio yet).

Beats from a directed packet carry source="directed"; every other beat falls back to the draft
(source="draft"): captions read by the narrator, speech by an "unknown" voice, credits and
reactions silent. This is the design's "fall back to plain reading" behaviour for pages the
agents have not processed yet.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "detect"))
from strip import Strip  # noqa: E402

VOICED_DIRECTED = {"speech", "thought", "narration", "system", "reaction"}
EMOTION_SPEED = {"angry": 1.08, "excited": 1.1, "afraid": 1.08, "surprised": 1.06,
                 "sad": 0.92, "tired": 0.92, "tender": 0.94, "menacing": 0.9}


def sentence_case(t: str) -> str:
    """OCR text is ALL CAPS; voices read lower case more naturally."""
    letters = [c for c in t if c.isalpha()]
    if letters and sum(c.isupper() for c in letters) / len(letters) > 0.7:
        t = t.lower()
    t = re.sub(r"(^|[.!?]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), t.strip())
    t = re.sub(r"\bi\b", "I", t)
    t = re.sub(r"\bi'(m|ll|d|ve)\b", lambda m: "I'" + m.group(1), t)
    return t


# emotion -> (pitch semitones, speed multiplier, loudness). Small, speech-safe moves: local TTS cannot act,
# it can only be shaped. Real acting is the paid-voice upgrade (decision D4).
EMOTION_STYLE = {
    "neutral": (0.0, 1.00, 1.00), "happy": (0.8, 1.04, 1.00), "excited": (1.4, 1.10, 1.05),
    "surprised": (1.8, 1.05, 1.05), "embarrassed": (1.0, 1.00, 0.90), "afraid": (1.2, 1.10, 0.95),
    "angry": (-0.4, 1.08, 1.10), "resolute": (-0.4, 0.97, 1.00), "sarcastic": (-0.3, 0.95, 1.00),
    "tender": (-0.3, 0.92, 0.85), "sad": (-1.2, 0.90, 0.85), "tired": (-0.9, 0.88, 0.85),
    "menacing": (-1.8, 0.88, 1.00),
}


def delivery_params(emotion: str | None, delivery: str | None) -> tuple[float, float]:
    """PLAIN version (what the first listening tests used): emotion only nudges speed, plus whisper/quiet loudness."""
    speed = EMOTION_SPEED.get(emotion or "", 1.0)
    gain = 1.0
    d = (delivery or "").lower()
    if "whisper" in d or "hushed" in d or "murmur" in d:
        speed, gain = min(speed, 0.92), 0.6
    elif "quiet" in d or "soft" in d:
        gain = 0.8
    elif "shout" in d or "yell" in d or "scream" in d:
        speed, gain = max(speed, 1.08), 1.0
    return round(speed, 3), gain


def expressive_params(emotion: str | None, delivery: str | None, profile: dict) -> tuple[float, float, float]:
    """EXPRESSIVE version: character age profile + emotion + delivery -> (speed, gain, pitch semitones)."""
    pitch, speed, gain = EMOTION_STYLE.get(emotion or "neutral", EMOTION_STYLE["neutral"])
    d = (delivery or "").lower()
    if any(k in d for k in ("whisper", "hushed", "murmur")):
        speed, gain = speed * 0.92, gain * 0.6
    elif any(k in d for k in ("shout", "yell", "scream", "bellow")):
        pitch, gain, speed = pitch + 0.8, gain * 1.2, speed * 1.05
    elif any(k in d for k in ("quiet", "soft", "muttered", "low")):
        gain *= 0.85
    if any(k in d for k in ("trailing off", "hesitant", "reluctant")):
        speed *= 0.95
    if any(k in d for k in ("stammer", "nervous", "flustered")):
        pitch += 0.5
    pitch += float(profile.get("pitch_st", 0.0))      # age / character
    speed *= float(profile.get("speed", 1.0))
    return (round(max(0.8, min(1.2, speed)), 3), round(max(0.4, min(1.25, gain)), 3), round(max(-4.5, min(4.5, pitch)), 2))


def main(images: Path, run: Path, bundle: Path, copy_images: bool = True,
         cast_path: Path | None = None, voices_path: Path | None = None) -> None:
    strip = Strip(images)
    draft = json.loads((run / "draft_beats.json").read_text(encoding="utf-8"))["beats"]
    cast_path = cast_path or (run / "cast" / "cast.json")
    voices_path = voices_path or (Path(__file__).parent / "voices.json")
    cast = json.loads(cast_path.read_text(encoding="utf-8"))
    voices = json.loads(voices_path.read_text(encoding="utf-8"))

    directed: dict[str, dict] = {}
    for f in sorted((run / "directed").glob("p*.json")):
        for b in json.loads(f.read_text(encoding="utf-8"))["beats"]:
            directed[b["id"]] = b

    beats = []
    for d in draft:
        bid = d["id"]
        bubble = d["bubble_box"] or d["box"]
        base = {
            "id": bid,
            "bbox": d["box"],            # tight text box: scroll target
            "bubble": bubble,            # outline: highlight
        }
        if bid in directed:
            x = directed[bid]
            spoken = x["type"] in VOICED_DIRECTED and (x.get("tts_text") or "").strip()
            speed, gain = delivery_params(x["emotion"], x["delivery"])
            speaker = x["speaker"]
            beats.append({**base, "source": "directed", "type": x["type"], "speaker": speaker,
                          "text": x["text"], "tts_text": x["tts_text"] if spoken else "",
                          "emotion": x["emotion"], "delivery": x["delivery"],
                          "confidence": x["confidence"], "speed": speed, "gain": gain,
                          "_emotion": x["emotion"], "_delivery": x["delivery"]})
        else:
            typ = d["type"]
            spoken = typ in {"speech", "caption"} and d["text"].strip()
            speaker = "narrator" if typ == "caption" else ("unknown" if typ == "speech" else "none")
            beats.append({**base, "source": "draft", "type": typ, "speaker": speaker,
                          "text": d["text"], "tts_text": sentence_case(d["text"]) if spoken else "",
                          "emotion": "neutral", "delivery": "", "confidence": None, "speed": 1.0, "gain": 1.0,
                          "_emotion": "neutral", "_delivery": ""})
    # Packets are cut top to bottom, so concatenating them is page order. Inside a packet the Director may
    # say the speaking order differs from the page order (speak_order); honour it only there.
    by_id = {b["id"]: b for b in beats}
    ordered: list[dict] = []
    for pk in json.loads((run / "packets" / "index.json").read_text(encoding="utf-8")):
        ids = pk["beat_ids"]
        keyed = sorted(
            enumerate(ids),
            key=lambda t: (directed.get(t[1], {}).get("speak_order") or (t[0] + 1), t[0]),
        )
        ordered += [by_id[i] for _, i in keyed]
    assert len(ordered) == len(beats) and {b["id"] for b in ordered} == set(by_id), "packets do not cover all beats"
    beats = ordered

    # Human / policy corrections survive every re-run (design: overrides.json). Overrides win over the Director.
    allowed = {c["id"] for c in cast["characters"]} | {"narrator", "system", "announcer", "unknown", "none"}
    ov_path = bundle / "overrides.json"
    overrides = json.loads(ov_path.read_text(encoding="utf-8")).get("beats", {}) if ov_path.exists() else {}
    by_id = {b["id"]: b for b in beats}
    for bid, o in overrides.items():
        if bid not in by_id:
            print(f"warning: override for unknown beat {bid} ignored")
            continue
        b = by_id[bid]
        if "speaker" in o:
            if o["speaker"] not in allowed:
                raise ValueError(f"override {bid}: unknown speaker {o['speaker']!r}")
            b["override"] = {"by": o.get("by", "user"), "was": b["speaker"]}
            b["speaker"] = o["speaker"]
        if o.get("muted"):
            b["tts_text"] = ""
            b["override"] = {"by": o.get("by", "user"), "was": b["speaker"], "muted": True}

    # expressive parameters depend on the FINAL speaker (a correction changes the character profile too)
    profiles = {k: {"pitch_st": v.get("pitch_st", 0.0), "speed": v.get("speed", 1.0)}
                for k, v in voices.items() if not k.startswith("_")}
    for b in beats:
        sp, ga, pi = expressive_params(b.pop("_emotion"), b.pop("_delivery"), profiles.get(b["speaker"], {}))
        b["x_speed"], b["x_gain"], b["x_pitch"] = sp, ga, pi

    # slices -> webp (skipped on a fast rebuild: the images do not change when a voice does)
    (bundle / "strip").mkdir(parents=True, exist_ok=True)
    slices = []
    for i, s in enumerate(strip.slices, 1):
        out = bundle / "strip" / f"{i:03d}.webp"
        if copy_images or not out.exists():
            with Image.open(s.path) as im:
                im.convert("RGB").save(out, "WEBP", quality=85, method=4)
        slices.append({"file": f"strip/{i:03d}.webp", "y": s.y, "h": s.h})

    script = {
        "schema_version": 1,
        "episode": images.parent.name,
        "reading_direction": "vertical",
        "strip": {"width": strip.width, "height": strip.height, "slices": slices},
        "cast": [{"id": c["id"], "name": c.get("name") or c.get("role") or c["id"]} for c in cast["characters"]]
                + [{"id": k, "name": k} for k in ("narrator", "system", "announcer", "unknown")],
        "voices": {k: v["voice"] for k, v in voices.items() if not k.startswith("_")},
        "profiles": profiles,
        "beats": beats,
    }
    (bundle / "script.json").write_text(json.dumps(script, ensure_ascii=False), encoding="utf-8")
    (bundle / "build.json").write_text(json.dumps({"images": str(images.resolve()), "run": str(run.resolve()),
                                                  "cast": str(cast_path.resolve()), "voices": str(voices_path.resolve())}), encoding="utf-8")
    n_dir = sum(b["source"] == "directed" for b in beats)
    voiced = sum(bool(b["tts_text"]) for b in beats)
    size = sum(f.stat().st_size for f in (bundle / "strip").iterdir()) / 1e6
    print(f"beats {len(beats)} (directed {n_dir}, draft {len(beats)-n_dir}); voiced {voiced}; webp {size:.1f} MB -> {bundle}")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a_ = sub.add_parser("assemble")
    a_.add_argument("images", type=Path); a_.add_argument("run", type=Path); a_.add_argument("bundle", type=Path)
    a_.add_argument("--cast", type=Path); a_.add_argument("--voices", type=Path)
    r_ = sub.add_parser("rebuild")
    r_.add_argument("bundle", type=Path)
    args = ap.parse_args()
    if args.cmd == "assemble":
        main(args.images, args.run, args.bundle, cast_path=args.cast, voices_path=args.voices)
    else:
        # fast path used by the reader's "wrong voice" button: re-apply overrides, re-render only changed lines
        cfg = json.loads((args.bundle / "build.json").read_text(encoding="utf-8"))
        main(Path(cfg["images"]), Path(cfg["run"]), args.bundle, copy_images=False,
             cast_path=Path(cfg["cast"]) if cfg.get("cast") else None, voices_path=Path(cfg["voices"]) if cfg.get("voices") else None)
        sys.path.insert(0, str(Path(__file__).parent))
        import render_audio  # noqa: E402

        sys.exit(1 if render_audio.main(args.bundle) else 0)
