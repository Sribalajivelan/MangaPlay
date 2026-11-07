# 08 - Library, uploads and processing queue

Goal (from the owner): a home page that manages the manga list; create a manga; add chapters by choosing an images folder; the chapter goes into a queue and is processed automatically; when finished it is ready to read; it can be deleted; everything (library, queue, reading position) survives a restart, using SQLite.

## Decisions

| # | Decision | Why |
|---|---|---|
| L1 | **Backend: FastAPI (Python) + SQLite (stdlib `sqlite3`, WAL)** | The pipeline is Python; one process owns the database, the queue and the files. This is the "API/DB later" row of design section 9, now needed. |
| L2 | **Frontend: the existing React app + react-router** (Home, Manga, Reader). In production the backend serves the built app; in development Vite proxies `/api` and `/bundle` to the backend. | One URL, one process to start. |
| L3 | **LLM stages run unattended via headless Claude Code** (`claude -p`), tools limited to `Read` and `Write`, output validated by the server and retried once. | Verified on 2026-11-07: one packet in 27 s, valid, identical types and speakers to the in-session run. Uses the owner's existing Claude Code login; no API key to store. The JSON result reports cost, which is recorded per chapter. Alternative if ever wanted: the Anthropic API directly. |
| L4 | **The chapter row is the queue entry.** `status` goes `uploading -> queued -> processing -> ready` (or `failed` / `cancelled`). One chapter processes at a time. On startup `processing` becomes `queued` and resumes from the first incomplete stage (stages are idempotent with output checks, as in the reference project). | Restart-safe with no extra table. |
| L5 | **Cast and voices belong to the manga, not the chapter.** First chapter builds `cast.json`; later chapters extend it with stable ids. Voices (`voices.json`) are assigned per manga from a pool by gender and age band, so a character sounds the same in every chapter. | The owner's requirement: same person, same voice. |
| L6 | **Uploads are one image per request** (`PUT /api/chapters/{id}/pages/{n}`, raw bytes). Sniffed by file signature, size-capped, stored under server-chosen names. No multipart dependency, per-file progress, robust to large folders. | Safe and simple. |
| L7 | **Local only.** Binds 127.0.0.1; Host and Origin checks on every request; JSON/content-type checks on writes; ids are integers; all paths built from ids under `library/`. | Personal tool (D3), but the process can spawn commands and delete files, so it is not left open. |

## Storage layout (`library/`, gitignored)
```
library/library.db
library/manga/<manga_id>/cast.json, voices.json
library/manga/<manga_id>/chapters/<chapter_id>/
    source/001.<ext> ...   uploaded originals under server-chosen names
    run/                   pipeline working files (detect, ocr, packets, directed ...)
    bundle/                script.json, strip/, audio/, audio_x/, overrides.json  (what the reader loads)
```

## Schema (user_version 1)
`manga(id, title, created_at, updated_at)` ; `chapter(id, manga_id -> manga ON DELETE CASCADE, number, title, status, stage, progress, detail, error, page_count, cost_usd, queued_at, created_at, updated_at, ready_at)` ; `stage_run(id, chapter_id -> chapter CASCADE, stage, status, started_at, seconds, cost_usd, note)` ; `reading_state(chapter_id PK -> chapter CASCADE, beat_id, y, rate, pace, expressive, updated_at)` ; `app_state(key, value)` (last opened chapter).

## Processing stages (per chapter)
1. `ingest` validate images, normalise to one width, count pages
2. `detect` gutters + speech bubbles (YOLO checkpoint; vetted, see 05)
3. `ocr` text lines (ONNX)
4. `fuse` draft beats
5. `packets` Director packets and cast sheets
6. `cast` (LLM) build or extend the manga cast
7. `direct` (LLM) batches of 6 packets, 3 at a time, validate, retry once
8. `voices` assign voices for any new cast members
9. `package` assemble bundle + render audio (plain and expressive)
Each stage records seconds and cost. Cancelling kills the running subprocess tree.

## API (all JSON, `/api`)
`GET/POST /manga` - `GET/PATCH/DELETE /manga/{id}` - `POST /manga/{id}/chapters` - `PUT /chapters/{id}/pages/{n}` - `POST /chapters/{id}/finalize` - `GET/DELETE /chapters/{id}` - `POST /chapters/{id}/cancel|retry` - `GET/PUT /chapters/{id}/reading-state` - `POST /chapters/{id}/override` (the Wrong voice button) - `GET /bundle/{chapter_id}/{path}` (reader files).

