# 06 - Director spike (Track C) - results so far

Goal: can Claude turn the machine-detected beats into a performance script (type, speaker, emotion, corrected text) well enough to read aloud? Method follows the design: cast pass, one Director agent per packet, an independent Reviewer per packet, schema validation, then a human accuracy check.

Everything below is for one chapter, 10 of 57 packets (50 beats). Chapter text stays local and is not quoted here.

## What was built (all in the repo)

| Piece | Where |
|---|---|
| Packet maker: annotated crop + beat JSON, cut between beats, 250 px padding, 57 packets for the chapter | `spike/direct/make_packets.py` |
| Cast contact sheets (gutters collapsed, labelled with strip y) | `spike/direct/make_cast_sheets.py` |
| Rubrics as versioned skills: `manga-cast`, `manga-direct`, `manga-review` | `.claude/skills/*/SKILL.md` |
| Output validators (cast / director / review) | `spike/direct/validate.py` |
| Reviewer-input prep (strips the Director's reasoning) + agreement scoring | `spike/direct/score.py` |
| Human verification page (crop + predicted speaker, correctable, exports `labels.json`) | `spike/direct/make_verify_page.py` |

## Cast pass
One agent read 7 contact sheets plus the OCR text and produced `cast.json`: 4 characters (protagonist, a parent figure, a younger sibling, a high-ranking woman) and three special speakers (narrator, system, announcer). It validated first try. Two roles ("father", "sibling") are inferences the text does not state; the agent listed them under `uncertain`.

## Director run
- 10 Director agents in parallel, one per packet. All 10 outputs passed the validator.
- 50 beats: 17 system, 11 speech, 9 narration, 5 credit, 4 skip, 1 thought, 1 reaction, 1 note, 1 sfx. 8 beats below 0.7 confidence.
- The Director corrected the OCR text on **22 of 50 beats**; **15 of those were word-level** changes (not just spacing or case). So OCR text cannot be voiced without this step.
- The Director found things my first rubric missed, now in the skill: chibi icons attached to bubbles mark the speaker; translator notes need their own type; unboxed text (mostly Korean SFX) exists around the boxes.

## Reviewer run and agreement

| Measure | Result |
|---|---|
| Type agreement | 49/50 (98%) |
| Text agreement | 48/50 (96%) |
| Speaker agreement | 39/39 (100%), reviewer undecided on 0 |
| Speaker agreement on beats the Director rated below 0.7 | 6/6 |
| Missed text reported | Director 10, Reviewer 3, false beats 1 |

The 3 disagreements: two on partly hidden system-window text (the Director reconstructed words it could not fully see), one on thought vs narration.

### Why this is NOT an accuracy number
- Director and Reviewer are the same model reading the same image, so shared blind spots agree with each other.
- The Reviewer never answered "unknown" on any speaker, including two beats (p22 b074 and b075) where the Director itself said the speakers might be swapped. A reviewer that agrees on every coin-flip is probably anchored by the Director's answer despite the image-first instruction.
- So the honest reading is: **no gross disagreement found**, accuracy still unmeasured. The human labels are the real test.

## Findings that change the design
1. **Crops must show what is below a bubble.** Tails point down at the speaker. My first verification crops cut the speaker off; a human could not have judged them either. Packet padding is symmetric today; the verify page now shows 220 px above and 520 px below. Packet padding for the Director should be reviewed the same way.
2. **Cost is dominated by fixed overhead.** Each agent used roughly 56,000 to 63,000 tokens for 2 to 10 beats (image, skill file, system prompt), regardless of beat count. 20 agents for 50 beats; the whole chapter at 57 packets would be about 3.3 million tokens for Directors alone and about double with blanket review. This is too heavy. Fixes to try: batch 4 to 6 packets per Director agent; review only beats under 0.8 confidence, plus a random sample.
3. **Partly hidden system text** (covered by a character): the Director voiced a partial reconstruction at 0.5 confidence. Proposed rule: if text is not fully legible, set it `unreadable` and do not voice it, instead of guessing.
4. **Reviewer should be blind for doubtful beats.** For beats under 0.7, run a reviewer that is not shown the Director's answer at all, then compare.

## Pending: human accuracy check
`samples/ep01/_run/verify/index.html` (41 beats: all spoken beats plus any low-confidence one). Open it in a browser, correct anything wrong, press "Download labels", and save `labels.json` into `samples/ep01/_run/verify/`. That gives the first real speaker/type/text accuracy figure and seeds the regression set for Phase 2.

## Addendum: whole chapter directed, and the cost question answered

After the first listening test (see `07-READER-PROTOTYPE.md`), the remaining 47 packets were directed in 9 batches of consecutive packets (2 to 7 packets per agent). All 57 outputs validate.

- **Batching works.** The 9 batch agents used about 669,000 tokens for 47 packets, roughly **14,000 tokens per packet**, versus roughly 58,000 per packet when each packet had its own agent. That is about 4x cheaper for the same rubric, and consecutive packets also give the Director conversation flow. Use batches of 5 to 7 packets by default.
- **No Reviewer pass was run on the 47 batch packets.** Agreement/accuracy numbers above cover only the first 10 packets. Plan: gated review of beats below 0.8 confidence plus a sample, using a blind reviewer for doubtful speakers.
- **Whole chapter result:** 201 beats: 67 speech, 49 narration, 19 system, 3 thought, 4 reaction, 49 credit, 5 skip, 4 sfx, 1 note. 11 beats are below 0.7 confidence.
- **Rubric change that mattered:** narration is always the `narrator` voice. Before this, Directors split first-person caption boxes between the protagonist and the narrator, which listeners hear as the same text read by two different people.

## Listening result: first real accuracy figure (2026-11-07)

The whole chapter (142 voiced lines) was listened to in the reader with the **Wrong voice?** button available. `spike/direct/correction_report.py` summarises the saved corrections.

- **2 lines corrected**, both moved to the sister (c3): one from Aiden (c2, evidence: bubble tail) and one from the announcer (evidence: content), in packets p19 and p23 of the TV-watching scene. The listener reported the rest as good.
- **Character-voiced lines (speech, thought, reaction): 72 of 74 correct = 97%.** All voiced lines: 140 of 142 = 99%.
- The 33 policy overrides (first-person narration to the protagonist) are rules, not corrections, and are excluded.
- **How far to trust it:** one listener, judged by ear, with the picture on screen and no line-by-line visual audit, so a wrong speaker that sounds plausible may have passed. It is real evidence, not a measurement of every line. The two errors were both missing sister lines; the Director's own evidence and confidence did not predict them (one was above 0.8 confidence), so confidence is not a reliable way to choose lines for review.
- This is much better than the earlier complaint suggested: that feedback was about an earlier bundle where 151 of 171 lines had no Director pass and narration flipped between two voices. Both were fixed.
