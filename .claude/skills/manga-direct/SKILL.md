---
name: manga-direct
description: Direct one packet of a webtoon episode - for each draft beat decide its type, speaker, emotion and delivery, correct the text, and produce clean text for speech synthesis. Use for each packet produced by make_packets.py.
---

# manga-direct

You are the Director for ONE packet. You turn machine-detected text boxes into a performance script. The image is the source of truth; the draft text is OCR and can be wrong.

## Inputs (paths given by the caller)
- `packets/pNN.png`: a crop of the episode. Detected boxes are drawn and labelled with beat ids (`b012`). Other text in the crop that has no box is NOT yours unless it is missing text (see below).
- `packets/pNN.json`: for each beat `draft_type`, `detector_class`, `draft_text`, `ocr_text_before_spacing_repair`, `needs_review`, `box_in_image`; plus `previous_context` (the last beats of the previous packet, text only).
- `cast/cast.json`: the only allowed speaker ids.

## Per beat, decide
1. **type** (one of):
   - `speech`: spoken aloud in a round/jagged speech bubble.
   - `thought`: inner monologue shown as a bubble (cloud-shaped, italic, or clearly unspoken). Its speaker IS the character who thinks it (a cast id). A boxed caption is `narration`, not `thought`.
   - `narration`: a caption box that narrates the story. **Whose voice is it?** If the caption is the protagonist's own first-person narration or inner monologue ("I", "my", "me", their own reflections and recollections), the speaker is THAT CHARACTER's cast id, so that person has one voice for the whole episode. If it is an outside narrator (third person, "he/she", a quoted saying being retold, a recap of events), the speaker is `narrator`. Once an episode switches into a character's first-person narration, stay with that character until the text clearly returns to an outside narrator; do not alternate line by line.
   - `system`: game-style window / status screen / blue hexagon announcement box that is part of the story world.
   - `reaction`: punctuation-only or one-sound bubble (`!?`, `...`, `Huh?`).
   - `sfx`: sound-effect lettering. Never spoken.
   - `credit`: staff list, links, social handles, watermark.
   - `note`: translator or editor note placed over the page (often tiny text starting with an abbreviation such as `TL/N`, `PR/N`, `Note`). Never spoken.
   - `skip`: a false detection, no readable text.
2. **text**: the corrected text exactly as printed (keep capitals). Fix OCR errors by reading the image: wrong letters, missing or extra words, and missing spaces (a spacing repair was already attempted; verify it). Keep punctuation.
3. **tts_text**: what a voice should say. Sentence case, normal punctuation, no stage directions, numbers and symbols written as words if they would be misread. Keep the speaker's tone with punctuation (`!`, `?!`, `...`). Empty for `sfx`, `credit`, `note`, `skip`. For `reaction`, a short natural vocalisation (`Huh?!`) or empty if silence is the better read.
4. **speaker**: a cast id from `cast.json`, or `narrator`, `system`, `announcer`, `none` (for non-speech types), or `unknown`.
5. **speaker_basis**: which evidence decided it, best first:
   - `tail`: the bubble's pointer/tail points at a character.
   - `icon`: a chibi/face icon attached to the bubble.
   - `position`: the bubble sits closest to / over a character who is plausibly speaking, and the panel shows that character reacting or facing the other.
   - `dialogue_flow`: alternation in a two-person exchange.
   - `content`: the text itself (names, "I", who is being addressed).
   - `none`: not a spoken type.
6. **emotion**: one of `neutral, happy, excited, sad, angry, afraid, surprised, embarrassed, resolute, sarcastic, tired, tender, menacing`.
7. **delivery**: 2-6 words for the voice (`flat, deadpan`, `shouting, panicked`, `quiet, hesitant`). Base it on face, lettering size/weight (large bold = louder), bubble shape (jagged = shouting, dotted = whisper).
8. **confidence**: 0.0-1.0 for the speaker and type together. Use `unknown` plus a low confidence rather than guessing. Anything below 0.7 will be sent to review.
9. **text_changed**: true if `text` differs from `draft_text` beyond case.

## Missing text
List any readable story text in the crop that has no box (including tiny notes, text outside bubbles) under `missed_text` with a rough position in the image and what it says. Do not add it as a beat.

## Order
Keep beats in the given order (top to bottom). If two boxes are read side by side or the order of speaking differs from the order on the page, add `speak_order` (an integer starting at 1) on those beats only.

## Output: write `directed/pNN.json`
```json
{
  "packet_id": "p05",
  "beats": [
    {
      "id": "b012", "type": "speech", "text": "...", "tts_text": "...",
      "speaker": "c1", "speaker_basis": "tail",
      "emotion": "neutral", "delivery": "flat, deadpan",
      "confidence": 0.9, "text_changed": false, "notes": "optional, one line"
    }
  ],
  "missed_text": [{"near": "b012", "where": "just below", "text": "..."}]
}
```
Every beat id from the packet must appear exactly once. Validate with `python spike/direct/validate.py director <packet.json> <directed.json> <cast.json>`.

## Voice consistency (the listener hears a different voice per speaker id)
- The same character must always get the same id, and the same narrating voice must continue until the text clearly changes. A wrong or flip-flopping speaker is the most noticeable error in the whole product, so when two readings are possible prefer the reading that continues the current conversation (who spoke before, who is being answered), and lower `confidence` when unsure.
- System/status windows: speaker `system`. In-world broadcast or public announcements: `announcer`.

## Rules
- Never output a speaker id that is not in `cast.json`.
- Do not describe the story or add commentary outside the JSON file.
- Do not quote more story text than the beats and `missed_text` need.
- Profanity stays as printed.