## Pages
- **Home**: manga cards (cover = first page crop, chapter counts, ready/processing), "Continue reading", New manga, queue indicator.
- **Manga**: chapter list with status badge, stage and progress while processing, Read, Delete, Retry/Cancel; **Add chapter** (title, number, choose the images folder, upload progress).
- **Reader**: as now, plus resume position and saving state (position, speed, scroll pace, voice style).

## Cost to know about
Directing a chapter uses real model usage: about 14,000 tokens per packet measured, so roughly 0.7M tokens for a 57-packet chapter; the headless run reports `total_cost_usd` (about $0.17 at list price for one 10-beat packet). The chapter card shows the running cost. Batch size and concurrency are settings.

## Build order
M1 backend + database + library UI + delete + reading-state persistence, with the existing chapter imported as the first ready chapter (its Director work is not redone). M2 uploads + queue + stages + headless agents. M3 polish: cancel/retry UX, per-manga voice editing, progress detail.

## Status (built 2026-11-07)

**Run it:** `.\start.ps1` (builds the web app once, then starts everything) and open http://127.0.0.1:8000. For frontend work: `uvicorn` on :8000 plus `pnpm dev` in `app/` on :5173 (Vite proxies `/api` and `/bundle`). The finished sample chapter was imported as the first manga, so it is already in the library (`python -m server.cli import-chapter ...`).

**Verified by running it**
- `pytest server/tests`: 52 tests. API (validation, uploads incl. non-image/oversize/gaps, delete cascades and files, cancel/retry, reading state, security: foreign Origin and Host refused, path traversal refused, media types), voice assignment (distinct, gendered, age-shaped, existing never changed, pool exhaustion), the queue state machine (success, failure then resume, progress bounds, cancel mid-run, delete mid-run, FIFO, restart recovery), and the model steps against a fake `claude` (cast first/extend/rejects dropped characters, direct batches, retries only what is missing, rejects invalid output, gives up clearly).
- **Real end-to-end job** (`server/tests/e2e_real_job.py`): 4 pages uploaded through the API, every stage ran with real OCR, real Claude agents and real audio, bundle served, delete left nothing behind. 215 s, about $0.41.
- **Real restart test** (`server/tests/e2e_restart.py`): server killed hard during the model step. After restart the library and reading position were intact, the chapter went back to the queue and finished by itself, and the six finished steps were skipped at 0.0 s and $0. The interrupted model step is redone from its start; what the killed run had already spent is not tracked.
- Frontend: typecheck clean, production build, 13 timeline tests.

**NOT verified: the new pages in a browser.** Home, Manga (add chapter, folder picker, upload progress, status/progress, delete dialogs) and the Read page with position restore have been typechecked and built, and every API call they make was exercised over HTTP, but nobody has clicked through them yet (the Chrome extension is not connected here).

**Known limits**
- Cost: the real runs cost about $0.06 per packet at list price (model steps only). A chapter of around 57 packets is therefore roughly $3, plus the one-off cast step. Batch size and concurrency are settings (`MANGA_DIRECT_BATCH`, `MANGA_DIRECT_CONCURRENCY`).
- One chapter is processed at a time. Chapters wait in the queue in the order they were added.
- Later chapters of the same manga extend its cast and keep every existing voice; extend mode itself is tested with the fake agent only, not yet with a real second chapter.
- The detector checkpoint (`.cache/detector/*.pt`) must exist; it is not downloaded automatically.
- Uploads: PNG, JPEG or WebP, up to 400 pages and 40 MB each; pages are normalised to one width (at most 900 px).
- A job interrupted mid-model-step repeats that step.

## Your Claude plan and usage (checked 2026-11-07)
- Claude Code here is signed in with `authMethod: claude.ai`, `subscriptionType: pro`, and no API-key variable is set, so the unattended agent runs draw on the **Pro subscription's usage**, not on API billing. The `total_cost_usd` the CLI reports is a **list-price equivalent** (`costBasis: list`), shown in the app as "Claude usage ≈ $x at list price"; it is not a charge.
- The interactive Claude Code session and the queue's agents share the same plan limits.
- **If a limit is hit** (usage limit, rate limit, quota), the model step now fails at once with "Claude usage limit reached ... press Retry after your limit resets" instead of retrying uselessly; finished steps are kept and Retry resumes from the failed step. If extra/usage-based billing is off on the account (as reported by the owner; not visible from here), hitting the limit stops work rather than charging.
- A rough scale from measured runs: about $0.06 of list-price usage per packet, so roughly $3 of list-price usage for a 57-packet chapter. How much of a Pro allowance that is depends on the plan's current limits, which are not visible from here; `/usage` in Claude Code shows the remaining allowance.
- Headless mode is an official Claude Code feature and this is a personal local tool. Using your login to run something for other people would be a different matter and should be checked against Anthropic's current terms.
