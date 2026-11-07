# 04 - Local TTS candidates (CPU, English)

Status: **from web search only, not yet measured on this machine.** Sources are mostly blog posts that disagree with each other; the Phase 0 spike replaces every claim here with a number. Treat each row as "worth testing".

| Candidate | Why it is on the list | Concerns to verify |
|---|---|---|
| **Kokoro-82M** via `kokoro-onnx` | Small (about 300 MB, about 80 MB quantised), runs on ONNX Runtime CPU, many preset voices, weights reported Apache-2.0, `kokoro-onnx` package MIT | Exact voice count and list (check the model's own VOICES.md; sources say 8 to 54). Phonemiser dependencies: the model card mentions GPLv3 `espeak-ng` - fine for a personal tool, relevant only if we ever distribute. Emotion control is limited to voice choice, speed and punctuation, not tags. |
| **Piper** | Very light, real-time on tiny hardware, many voices | Audibly more synthetic than Kokoro per one reviewer. One source says the PyPI `piper-tts` 1.7.0 is GPL-3.0-or-later - again personal use only, but check before any distribution. |
| **Kitten TTS nano** | About 24 MB, Apache-2.0 | Lower quality; useful only as a fast fallback. |
| Chatterbox, Orpheus | Praised for emotion | Not CPU-friendly (Orpheus needs roughly 8-12 GB VRAM). **Excluded by D5**, revisit for the paid/GPU tier. |

## Spike test

Same 20 English lines (statements, shouts, whispers, questions, one-word reactions) through each candidate, on this machine:

- real-time factor (seconds of audio per second of compute) with 1 and with 4 threads
- first-audio latency
- subjective score 1-5 for naturalness and for "does this voice suit a given character"
- number of clearly different usable voices (male/female, young/old)
- install friction on Windows (no admin, no system ffmpeg)

Pick Kokoro as the default only if it is at least about 3x real time on this CPU (a chapter must render in minutes, not hours) and has enough distinct voices to cast 4-6 recurring characters.

## Measured: Kokoro int8 on this machine (2026-11-07)

Hardware: i7-1255U (2 performance + 8 efficiency cores, 12 threads), 32 GB, Windows 11, `kokoro-onnx` 0.6.1 + `onnxruntime` 1.31.1, `kokoro-v1.0.int8.onnx` (92 MB). 20 original test lines, about 45 s of audio. Scripts: `spike/tts/bench_kokoro.py`, `spike/tts/bench_kokoro_scaling.py`.

| Setup | x real time |
|---|---|
| 1 process, 1 thread | 0.37 |
| 1 process, 4 threads | 1.15 |
| 1 process, 8 threads (best single process) | 1.15 |
| 1 process, 12 threads (oversubscribed) | 0.76 |
| **3 processes x 4 threads (best batch throughput)** | **2.18** |
| 6 processes x 2 threads | 2.04 |

Findings:
- Voice list: **54 voices total, 28 US/UK English** (the sources disagreed, 8 vs 54; the 54 is right for v1.0). Enough to cast 4-6 recurring characters plus a narrator with room to spare.
- It is **not real-time per line** (first line about 2.4 s at 4 threads), so audio must be pre-rendered, which the design already assumes. Live synthesis during playback is off the table on this CPU.
- Batch throughput is about **2x real time**, below the 3x I originally set as the bar. Because rendering is offline and cached by content hash, this is acceptable: a webtoon episode with about 8 minutes of speech renders in roughly 4 minutes. I am relaxing the criterion to "an episode renders in under about 10 minutes", and flagging that it was relaxed after seeing the number.
- Untested: the fp32 model (310 MB, may be faster or slower than int8 on this CPU), the quality difference between int8 and fp32, and Piper.
- **Not yet judged: how it sounds.** 20 WAVs per voice for 4 voices are in `spike/tts/out/` (named `<voice>_<NN>_<style>.wav`). Naturalness and "does this suit a character" need your ears, not mine.

## Webtoon bubble detection candidates (for the detector stage)

| Candidate | Notes |
|---|---|
| `Zaidppo/comic-speech-bubble-detector-yolov8m` (Hugging Face) | Trained on about 8k manga, webtoon, manhua and western comic images; closest match to our need. Licence not confirmed. |
| Roboflow "webtoon bubble detection" dataset | Eight classes including dialog, narration, sound-effect, thought; listed CC BY 4.0. Could fine-tune on CPU only with difficulty, so treat as eval data first. |
| `mnemic/comic_speechbubble_yolov8`, `AymanKUMA` detector | Research/academic-only per their pages. Avoid as a dependency; fine to compare against for the spike. |

Note: the Ultralytics YOLOv8 runtime is AGPL-3.0, acceptable for a personal tool, but it is a reason to keep the detector behind an interface (ONNX export + plain `onnxruntime` removes the dependency).

## Sources
- [Browser TTS Showdown: Kokoro vs Piper vs Kitten](https://offlinetts.com/blog/browser-tts-showdown-kokoro-piper-kitten/)
- [Best open source TTS 2026](https://findskill.ai/blog/best-open-source-tts-2026/)
- [Best TTS without GPU](https://localaimaster.com/blog/best-tts-without-gpu)
- [kokoro-onnx on PyPI](https://pypi.org/project/kokoro-onnx)
- [Kokoro-82M model card](https://huggingface.co/hexgrad/Kokoro-82M/blob/refs%2Fpr%2F44/README.md)
- [Zaidppo comic speech bubble detector](https://huggingface.co/Zaidppo/comic-speech-bubble-detector-yolov8m)
- [mnemic comic_speechbubble_yolov8](https://huggingface.co/mnemic/comic_speechbubble_yolov8)
- [Roboflow webtoon bubble detection](https://universe.roboflow.com/john-dykes-m6bih/webtoon-bubble-detection)

## Emotion on a CPU: what exists (web search 2026-11-07, unverified claims)

Question: is there a local model with real emotion control that runs on this CPU-only machine? Answer from the search: **no established one.**
- Kokoro has no emotion control (it is fast on CPU, which is why it is the baseline).
- Chatterbox has an explicit emotion "exaggeration" control, but is listed as GPU-recommended.
- Fish Speech S2 supports emotion tags such as whisper and angry, but the sources describe GPU self-hosting and give no CPU numbers.
- VoxCPM2 reviews say it needs serious GPU acceleration.
- SouraTTS is the only candidate described as CPU-first with emotions (built on Kyutai's Pocket-TTS, six emotions), but only a third-party mirror page was found, with a warning about instability at higher intensities. Treat as unproven until checked at the source.
So on this hardware emotion is **shaped**, not acted (pitch, pace, loudness per line, see `07-READER-PROTOTYPE.md`). Acting is the paid-voice upgrade (decision D4); when that is evaluated, the Director's per-line emotion and delivery fields are already the input it needs.

Sources: [Fish Speech S2 overview](https://emelia.io/hub/fish-speech-s2-tts), [Kokoro vs XTTS vs Chatterbox](https://localaimaster.com/blog/kokoro-vs-xtts-vs-chatterbox), [VoxCPM2 review](https://aiindigo.com/blog/voxcpm2-review-professional-grade-voice-synthesis-for-everyone), [SouraTTS mirror page](https://hf-2025.pages.dev/Sourajit123/SouraTTS)
