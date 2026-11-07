# 05 - Detection spike (Track B) - results

Sample: `Copying Skills With Affinity! - Ch.1` (28 PNG slices, 690 px wide, 145,810 px tall in total, slice heights 2,052-10,000 px). Pages are user-supplied and stay local; nothing from the chapter is copied into these docs.

## Done

- **Virtual strip loader** (`spike/detect/strip.py`): natural-sorts slices, records offsets, composes any `[y0, y1)` window on demand. Fails loudly on mixed widths.
- **Gutter segmentation** (`segment.py`, `segment_only.py`): rows whose colour variation is tiny are flat; runs of at least 60 px split the strip. Result on this chapter: **85 gutters, 81 segments, 7.5 s**, segment height min/median/max 129 / 1,270 / 7,097 px.
- **Overlay renderer** (`overlay.py`) to check results by eye.
- **Checkpoint audit** (`audit_pt.py`): static scan of the detector's `.pt` pickle without executing it.

## What the overlays show

1. Gutter splitting is sound: flat colour bands between scenes are found and the segments between them are scene-sized.
2. **Some bubbles sit in the white gutters themselves** (dialogue floated over a white band, before the next art starts). A gutter is therefore not "dead space": bubble detection must run on the whole strip, not only inside segments.
3. **Not every text container is a round speech bubble.** This chapter also has hexagonal blue "system window" boxes with a different font, and bold text directly on white. A detector trained only on speech bubbles may miss these, so the design needs a second text source (OCR-style text-region detection) or a detector with narration/system classes.
4. Untranslated Korean sound effects remain in the art next to English dialogue. English-only TTS should ignore them (the reviewer step marks them `sfx`, not spoken).

## Results (decision C: safe ONNX text detection first, speech-bubble detector as comparison)

Chapter: 145,810 px of strip. All numbers measured on this CPU. Scripts in `spike/detect/`.

| Source | Runtime | Output |
|---|---|---|
| ONNX OCR (RapidOCR, PP-OCRv4, models bundled as `.onnx`) | 418 s (2.9 s per 1,000 px) | 481 English-like text lines -> **197 text blocks** (Korean SFX filtered out) |
| Bubble detector (YOLOv8m `.pt`, classes `text_bubble` / `text_free`) | 121 s (0.83 s per 1,000 px) | 126 detections (112 bubble, 14 free text) |
| Gutter segmentation | 7.5 s | 85 gutters, 81 segments |

The `.pt` detector was run after you chose option C. It needs a one-time pickle load, so it stays a comparison and is not a dependency of the safe path (static audit of the file was clean, see below).

### What each source is good and bad at

- **OCR blocks** are tight, accurate text boxes and catch everything with letters: round bubbles, hexagonal system windows, narration on white, bold captions, game-UI text. Weak at: punctuation-only bubbles (dropped by the letters filter) and **word spacing in condensed fonts**.
- **Detector** gives the bubble outline (good highlight region) and a bubble-vs-free-text hint, at 3.4x the OCR speed. Covers **142 of 197** OCR blocks (72%). It misses narration/system/caption text and the scanlation credits (a good miss). Its 4 text-less detections were all punctuation-only "reaction" bubbles that OCR dropped.
- Conclusion: **fuse them.** OCR supplies text and position, the detector supplies bubble shape, type and the reactions OCR can't see.

### Fusion (`fuse.py`) -> 201 draft beats

120 speech, 61 caption, 16 credit (never spoken), 4 reaction. About 1,140 words, roughly **7.3 minutes of speech**, so about 3.3 minutes of TTS rendering at the measured 2.2x. 74 beats are marked `needs_review`.

### The main problem found: OCR spacing

Condensed comic fonts make the recogniser drop spaces ("ALLIHADTODOWAS"), and its confidence stays at 0.95 to 0.99 on these errors, so **confidence cannot be used to find them**. Repair with a word segmenter (`wordninja`) on tokens of 7 or more letters fixed 64 beats. Two guards were needed, both found by checking output rather than assumed:
- Invented names (for example a 10-letter surname) were being split into two words. Names are now protected when they recur in clean, normally spaced blocks.
- A first version protected any repeated token, which also protected a quote shown twice in the chapter. Fixed by requiring the repeats to be in clean blocks.
- Bug found and fixed: a non-raw replacement string injected control characters into the text.
Spacing repairs are marked on the beat (`spacing_repaired`, original kept in `ocr_text`) so the Claude Director step verifies them against the image.

### Other findings
- Credit and translator-note text appears at the start and end of the strip (16 blocks), all caught by a keyword rule, with no dialogue lost in the sample checked. Keep the rule, but Director must confirm.
- Detector class confusion expected: a thought bubble looks like `text_bubble`; the Director step decides speech vs thought.

### Not measured (be honest about it)
No labelled ground truth exists, so there are no recall/precision figures. Quality was judged by eye on 8 overlay windows plus targeted checks of the empty detections. A real measurement needs about 50 hand-labelled bubbles. Speaker attribution and emotion are Track C and are not started.

### Static audit of the `.pt` (kept for the record)
29 imports, all PyTorch layers and Ultralytics architecture classes; no `os`, `subprocess`, `eval`, network or `importlib`. Only flag: `__builtin__.set`, the Python 2 name for `set`. Lowers risk, does not prove safety.
