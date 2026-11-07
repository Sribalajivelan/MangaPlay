"""Tests run against a throwaway library in the temp folder; env vars are set BEFORE the app is imported."""
import io
import os
import shutil
import tempfile

_TMP = tempfile.mkdtemp(prefix="mangalib_test_")
os.environ["MANGA_LIBRARY"] = _TMP
os.environ["MANGA_NO_WORKER"] = "1"
os.environ["MANGA_ALLOW_TESTCLIENT"] = "1"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from server import config  # noqa: E402
from server.main import app  # noqa: E402


def png_bytes(w: int = 690, h: int = 1200, color=(255, 255, 255)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture()
def client():
    assert str(config.LIBRARY).startswith(tempfile.gettempdir()), "refusing to wipe a non-temp library"
    if config.LIBRARY.exists():
        shutil.rmtree(config.LIBRARY)
    with TestClient(app, base_url="http://localhost") as c:  # runs the lifespan: creates the schema
        yield c


def make_chapter(client, pages: int = 2, title: str = "T") -> tuple[int, int]:
    m = client.post("/api/manga", json={"title": "Manga"}).json()
    ch = client.post(f"/api/manga/{m['id']}/chapters", json={"title": title}).json()
    for n in range(1, pages + 1):
        r = client.put(f"/api/chapters/{ch['id']}/pages/{n}", content=png_bytes(), headers={"content-type": "application/octet-stream"})
        assert r.status_code == 200, r.text
    return m["id"], ch["id"]
