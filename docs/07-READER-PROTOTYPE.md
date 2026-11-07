# 07 - Reader prototype (Track D)

A working read-along reader for the sample episode: the strip auto-scrolls to each spoken bubble, highlights it, and plays its voice. Built as the real app skeleton (Vite + React + TypeScript), not a throwaway page.

## Run it

```
# one-time: build the bundle (script + web images), then voices
.venv\Scripts\python.exe -I spike\package\build_bundle.py assemble "<episode>\images" samples\ep01\_run bundles\ep01
.venv\Scripts\python.exe -I spike\package\render_audio.py bundles\ep01       # about 6 min on this CPU, cached afterwards

# the app
cd app
pnpm dev            # http://localhost:5173   (?ep=<folder under bundles/>, default ep01)
pnpm test           # timeline unit tests
pnpm typecheck
```
Voices per character are in `spike/package/voices.json`; edit and re-run `render_audio.py` (only changed lines are re-synthesised, keyed by text + voice + speed).

## What is in the bundle (bundles/ep01, gitignored)
- `script.json`: 201 beats, **all directed** (the whole chapter went through Director agents). 142 are voiced (6.0 minutes), 59 are credits, sound effects, notes or skipped fragments and are silent.
- `strip/*.webp`: 28 slices, 7.6 MB. `audio/*.ogg`: 142 clips.
- Voices: c1 `bm_george`, c2 `am_michael`, c3 `af_heart`, c4 `bf_emma`, narrator `am_adam`, system `af_alloy`, announcer `af_jessica`. One voice per speaker id, no generic fallback voice any more.

## Changes after the first listening test
User feedback: (1) voices did not match the characters and changed from line to line; (2) the scroll moved too fast between lines to see the art.
1. **Cause of the voice flipping:** 151 of 171 lines were un-directed draft lines, so all speech used one generic voice and all captions the narrator, and even directed narration was split inconsistently between the protagonist and the narrator. Fix: the remaining 47 packets were directed (9 batch agents), and policy was fixed in the `manga-direct` skill and enforced in `build_bundle.py`: thought bubbles use the thinking character's voice; Director `speak_order` is honoured inside a packet. (Narration policy changed again below.)
2. **Cause of the fast scroll:** travel was 650 px/s with a hard 3.6 s cap, so long art stretches were crossed at 1,400+ px/s. Now 300 px/s default with a 30 s cap (about 3 s per screen of art), plus a **Scroll** control: Slow 200, Relaxed 300, Normal 450, Fast 800 px/s. Full chapter now plays in about 14.6 minutes at Relaxed and normal speed.

## Second round of feedback and the "Wrong voice?" button
User feedback after the whole chapter was directed: the first pages were fine, later ones were not; a character's voice should stay the same through the whole chapter; some bubbles sound like the wrong person. Chosen answers: fix it **while listening**, and **Aiden's own narration should use Aiden's voice**.

- **Narration rule (changed):** a caption is the voice of whoever is speaking it. The protagonist's first-person narration and inner monologue use his cast id; third-person narration, retold sayings and recaps use the narrator. Do not alternate line by line. In `manga-direct/SKILL.md`. For this chapter it is applied as 33 `policy` overrides (the first-person run from the line that introduces him through his reflections) in `bundles/ep01/overrides.json`, because re-directing everything would cost about 670k tokens again.
- **Wrong voice? button** (in the control bar; works on the line currently shown in the caption): choose who really speaks it (a character, narrator, system window, announcer), or "Don't read this line", or undo an earlier correction. The reader posts to a local endpoint, which writes `overrides.json` and runs `build_bundle.py rebuild`, which re-applies overrides and re-synthesises **only the lines whose voice changed**. Measured: one correction takes about 4.4 s end to end, an undo about 5.4 s, a no-change rebuild 1 s. The line then plays again in the new voice. A counter shows how many corrections are saved.
- **Corrections are data.** Each user override records the original speaker (`was`), who made it (`user` vs `policy`) and when. The share of lines you had to correct is the first real accuracy number for the Director step, and the corrected set becomes the regression set for Phase 2.
- **Safety of the endpoint (it can start a process):** dev server only; fixed command and arguments; episode, beat id and speaker validated against the bundle; same-origin only; JSON only; 4 KB body limit; one rebuild at a time (a failed request does not jam the queue). Tested with: wrong method, wrong content type, foreign Origin, foreign Host, path traversal in the episode name, bad beat id, unknown speaker, unknown beat, oversized body. All rejected, and none of them modified `overrides.json`.

