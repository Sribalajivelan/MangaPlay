# 00 - Decisions

Locked on 2026-11-07. Change a decision by editing this file and noting why.

| # | Question | Decision | Consequence |
|---|----------|----------|-------------|
| D1 | Language | **English only**, no translation | No JP OCR/TTS, no translation stage. Text can be read by OCR and/or Claude vision. |
| D2 | Content source | **User uploads** | Ingest must accept messy input: a folder of tall slices, a zip/cbz, a single very long image. No scraping, no hosted library. |
| D3 | Audience | **Just the owner** | No accounts, no server, no DB for v1. Personal local tool; copyright exposure stays personal-use only. |
| D4 | Voices | **Free local first, paid higher-quality later** | TTS sits behind a provider interface from day one so a paid provider is a drop-in upgrade, not a rewrite. |
| D5 | Hardware | **CPU only** (i7-1255U, 12 threads, 32 GB RAM, Windows 11) | Detection and TTS must run acceptably on CPU. No large generative models locally. Batch/offline processing is fine; runtime playback uses pre-rendered audio. |
| D6 | Format | **Vertical-scroll webtoons** | Reading unit is a continuous strip, not a page. Panel/reading-order detection (the reference's MAGI stage) is mostly replaced by gutter segmentation + bubble detection. Auto-scroll is the primary mode. |
| D7 | Stack | **TypeScript + React + Vite (PWA) for the app; Python for the pipeline**; Pydantic -> JSON Schema -> TS types | As in `02-DESIGN.md` section 9. |

## Environment facts (checked)

- Python 3.11.9, Node 24.18, `uv` and `pnpm` present. **`ffmpeg` is not installed** - use a bundled binary (e.g. the `imageio-ffmpeg` wheel) rather than a system install.
- 75 GB free disk, 31.6 GB RAM.

## Implications worth stating plainly

1. **Webtoons are easier in one way and harder in another.** Easier: no RTL ordering and no page-spanning panel layouts; order is simply top to bottom. Harder: there are no neat panel borders, art is full colour and text can sit on busy backgrounds, and the stitched strip can be 10,000+ px tall, so everything must be done in overlapping windows.
2. **Local CPU TTS will be good, not "real anime".** See `04-TTS-CANDIDATES.md`. Distinct voices per character and light emotion are realistic; true acted performance is the paid-tier upgrade, which D4 already plans for.
3. **Claude is the vision/OCR backstop.** With English-only and no GPU, a dedicated OCR model may be unnecessary: a bubble detector finds boxes, and Claude reads and attributes text from crops. The spike decides whether a CPU OCR is still worth adding (speed/cost), not whether it is possible.
