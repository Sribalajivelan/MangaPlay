# MangaPlay

> **Turn silent manga and webtoons into playable, voiced performances.**

MangaPlay is a local, AI-powered web reader that can **play itself**. It smoothly moves a virtual camera across panels and vertical strips, reads each speech bubble aloud with distinct character voices and emotion, and highlights the dialogue in real time—giving you the feeling of watching an anime adaptation while preserving the original comic artwork.

---

## What MangaPlay Does

- **Automated "Watch & Listen" Player:** Plays chapters like a timeline. The camera automatically scrolls and centers on speaking characters, highlights bubbles as dialogue is delivered, and transitions between beats.
- **Intelligent Bubble Detection & OCR:** Automatically finds speech bubbles, thoughts, captions, and SFX across tall webtoon strips and traditional pages using a lightweight YOLO model and RapidOCR.
- **AI-Directed Voice Casting & Performance:** Leverages Claude to identify characters, understand context, infer emotional tone (angry, whisper, sarcastic, cheerful, etc.), and assign stable voices to cast members across entire series.
- **Consistent Local Character Voices:** Renders distinct voice lines using **Kokoro TTS (ONNX)** running entirely on your CPU. Characters sound consistent across every chapter in a series.
- **Expressive vs. Plain Audio Modes:** Generates natural pitch and emotion-inflected voice clips alongside clean baseline speech. Toggle between them seamlessly in the player.
- **In-Reader "Wrong Voice" Corrections:** If the director misattributes a line, hit `V` or click **Wrong voice** to reassign the speaker or mute the bubble on the fly. Corrections survive re-runs.
- **Zero-Latency Static Bundles:** All AI detection and voice generation happens offline during chapter ingest. Playback in the browser uses pre-rendered static assets—no runtime LLM delays or token costs while reading.
- **Persistent Reading State:** Automatically remembers your reading position, playback rate, camera scroll pace, volume, and audio preferences in a local SQLite database.

---

## How It Works (Pipeline Architecture)

MangaPlay separates **offline authoring** from **real-time playback**:

```
+-------------------------------------------------------------------------+
|                       AUTHORING PIPELINE (Offline)                      |
|                                                                         |
|  [Ingest Images] ──> [Detect Bubbles] ──> [OCR Text] ──> [Fuse Beats]   |
|         │                                                               |
|         ▼                                                               |
|  [Make Packets] ──> [Claude Cast/Direct] ──> [Assign Voices]            |
|         │                                                               |
|         ▼                                                               |
|  [Kokoro TTS Synthesis] ──> [Chapter Bundle (static files)]             |
+-------------------------------------------------------------------------+
                                    │
                                    ▼
+-------------------------------------------------------------------------+
|                        MANGAPLAY READER (Web / PWA)                     |
|                                                                         |
|   Smooth Virtual Camera ── Sync Audio Beats ── Bubble Highlighting      |
+-------------------------------------------------------------------------+
```

### Chapter Processing Stages:
1. **`ingest`**: Validates image slices (PNG/JPG/WebP), normalizes widths, and indexes strips.
2. **`detect`**: Locates speech bubbles, narration boxes, and gutter boundaries on CPU.
3. **`ocr`**: Extracts dialogue lines and bounding boxes using RapidOCR (ONNX).
4. **`fuse`**: Groups detected bounding boxes with transcript text into draft timeline beats.
5. **`packets`**: Chunks beats into coherent context windows for directing.
6. **`cast`**: Headless Claude pass creates or updates the persistent series cast bible.
7. **`direct`**: Claude assigns speaker identities, emotional delivery, pacing, and camera hints.
8. **`voices`**: Maps cast characters to age- and gender-matched Kokoro voice profiles.
9. **`package`**: Synthesizes `.opus` audio clips, builds continuous strip images, and outputs a ready-to-read static bundle.

---

## System Requirements & Prerequisites

### 1. Hardware
- **CPU:** Standard multi-core x86_64 CPU (e.g., Intel Core i5/i7 or AMD Ryzen).
- **RAM:** 16 GB minimum (32 GB recommended when processing long, high-resolution webtoon strips).
- **GPU:** **Not required.** All local neural models (YOLO detection, RapidOCR, Kokoro TTS) run on CPU via ONNX Runtime.

