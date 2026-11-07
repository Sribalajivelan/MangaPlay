"""What did the listener have to correct? First real accuracy figure for the Director step.

Run: .venv\\Scripts\\python.exe -I spike\\direct\\correction_report.py <bundle_dir> <run_dir>

Reads bundle/overrides.json (entries with by == "user") and the Director output. Policy overrides
(by == "policy") are rules, not corrections, and are excluded from every accuracy figure.
"""
from __future__ import annotations

import glob
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

SPOKEN_KINDS = {"speech", "thought", "reaction"}  # where a *character* is chosen; narration/system are rule-driven


def pct(a: int, b: int) -> str:
    return f"{a}/{b} = {100 * a / b:.0f}%" if b else "n/a"


def main(bundle: Path, run: Path) -> None:
    script = json.loads((bundle / "script.json").read_text(encoding="utf-8"))
    ov_path = bundle / "overrides.json"
    ov = json.loads(ov_path.read_text(encoding="utf-8")).get("beats", {}) if ov_path.exists() else {}
    user = {k: v for k, v in ov.items() if v.get("by") == "user"}

    directed: dict[str, dict] = {}
    packet_of: dict[str, str] = {}
    for f in sorted(glob.glob(str(run / "directed" / "p*.json"))):
        pid = Path(f).stem
        for b in json.loads(Path(f).read_text(encoding="utf-8"))["beats"]:
            directed[b["id"]] = b
            packet_of[b["id"]] = pid

    beats = {b["id"]: b for b in script["beats"]}
    voiced = [b for b in script["beats"] if b["tts_text"] or (b.get("override") or {}).get("muted")]
    chars = [b for b in voiced if b["type"] in SPOKEN_KINDS]

    print(f"voiced lines: {len(voiced)}   user corrections: {len(user)}   policy overrides: {sum(1 for v in ov.values() if v.get('by') == 'policy')}")
    if not user:
        print("No corrections yet. Listen, press 'Wrong voice?' on each wrong line, then run this again.")
        return

    muted = {k for k, v in user.items() if v.get("muted")}
    changed = {k: v for k, v in user.items() if "speaker" in v and v["speaker"] != v.get("was")}
    print(f"  speaker changed: {len(changed)}   muted (should not be read): {len(muted)}")
    print()
    print(f"Lines needing a speaker fix, of all voiced lines:           {pct(len(changed), len(voiced))}")
    ch_changed = [k for k in changed if beats.get(k, {}).get("type") in SPOKEN_KINDS]
    print(f"Lines needing a speaker fix, of character-voiced lines:     {pct(len(ch_changed), len(chars))}   (speech/thought/reaction only)")

    print("\nWhat was confused with what (Director said -> you said):")
    for (a, b), n in Counter((v.get("was"), v["speaker"]) for v in changed.values()).most_common():
        print(f"  {a:>9} -> {b:<9} {n}")

    print("\nDid the Director's own evidence predict errors? (character-voiced lines)")
    by_basis: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    by_conf: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for b in chars:
        d = directed.get(b["id"])
        if not d:
            continue
        bad = b["id"] in changed
        basis = d.get("speaker_basis", "?")
        by_basis[basis][0] += bad
        by_basis[basis][1] += 1
        bucket = "conf >= 0.8" if d["confidence"] >= 0.8 else ("0.7-0.8" if d["confidence"] >= 0.7 else "conf < 0.7")
        by_conf[bucket][0] += bad
        by_conf[bucket][1] += 1
    for k, (bad, n) in sorted(by_basis.items(), key=lambda t: -t[1][1]):
        print(f"  basis {k:<14} corrected {pct(bad, n)}")
    for k in ("conf >= 0.8", "0.7-0.8", "conf < 0.7"):
        if k in by_conf:
            bad, n = by_conf[k]
            print(f"  {k:<15} corrected {pct(bad, n)}")

    print("\nWhere in the chapter (by packet) - to see whether errors cluster late:")
    per_packet = Counter(packet_of.get(k, "?") for k in changed)
    print("  " + ", ".join(f"{p}:{n}" for p, n in sorted(per_packet.items())))

    print("\nLines you changed:")
    for k, v in sorted(changed.items()):
        b = beats[k]
        d = directed.get(k, {})
        print(f"  {k} {packet_of.get(k,'?')} {v.get('was')}->{v['speaker']}  basis={d.get('speaker_basis','?')} conf={d.get('confidence','?')}  {b['tts_text'][:50]!r}")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