## Age and emotion: "Expressive" voices
Request after listening: adjust each voice to the character's age, and add some emotion to the reading. Everything stays local and free (decision D4); a **Voice: Expressive / Plain** switch in the control bar lets you compare, and Plain is exactly what you heard before.

- **Age** (`spike/package/voices.json`): each speaker has a `pitch_st` and `speed`. Pitch is shifted with rubberband (bundled ffmpeg) **with formants moving along**, which is what makes a voice read younger (up) or older (down). Current profile from the cast ages: father (adult, stern older man) -1.5 semitones and 0.95x speed; Aiden (young adult) unchanged; sister (teen) +2.5 semitones and 1.05x; Noel (young adult, commanding) -0.7 and 0.97x. Narrator, system and announcer unchanged.
- **Emotion** (`EMOTION_STYLE` in `build_bundle.py`): each Director emotion maps to small pitch, speed and loudness moves, e.g. excited +1.4 semitones, 1.10x, louder; sad -1.2, 0.90x, softer; menacing -1.8, 0.88x. Delivery notes refine it: whisper/hushed is much quieter and slower; shout is louder and higher; "trailing off" and "hesitant" are slower; "stammering/nervous" is slightly higher. Totals are clamped (pitch +/-4.5 semitones, speed 0.8-1.2x) because beyond that speech artefacts appear.
- **Verified:** `spike/package/test_pitch.py` checks the shifter on a known tone and on real clips: pitch lands within a few percent of the request and the line length changes by under 2.5%.
- **Honest limit:** this shapes the voice; it does not act. A local CPU model cannot do real emotion (see `04-TTS-CANDIDATES.md`), so expect more variety, not performance. Acting is the paid-voice upgrade. 79 of 142 lines are tagged neutral by the Directors, so most lines change little; the effect is mainly on the exclamations, whispers, tired and sarcastic lines and on the sister and father sounding their ages.
- **Not yet judged:** whether it sounds better. That needs your ears; use the switch, and tell me which lines or characters feel wrong (age profile numbers are the first thing to tune).

## How playback works (`app/src/engine`)
- `timeline.ts` (pure, 13 unit tests): from voiced beats it computes, for each line, a travel interval (camera eases to put the bubble at 38% of the viewport height; default 300 px/s, clamped 0.7 to 30 s, user-selectable) and a speaking interval (exactly the clip length divided by the speed). Camera position and the active line are functions of time.
- `player.ts`: **the Web Audio clock is the only clock.** Clips are scheduled at exact context times up to 4 s ahead, the camera is computed from the same clock, pause is `AudioContext.suspend()` so voice and scroll freeze together. Seeking and speed changes rebuild the timeline and reschedule.
- `Reader.tsx`: renders the strip as stacked slices, highlight overlay on the active bubble, a tap target on every voiced bubble (tap = play from here), and steps aside when the reader grabs the scroll (wheel/touch pauses; Play then continues from where they are, not from the old spot).
- Controls: play/pause/resume/replay, previous/next line, speed 0.75 to 2x, volume, caption with speaker name.

## Verified
- Typecheck clean, 13 timeline tests pass (two cover the pace fix), production build succeeds (230 kB JS, 72 kB gzip).
- Dev server serves `script.json`, webp and ogg with correct content types. Bundle middleware blocks path traversal (5 encodings tried, all 403); I fixed a sibling-directory prefix hole in it while checking.
- Missing bundle now gives a clear message instead of a JSON parse error.

## NOT verified (read this)
- **It has not been run in a browser by me, including the new Wrong voice? button and dialog.** The server side of that button was tested with HTTP requests only. The Chrome extension was not connected, so nothing about actual playback was observed: audio start, voice/scroll sync, highlight position, pause/resume, tap-to-play, manual-scroll takeover. Treat all of that as untested until someone opens it.
- Hearing the voices on this chapter, and whether the scroll pace feels right, are subjective and need a person.
- Mobile layout is written but not tried on a phone.

## Known limitations
- Speaker attribution is still only machine-checked: 11 beats are below 0.7 confidence, and the batch Directors flagged about 35 beats as uncertain (off-panel speakers, white-on-black captions that may be thoughts, partly hidden system windows). Voices will sometimes be wrong until `labels.json` from the verify page exists. The verify page currently covers only the first 10 packets.
- Ogg Vorbis clips: widely supported in Chrome and Firefox; Safari support for decoding it is uncertain. Switch to AAC or Opus-in-MP4 if Safari matters.
- No progress memory, no bundle picker, no editor, no offline cache yet (Phases 4 and 5 of the plan).
- Local voices change speed and pick a voice, they do not act: emotion is mostly lost. That is the known ceiling of the free tier (decision D4).
