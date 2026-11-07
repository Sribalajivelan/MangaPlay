---
name: manga-review
description: Independently audit a Director's output for one webtoon packet - judge each beat's type, speaker and text against the image, and report missed text. Use after manga-direct, with a different agent than the one that directed.
---

# manga-review

You are the Reviewer. You did not direct this packet and you must not trust it. Judge each beat from the image first, then compare with the Director's answer.

## Inputs (paths given by the caller)
- `packets/pNN.png` and `packets/pNN.json` (same as the Director saw).
- `cast/cast.json`.
- `reviewer_input/pNN.json`: the Director's answers **with the reasoning removed** (only `id, type, text, tts_text, speaker, emotion`). Do not look for the Director's own file.

## Procedure
1. For each beat, BEFORE reading the Director's answer, decide from the image alone: type, speaker, and the exact printed text. Use the evidence order in the manga-direct skill (tail, icon, position, dialogue flow, content).
2. Then compare with the Director's answer and record a verdict per field:
   - `type_ok`, `speaker_ok`, `text_ok` (true/false). `text_ok` means the words match the printed text; ignore capitalisation. `tts_text` must also be faithful to the text and read naturally.
   - If false, give `suggested_type` / `suggested_speaker` / `suggested_text`.
   - `emotion_ok` only if clearly wrong (otherwise true).
3. If you cannot decide a speaker from the image, say `reviewer_speaker: "unknown"` and set `speaker_ok` to null. Do not force agreement and do not force disagreement.
4. List any story text visible in the crop that no beat covers (`missed_text`), and any beat that is not really text (`false_beats`).

## Output: write `reviewed/pNN.json`
```json
{
  "packet_id": "p05",
  "beats": [
    {
      "id": "b012",
      "reviewer_type": "speech", "reviewer_speaker": "c1", "reviewer_text": "...",
      "type_ok": true, "speaker_ok": true, "text_ok": true, "emotion_ok": true,
      "suggested_type": null, "suggested_speaker": null, "suggested_text": null,
      "note": "optional, one line"
    }
  ],
  "missed_text": [], "false_beats": []
}
```
Validate with `python spike/direct/validate.py review <packet.json> <reviewed.json> <cast.json>`.

## Rules
- Be strict about speakers and spoken-vs-not-spoken types: those decide what the listener hears.
- Be lenient about wording of `delivery` and about emotion unless clearly wrong.
- Do not rewrite the whole script. Report differences only.
