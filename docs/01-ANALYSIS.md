# 01 - Reference Analysis: Manga2Animate

Source analysed: `..\Manga2Animate` (103 commits, paper "Manga2Animate: An Agentic Framework for Faithful Manga Animation with Script and Storyboard Planning", NYCU, arXiv 2610.26851).
Read in full: `README.md`, `.env.example`, `src/run_all.py`, `magi.py`, `croppanels.py`, `create_script.py`, `create_character_description.py`, `utils.py`, parts of `create_video.py`; prompts for script creation, character description, clip/character review, storyboard, video.
Skimmed only (not relevant to us): `mangaeval/` (VBench, AMT, GRiT, aesthetic scorers - vendored third-party eval code), `opensource_backends/` (FLUX.2 and MiniMax/AniSora GPU serving).

## 1. What it is

A **batch research pipeline**: 6 manga panels + a character reference sheet in, a short generated **video** out. It is not a reader and has no UI. Everything is Python scripts driven by `argparse`, state lives in folders on disk, and the only "agents" are Gemini calls with different prompts.

Core idea: do not feed raw manga to a video model. Mimic real animation production instead: **script -> storyboard -> video**, with a *creator* agent and a *reviewer* agent at each step.

## 2. Pipeline, stage by stage

| # | Stage | Tool / model | Output |
|---|-------|--------------|--------|
| 1a | Panel detection + reading order | MAGI (`ragavsachdeva/magi`, HF, `trust_remote_code`) on greyscale pages, threshold 0.2 | `manga_panels/panelN.png` |
| 1b | Transcript (OCR + speaker/text association) | MAGI `predict_ocr` + `generate_transcript_for_single_image` | `character/transcript.txt` |
| 2 | Character descriptions | Gemini vision on the reference sheet(s) | `character_description.json` |
| 3 | Script creation x3 candidates | Gemini (thinking=HIGH), all panels + transcript + descriptions | `iterK/scripts/script_*.json` |
| 4 | Script review | Character Reviewer (4 criteria) + per-clip Clip Reviewer (6 criteria), winner-per-criterion, **best character block and best clip chosen independently then reassembled** | `bestScript.json`, `feedback.json` |
| 5 | Storyboard x3 | Gemini image model (or FLUX.2 per panel) | 3x2 storyboard grid |
| 6 | Storyboard review | Pairwise comparison, 13 criteria (5 pass/fail) | `bestStoryboard.png`, feedback |
| 7 | Loop | Round 1 feeds best script + both feedbacks back into script creation (`NUM_ITERATIONS=2`) | |
| 8 | Video | Seedance / MiniMax / Wan / AniSora, 2 candidates, Gemini video reviewer picks | `best_video.mp4` |

Orchestration is `run_all.py`: ordered `run_stage(name, done_fn, action)` calls.

## 3. Engineering patterns worth copying

1. **Idempotent, resumable stages.** Every stage has a `done_fn` that checks its output files exist, are non-empty and parse as JSON. `--auto-resume` skips finished stages and fails loudly if a stage "finished" but outputs are missing. Directly applicable: a 200-page chapter must be restartable without paying twice.
2. **Run folder per timestamp**, config snapshot written next to results, `metrics.json` with per-stage wall time and API call count (written in a `finally`). Cost and latency visibility from day one.
3. **Creator and reviewer are different calls with different rubrics.** Nothing grades its own output.
4. **Rubric-based comparison with forced single winners** and explicit tie-break order, rather than free-form "is this good".
5. **Source-of-truth ordering baked into prompts**: "the manga image beats the transcript beats the character text; override silently." OCR is wrong often enough that this matters.
6. **Dialogue is scoped to the panel it physically appears in** (prompt rule 5/6). Speaker assignment is an explicit review criterion - the authors treat it as a hard problem. It is *the* hard problem for us too.
7. **Duration heuristic** (`calculate_optimal_duration`): `1s + (panel_area / total_area) * 10 + words / 10`, clamped. A reasonable starting point for how long a panel should stay on screen.
8. **Provider backends behind a registry** (`Backend` subclasses, `get_backend`). Swap TTS providers the same way.

## 4. Weaknesses and traps (do not inherit these)

1. **Dialogue is embedded in prose, then stripped by regex.** `utils.py` carries ~100 lines of comments on four successive regex bugs (possessive apostrophes, "says:" debris, screenplay-style speaker chains, paraphrased "sound effect" wording). The authors' later flux2 prompts added a structured `dialogue` array - the right fix. **Our schema keeps dialogue/text as structured fields from the start; never regex it out of narration.**
2. **`re.search(r"\{.*\}")` to extract JSON** from model output, no schema validation. Use schema-validated output with a bounded retry.
3. **`with_retry` returns `default` (None) after 20 failures** instead of raising; callers cannot distinguish failure from empty. We raise, and record per-item status.
4. **Module-level config via environment variables set before import** (`os.environ["TARGET"]` then `import`). Fragile. Pass an explicit config object.
5. **Fixed to exactly 6 panels** (`NUM_CLIPS=6`). We need whole chapters (hundreds of panels), so the unit of work must be a page, with bounded context per call and parallel fan-out.
6. **MAGI loaded with `trust_remote_code=True` and no pinned revision.** Executes remote code from a model repo. Pin a commit hash, or vendor/replace.
7. **Hard GPU assumptions** (FLUX.2 ~105 GB weights, 97 GB card; bash + conda scripts). Irrelevant to us, and the tooling is not Windows-friendly. Our pipeline must run on a normal Windows dev machine.
8. **Panel detection and reading order are only as good as MAGI**; there is no human correction path. For a reader this is unacceptable - users will hit wrong order on any non-standard layout.

## 5. Licence and reuse

The repo has **no LICENSE file**, so default copyright applies (all rights reserved). Treat it as a **design reference only**: reuse the ideas (they are in a public paper), but write our own code and prompts. Do not copy source or prompt text verbatim. MAGI itself is a separate project with its own licence - check it before depending on it. The evaluation data uses Manga109, which is research-licensed.

## 6. Mapping to MangaPlay

| Manga2Animate | MangaPlay | Verdict |
|---|---|---|
| Panel crop + reading order (MAGI) | Same, but keep **bbox on the original page** instead of cropping, so the reader can pan/zoom over the real page | **Adopt**, change output |
| OCR transcript | Per-bubble text with bbox | **Adopt**, add bbox + type |
| Character description from reference sheet | Cast bible built from the chapter itself (no reference sheet exists); optional upload | **Adapt** |
| Script creator (panel -> clip description) | "Director": per-panel scene summary, bubble type, **speaker, emotion, delivery**, camera hint | **Adapt** - output is a performance script, not a video prompt |
| Script reviewer (best-of-N, rubric) | Reviewer agent re-checks speaker/order/missed bubbles; best-of-N only for low-confidence panels | **Adapt** (cheaper) |
| Storyboard generation + review | - | **Drop** |
| Video generation + review | - (optional far-future "anime mode") | **Drop for v1** |
| Duration heuristic | Starting point for visual dwell time; audio length dominates | **Adopt** |
| Resume / run folders / metrics | Same | **Adopt** |
| `mangaeval/`, FLUX.2, AniSora serving | - | **Ignore** |
| (nothing) | Reader app, TTS, playback engine, in-app correction editor | **New** - this is most of our product |

**Takeaway:** Manga2Animate is roughly 25% of what we need (the understanding half: panels, text, characters, per-panel structured script). The expensive generative half is out of scope. The other 75% - voice, playback engine, reader UX, correction tooling - is new.
