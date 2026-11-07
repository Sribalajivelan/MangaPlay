# 03 - Plan: MangaPlay

Companion to `01-ANALYSIS.md` and `02-DESIGN.md`. Each phase ends with something you can run and judge. Phases are ordered to retire the biggest risks first, not to ship features in UI order.

## Phase 0 - Feasibility spike (days, throwaway code allowed)

Goal: find out whether the idea feels good on **this CPU-only machine** before building infrastructure. Decisions are in `00-DECISIONS.md`.

Track A - voices (needs no webtoon, can start now)
- Install Kokoro via ONNX and Piper in a scratch venv; synthesise the same 20 English lines with each.
- Measure real-time factor (1 and 4 threads), first-audio latency, install friction, and count usable distinct voices. Score naturalness 1-5 by ear.
- Decide the baseline provider and write the provider interface around it.

Track B - detection (needs one webtoon episode)
- Stitch the slices, find gutters, render an overlay of segments.
- Run a candidate bubble detector on CPU in overlapping windows; measure time per 1,000 px of strip and recall/precision on ~50 hand-checked bubbles.
- Compare reading text three ways: CPU OCR, Claude from crops, both; record accuracy and cost.

Track C - understanding (needs the same episode)
- Hand-run a Claude pass on 3 segments (crops + boxes + text in, speaker/emotion JSON out). Score speaker accuracy on ~50 bubbles.

Track D - playback prototype
- One throwaway HTML page: a strip, bubble highlight, audio playback, eased auto-scroll keyed to bubble `y`. Judge whether it feels good.

Exit criteria: speaker accuracy at least about 85% after review; detection recall acceptable on the test episode (missed bubbles are fixable in the editor, invented ones are worse); local voice at least ~3x real time on this CPU; a prototype you want to keep using. If voices sound bad, we learn that here and bring the paid upgrade forward.
Deliverable: `docs/05-SPIKE-RESULTS.md` with numbers.

## Phase 1 - Contract and pipeline skeleton

- Pydantic models for script / cast / manifest / overrides; export JSON Schema and TS types.
- Python project (venv, pytest, ruff, mypy) with stage runner: `done` checks, run folders, config snapshot, `metrics.json`, raise-on-failure semantics.
- Tools: ingest, panels, ocr, overlay renderer, validate, package.
- A **golden bundle** committed for tests (small, synthetic or own-content).

Exit: `tools` can take a folder of images to a schema-valid bundle with no LLM and no audio (panels + OCR only), resumably, on Windows.

## Phase 2 - Agentic stages

- Skills: `manga-chapter`, `manga-panels`, `manga-cast`, `manga-direct`, `manga-review`, `manga-package`.
- Subagents: `page-director`, `page-reviewer`; schema-validated output, bounded retry, per-page status.
- Confidence gating and the best-of-N second pass for flagged panels only.
- Evaluation harness: labelled sample from Phase 0 becomes a regression set (speaker accuracy, missed/invented bubbles). Prompt or skill changes must not lower the score.

Exit: one command processes a full chapter to `script.json` with a metrics report; speaker accuracy on the regression set meets the Phase 0 bar.

## Phase 3 - Voice

- TTS provider registry with the chosen baseline provider; content-hash cache.
- Narrator mode, then cast mode (voice casting stored per series), then emotion/delivery.
- Audio normalisation (loudness), Opus encoding, `audio_ms` recorded.

Exit: bundle with audio for every spoken beat; re-run costs nothing for unchanged beats.

## Phase 4 - Reader MVP

- Scaffold app; bundle loader; page viewer; RTL/LTR/vertical.
- Playback engine (audio-as-clock state machine) with unit tests on the timeline maths.
- Cinematic mode first, then continuous scroll, then manual with tap-to-play.
- Controls, speed, captions, reduced motion, keyboard + touch, resume position (localStorage).
- Offline cache via service worker.

Exit: open a bundle in the browser, press play, it reads the chapter hands-free with correct sync, on desktop and a phone.

## Phase 5 - Director's desk (editor) and overrides

- Overlay editing: boxes, order, speaker, text, emotion, per-beat re-synthesis.
- `overrides.json` write and merge-on-rerun; `needs_review` queue.

Exit: fix a wrong speaker in the app, re-run the pipeline, the fix survives.

## Phase 6 - Polish and library

- Performance mode: SFX library, ambience, finer emotion control.
- Library screen, progress tracking, settings, themes.
- Decide whether multi-user hosting is in scope (needs rights decision, API, DB, auth).

## Phase 7 - Optional: anime mode

Only if wanted after everything above: generate short motion clips for key panels using the reference's approach (script -> storyboard -> image-to-video with reviewer selection). Expensive, GPU/API-bound, and a different product tier; kept out of the core plan on purpose.

## Cross-cutting

- **Testing**: schema validation on every bundle; golden-bundle snapshot tests; Playwright smoke test that plays 3 beats and asserts cursor advancement; pipeline regression set from Phase 2.
- **Cost control**: metrics per stage from Phase 1; refuse to run a chapter over a configurable token/character budget without confirmation.
- **Repo layout (proposed)**:
  ```
  MangaReader/
    docs/            # these documents
    schema/          # generated JSON Schema (committed)
    tools/           # Python pipeline tools + tests
    app/             # web reader
    bundles/         # local output (gitignored except golden fixture)
    .claude/         # skills + agents
  ```
- **Dependencies hygiene**: pin model revisions (no unpinned `trust_remote_code`), pin package versions, record them in each run's config snapshot.

## Decisions and what is still open

Answered (see `00-DECISIONS.md`): English only; user uploads; just you; local voices first then paid upgrade; CPU only; vertical-scroll webtoons; stack approved.

Still needed from you:
1. **One webtoon episode for the spike** (a few thousand to ~15,000 px tall, ideally with several recurring characters and a mix of dialogue, thoughts and narration). Put it in `MangaReader\samples\ep01\` as image slices or one long image. It stays local and is gitignored.
2. Install ffmpeg yourself, or let me use the bundled `imageio-ffmpeg` wheel? [default: bundled wheel, nothing system-wide is installed]
3. Is it OK to create a project virtual environment and download model files (Kokoro about 300 MB or about 80 MB quantised, a bubble detector) into `MangaReader\.cache\`? [default: yes]

## Immediate next step

Track A starts now (no sample needed). Track B-D start when the sample episode is in place.
