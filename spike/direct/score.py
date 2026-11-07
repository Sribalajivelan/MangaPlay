"""Reviewer input prep + Director/Reviewer agreement scoring.

  score.py prep  <run_dir> p05 p13 ...     -> writes reviewer_input/pNN.json (reasoning stripped)
  score.py score <run_dir> p05 p13 ...     -> prints agreement metrics, writes score.json

Agreement is NOT accuracy: two model passes can share a blind spot. It is a cheap signal for
where to look; the human verification sheet is the real accuracy check.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

SPOKEN = {"speech", "thought", "narration", "system", "reaction"}


def jload(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def prep(run: Path, pids: list[str]) -> None:
    out = run / "reviewer_input"
    out.mkdir(exist_ok=True)
    keep = ("id", "type", "text", "tts_text", "speaker", "emotion")
    for pid in pids:
        d = jload(run / "directed" / f"{pid}.json")
        (out / f"{pid}.json").write_text(json.dumps(
            {"packet_id": pid, "beats": [{k: b[k] for k in keep} for b in d["beats"]]},
            indent=1, ensure_ascii=False), encoding="utf-8")
    print("wrote", len(pids), "reviewer inputs")


def score(run: Path, pids: list[str]) -> None:
    n = Counter()
    low_conf, hi_conf = Counter(), Counter()
    disagreements = []
    changed = 0
    types = Counter()
    missed = false_b = 0
    for pid in pids:
        d = {b["id"]: b for b in jload(run / "directed" / f"{pid}.json")["beats"]}
        r = {b["id"]: b for b in jload(run / "reviewed" / f"{pid}.json")["beats"]}
        rj = jload(run / "reviewed" / f"{pid}.json")
        missed += len(rj.get("missed_text", []))
        false_b += len(rj.get("false_beats", []))
        dj = jload(run / "directed" / f"{pid}.json")
        missed_dir = len(dj.get("missed_text", []))
        n["director_missed_text_items"] += missed_dir
        for bid, b in d.items():
            rv = r[bid]
            n["beats"] += 1
            types[b["type"]] += 1
            changed += bool(b.get("text_changed"))
            n["type_ok"] += bool(rv["type_ok"])
            n["text_ok"] += bool(rv["text_ok"])
            if b["type"] in SPOKEN:
                n["spoken"] += 1
                if rv["speaker_ok"] is None:
                    n["speaker_undecided"] += 1
                else:
                    n["speaker_decided"] += 1
                    n["speaker_ok"] += bool(rv["speaker_ok"])
                    bucket = hi_conf if b["confidence"] >= 0.7 else low_conf
                    bucket["n"] += 1
                    bucket["ok"] += bool(rv["speaker_ok"])
            if not rv["type_ok"] or not rv["text_ok"] or rv["speaker_ok"] is False:
                disagreements.append({
                    "packet": pid, "beat": bid, "director": {k: b[k] for k in ("type", "speaker", "text")},
                    "reviewer": {"type": rv["reviewer_type"], "speaker": rv["reviewer_speaker"], "text": rv["reviewer_text"]},
                    "flags": [k for k, ok in (("type", rv["type_ok"]), ("text", rv["text_ok"]), ("speaker", rv["speaker_ok"])) if ok is False],
                })
    pct = lambda a, b: f"{100*a/b:.0f}%" if b else "n/a"
    print(f"beats {n['beats']}  types {dict(types)}")
    print(f"type agreement      {n['type_ok']}/{n['beats']} = {pct(n['type_ok'], n['beats'])}")
    print(f"text agreement      {n['text_ok']}/{n['beats']} = {pct(n['text_ok'], n['beats'])}   (Director changed text on {changed} beats)")
    print(f"speaker agreement   {n['speaker_ok']}/{n['speaker_decided']} = {pct(n['speaker_ok'], n['speaker_decided'])}   "
          f"(reviewer undecided on {n['speaker_undecided']} of {n['spoken']} spoken beats)")
    print(f"  confidence >= 0.7: {hi_conf['ok']}/{hi_conf['n']} = {pct(hi_conf['ok'], hi_conf['n'])}")
    print(f"  confidence <  0.7: {low_conf['ok']}/{low_conf['n']} = {pct(low_conf['ok'], low_conf['n'])}")
    print(f"missed text: director reported {n['director_missed_text_items']}, reviewer reported {missed}; reviewer false beats {false_b}")
    print(f"disagreements: {len(disagreements)}")
    (run / "score.json").write_text(json.dumps({"counts": dict(n), "disagreements": disagreements}, indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    cmd, run, pids = sys.argv[1], Path(sys.argv[2]), sys.argv[3:]
    {"prep": prep, "score": score}[cmd](run, pids)
