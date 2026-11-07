from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIBRARY = Path(os.environ.get("MANGA_LIBRARY", ROOT / "library")).resolve()
DB_PATH = LIBRARY / "library.db"
PYTHON = sys.executable
DIST = ROOT / "app" / "dist"

# uploads
MAX_PAGE_BYTES = 40 * 1024 * 1024
MAX_PAGES_PER_CHAPTER = 400
IMAGE_SIGNATURES = {  # file signature -> extension we store under
    b"\x89PNG\r\n\x1a\n": ".png",
    b"\xff\xd8\xff": ".jpg",
}

ALLOWED_HOSTS = {"localhost", "127.0.0.1", "[::1]"}
if os.environ.get("MANGA_ALLOW_TESTCLIENT"):
    ALLOWED_HOSTS.add("testserver")

# processing
DIRECT_BATCH_PACKETS = int(os.environ.get("MANGA_DIRECT_BATCH", "6"))
DIRECT_CONCURRENCY = int(os.environ.get("MANGA_DIRECT_CONCURRENCY", "3"))

# LLM provider: "auto", "claude", or "agy"
LLM_PROVIDER = os.environ.get("MANGA_LLM_PROVIDER", "auto").lower()
AGY_MODEL = os.environ.get("MANGA_AGY_MODEL", "")
