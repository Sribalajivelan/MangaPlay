"""Fuse OCR text blocks with bubble-detector boxes into draft beats for the Director step.

Rules (all deterministic, all recorded on the beat so a reviewer can see why):
  - OCR block inside a `text_bubble` box            -> type "speech"  (could be a thought; Director decides)
  - OCR block inside `text_free` or in no detection -> type "caption" (narration / system window / SFX-like)
  - detector box with no OCR text                   -> type "reaction" (punctuation-only bubble, e.g. "!?")
  - credit / watermark text                         -> type "credit" (never spoken)
  - tokens of 10+ letters without spaces are split with wordninja ("ALLIHADTODOWAS" -> "ALL I HAD TO DO WAS")

Run: .venv\\Scripts\\python.exe spike\\detect\\fuse.py <run_dir>
Writes <run_dir>/draft_beats.json
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

import wordninja

CREDIT_RE = re.compile(
    r"ko-?fi|translator|typesetter|redrawer|proofreader|cleaner|quality checker|our links|staff|discord|"
    r"translations|scanlat|read (it )?(first )?(at|on)|support us|join (us|our)",
    re.I,
)


def center(b):
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)


def inside(p, b, pad=6):
    return b[0] - pad <= p[0] <= b[2] + pad and b[1] - pad <= p[1] <= b[3] + pad


MIN_RUNON = 7  # letters; shorter tokens are left alone


def repair_spacing(text: str, protected: set[str]) -> tuple[str, bool]:
    changed = False

    def fix(m: re.Match) -> str:
        nonlocal changed
        tok = m.group(0)
        if len(tok) < MIN_RUNON or tok.upper() in protected:
            return tok
        parts = wordninja.split(tok.lower())
        if len(parts) < 2:
            return tok
        changed = True
        return " ".join(p.upper() if tok.isupper() else p for p in parts)

    out = re.sub(r"[A-Za-z]+", fix, text)
    spaced = re.sub(r"([,;!?])(?=[A-Za-z])", lambda m: m.group(1) + " ", out)  # "IMAGINABLE,ONE" -> "IMAGINABLE, ONE"
    return spaced, changed or spaced != out


def main(run: Path) -> None:
    D = json.loads((run / "detect.json").read_text(encoding="utf-8"))
    T = json.loads((run / "ocr.json").read_text(encoding="utf-8"))
    dets, blocks = D["bubbles"], T["blocks"]
    seg = [tuple(s) for s in D["segments"]]
    names = {0: "text_bubble", 1: "text_free"}

    def segment_of(y: float) -> int | None:
        for i, (a, b) in enumerate(seg):
            if a <= y < b:
                return i
        return None

    # A token that recurs is almost certainly a real word or a name (OCR glitches rarely repeat),
    # so never split it. This keeps invented names like "KELLERMAIN" intact.
    # A recurring token is protected from splitting only if it recurs in CLEAN blocks, i.e. blocks
    # where no other long token needs splitting. Invented names ("KELLERMAIN") sit in normally
    # spaced text and repeat; a repeated run-on line (a quote shown twice) has other run-ons next to it.
    clean_counts: Counter = Counter()
    for t in blocks:
        toks = [w.upper() for w in re.findall(r"[A-Za-z]{%d,}" % MIN_RUNON, t["text"])]
        splittable = [w for w in toks if len(wordninja.split(w.lower())) >= 2]
        if len(splittable) <= 1:
            clean_counts.update(splittable)
    protected = {w for w, n in clean_counts.items() if n >= 2}

    beats, used = [], set()
    for t in blocks:
        c = center(t["box"])
        hit = next((d for d in dets if inside(c, d["box"])), None)
        text, repaired = repair_spacing(t["text"], protected)
        if CREDIT_RE.search(t["text"]):
            typ = "credit"
        elif hit and hit["cls"] == 0:
            typ = "speech"
        else:
            typ = "caption"
        if hit:
            used.add(hit["id"])
        beats.append({
            "type": typ,
            "box": t["box"],
            "bubble_box": hit["box"] if hit else None,
            "detector_class": names[hit["cls"]] if hit else None,
            "text": text,
            "ocr_text": t["text"] if repaired else None,
            "spacing_repaired": repaired,
            "ocr_score": t["score"],
            "segment": segment_of(c[1]),
        })
    for d in dets:
        # a bubble holding several OCR blocks is already "used"; only truly empty ones become reactions
        if d["id"] in used or any(inside(center(t["box"]), d["box"]) for t in blocks):
            continue
        beats.append({
            "type": "reaction", "box": d["box"], "bubble_box": d["box"],
            "detector_class": names[d["cls"]], "text": "", "ocr_text": None,
            "spacing_repaired": False, "ocr_score": None, "detector_conf": d["conf"],
            "segment": segment_of(center(d["box"])[1]),
        })
    beats.sort(key=lambda b: (b["box"][1], b["box"][0]))
    for i, b in enumerate(beats, 1):
        b["id"] = f"b{i:03d}"
        b["needs_review"] = bool(
            b["spacing_repaired"] or b["type"] == "reaction"
            or (b["ocr_score"] is not None and b["ocr_score"] < 0.8)
            or (b["type"] == "speech" and b["detector_class"] is None)
        )
    out = {"strip": D["strip"], "segments": D["segments"], "beats": beats}
    (run / "draft_beats.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print("beats:", len(beats), dict(Counter(b["type"] for b in beats)))
    print("spacing repaired:", sum(b["spacing_repaired"] for b in beats),
          "| needs_review:", sum(b["needs_review"] for b in beats))
    spoken = [b for b in beats if b["type"] in {"speech", "caption", "reaction"}]
    words = sum(len(b["text"].split()) for b in spoken)
    print(f"spoken-ish beats: {len(spoken)}, words: {words}, est. speech minutes at ~2.6 words/s: {words/2.6/60:.1f}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