### 2. Software
- **Operating System:** Windows 10/11, macOS, or Linux.
- **Python:** `3.11` (with `pip` and virtual environment support).
- **Node.js:** `v20.x` or `v24.x` + [**pnpm**](https://pnpm.io/).
- **Claude Code CLI:** Required for the headless agent stages (`cast` and `direct`).
  - Install via npm: `npm install -g @anthropic-ai/claude-code`
  - Authenticate with your Anthropic subscription / login: `claude login`

---

## Installation & Setup

### 1. Clone the Repository
```bash
git clone git@github-personal:Sribalajivelan/MangaPlay.git
cd MangaPlay
```

### 2. Set Up Python Environment
Create and activate a Python virtual environment:

**Windows (PowerShell):**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**macOS / Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install required dependencies:
```bash
pip install fastapi uvicorn pydantic pillow opencv-python onnxruntime rapidocr-onnxruntime kokoro-onnx ultralytics soundfile imageio-ffmpeg wordninja httpx pytest
```

### 3. Set Up Frontend
Install the web application dependencies:
```bash
cd app
pnpm install
cd ..
```

---

## Running MangaPlay

### Quick Start (Windows)
Run the provided startup script:
```powershell
.\start.ps1
```
This script builds the frontend (if not already built) and launches the FastAPI server.

### Manual Start (Cross-Platform)
1. **Build the web app:**
   ```bash
   cd app
   pnpm build
   cd ..
   ```
2. **Start the backend server:**
   ```bash
   python -m uvicorn server.main:app --host 127.0.0.1 --port 8000
   ```
3. Open your browser to **`http://127.0.0.1:8000`**.

### Development Mode
For live frontend hot-reloading during development:
- Run the backend: `python -m uvicorn server.main:app --host 127.0.0.1 --port 8000`
- Run the frontend in a second terminal:
  ```bash
  cd app
  pnpm dev
  ```
  Open **`http://localhost:5173`** (Vite automatically proxies `/api` and `/bundle` to `:8000`).

---

## How to Use

### 1. Create a Manga
- On the **MangaPlay** home screen (`http://127.0.0.1:8000`), enter the title of your manga or webtoon in the input box and click **Create manga**.

### 2. Add a Chapter
- Select your manga to enter its detail page.
- Enter a chapter number and optional title.
- Click **Choose folder** to select a directory containing your chapter images (ordered slice images such as `.png`, `.jpg`, or `.webp`).
- Click **Upload & start processing**.

### 3. Background Processing Queue
- The server automatically processes the chapter through all 9 stages (`ingest` ➔ `detect` ➔ `ocr` ➔ `fuse` ➔ `packets` ➔ `cast` ➔ `direct` ➔ `voices` ➔ `package`).
- A live progress indicator will show current stage status and estimated model usage cost.
- If processing is interrupted or the server restarts, the chapter automatically re-queues and resumes from the last completed stage.

### 4. Read & Listen
- Once the status turns to **Ready**, click **Read** to launch the interactive player.
- Press **Space** or the Play button to begin playback.
- The camera will automatically ease down the page, highlighting each bubble as its voice line plays.

---

## Reader Keyboard Shortcuts

| Shortcut | Action |
| :--- | :--- |
| <kbd>Space</kbd> / Click | **Play / Pause** toggle |
| <kbd>→</kbd> or <kbd>K</kbd> | Jump to **Next beat** |
| <kbd>←</kbd> or <kbd>J</kbd> | Jump to **Previous beat** |
| <kbd>F</kbd> | Toggle **Full Screen** |
| <kbd>Tab</kbd> or <kbd>H</kbd> | Hide / Show Controls & Top Bar |
| <kbd>V</kbd> | Open **Wrong Voice** / Speaker Reassignment dialog |
| <kbd>Esc</kbd> | Close dialog or exit full screen |

---

## In-Reader Correction Tools

If the automated director makes a mistake:
1. Press <kbd>V</kbd> or click **Wrong voice** in the control bar while paused on any dialogue bubble.
2. Select the correct character from the cast list, assign to Narrator/System, or mute the beat.
3. The change is saved to `overrides.json` and immediately applies to playback.

---

## Project Structure

```
MangaPlay/
├── app/                  # Web player & Library UI (React, TypeScript, Vite)
│   ├── src/
│   │   ├── components/   # Reader, MiniBar, Controls, SpeakerPicker, UI
│   │   ├── engine/       # Timeline scheduler & audio player
│   │   └── pages/        # Home, Manga detail, and Read pages
│   └── package.json
├── server/               # FastAPI backend & offline pipeline
│   ├── main.py           # API endpoints & bundle server
│   ├── stages.py         # 9-stage pipeline implementation
│   ├── worker.py         # Background worker queue
│   ├── voices.py         # Voice assignment & Kokoro TTS pools
│   ├── llm.py            # Headless Claude Code integration
│   └── db.py             # SQLite database layer
├── spike/                # Prototype and benchmark modules
│   ├── detect/           # Bubble segmentation, YOLO & OCR spikes
│   ├── direct/           # Casting and performance directing tools
│   ├── package/          # Bundle compiler & audio rendering
│   └── tts/              # Kokoro TTS latency & scaling benchmarks
├── docs/                 # Architectural specifications & decision logs
├── library/              # Local storage for DB, uploads & ready bundles (gitignored)
├── start.ps1             # One-click Windows startup script
└── README.md
```

---

## Privacy & Local-First Philosophy

- **Local Storage:** All uploaded scans, processed strips, voice clips, and reading progress reside exclusively in your local `library/` directory.
- **Local Voice Generation:** Audio synthesis runs 100% locally on your machine via CPU-based ONNX models.
- **Scoped AI Directing:** Only text transcriptions and cropped scene snippets are inspected by Claude during the authoring step to perform character assignment and emotion directing.

---

## License

This project is licensed under the [MIT License](LICENSE).
