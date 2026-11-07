---
name: manga-cast
description: Build the cast bible for one webtoon episode from contact sheets and draft text. Produces cast.json with stable character ids that every later stage must use. Use before directing any packet of the same episode.
---

# manga-cast

Goal: one consistent list of the recurring characters in an episode, so parallel Director agents all use the same ids.

## Inputs (paths given by the caller)
- Contact sheets `cast/sheet_NN.png`: the whole episode, blank gutters removed, tiled left to right then onward by sheet, each tile labelled with its strip `y` range.
- `draft_beats.json`: OCR text of every beat with its strip position (`box[1]` is y). Use it to find names and who is addressed.
- `cast/index.json`: which tile labels belong to which sheet.

## Method
1. Look at every sheet. List each distinct character that speaks or is clearly important (appears in 2+ tiles or is named).
2. Identify by stable visual traits (hair colour/style, eye colour, outfit, build, age), not by pose. Note chibi/icon versions of faces: small cartoon heads used next to bubbles represent the same character.
3. Find names in the text (people address each other by name, system windows show names). Only record a name the text actually establishes; otherwise describe the role ("older man with round glasses").
4. Merge duplicates: the same person in different outfits is one character; give a short note.
5. Add the special speakers below if the episode uses them.

## Extend mode (a later chapter of a manga that already has a cast)
If the caller gives you an existing cast file: read it first and keep every existing character exactly as it is (same id, name, aliases, gender, age_band, voice_hint, visual). Only add characters that are new in this chapter, with the next free ids (never reuse or renumber), and fill in a `name` that was null if this chapter's text now establishes it. Write the FULL combined cast. A person who changed outfit is still the same character: match by face, hair and role, not clothing.

## Output: write `cast/cast.json`

```json
{
  "episode": "<folder name>",
  "characters": [
    {
      "id": "c1",
      "name": "name if established in text, else null",
      "aliases": ["other names or titles used for them"],
      "visual": "one sentence an agent can match against a crop",
      "icon": "how their chibi/icon looks if used, else null",
      "role": "protagonist | sibling | announcer | ...",
      "gender": "male | female | unknown",
      "age_band": "child | teen | young_adult | adult | elder",
      "voice_hint": "3-6 words, e.g. 'tired, dry young man'",
      "seen_at_y": [list of 2-4 strip y values where they are clearly visible]
    }
  ],
  "special_speakers": {
    "narrator": "boxed narration that is not on-screen speech",
    "system": "game-style window text (blue hexagon boxes, status screens)",
    "announcer": "in-world broadcast / TV / public announcement, if present"
  },
  "uncertain": ["anything you could not resolve, e.g. two characters that might be the same person"]
}
```

## Rules
- Ids are `c1, c2, ...`, ordered by first appearance. Never reuse or renumber later.
- Do not invent characters seen only as background crowd.
- If unsure whether two figures are the same person, list them separately and put the question under `uncertain`.
- Validate: `python spike/direct/validate.py cast <run_dir>/cast/cast.json`.
