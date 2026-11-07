import pytest

from server import config, db

from .conftest import make_chapter, png_bytes

OCTET = {"content-type": "application/octet-stream"}


# ---- library -------------------------------------------------------------------------------------------
def test_create_list_rename_delete_manga(client):
    m = client.post("/api/manga", json={"title": "  My   Manga "}).json()
    assert m["title"] == "My Manga"  # whitespace collapsed
    assert [x["title"] for x in client.get("/api/manga").json()["manga"]] == ["My Manga"]
    assert client.patch(f"/api/manga/{m['id']}", json={"title": "Renamed"}).json()["title"] == "Renamed"
    assert client.delete(f"/api/manga/{m['id']}").status_code == 204
    assert client.get("/api/manga").json()["manga"] == []
    assert client.get(f"/api/manga/{m['id']}").status_code == 404


@pytest.mark.parametrize("bad", ["", "   ", "x" * 201])
def test_manga_title_validation(client, bad):
    assert client.post("/api/manga", json={"title": bad}).status_code == 422


def test_chapter_numbering_and_listing(client):
    m = client.post("/api/manga", json={"title": "M"}).json()
    a = client.post(f"/api/manga/{m['id']}/chapters", json={}).json()
    b = client.post(f"/api/manga/{m['id']}/chapters", json={}).json()
    c = client.post(f"/api/manga/{m['id']}/chapters", json={"number": 10, "title": "Ten"}).json()
    assert (a["number"], b["number"], c["number"]) == (1, 2, 10)
    got = client.get(f"/api/manga/{m['id']}").json()["chapters"]
    assert [x["number"] for x in got] == [1, 2, 10]
    assert all(x["status"] == "uploading" for x in got)


# ---- uploads -------------------------------------------------------------------------------------------
def test_upload_and_finalize_queues_chapter(client):
    mid, cid = make_chapter(client, pages=3)
    out = client.post(f"/api/chapters/{cid}/finalize").json()
    assert out["status"] == "queued" and out["page_count"] == 3
    files = sorted(p.name for p in (db.chapter_dir(mid, cid) / "source").iterdir())
    assert files == ["001.png", "002.png", "003.png"]  # server-chosen names, never the client's


def test_upload_rejects_non_images(client):
    m = client.post("/api/manga", json={"title": "M"}).json()
    ch = client.post(f"/api/manga/{m['id']}/chapters", json={}).json()
    for payload in (b"MZ\x90\x00 not an image", b"<svg onload=alert(1)>", b"GIF89a....", b""):
        r = client.put(f"/api/chapters/{ch['id']}/pages/1", content=payload, headers=OCTET)
        assert r.status_code == 415, payload


def test_upload_size_limit(client, monkeypatch):
    monkeypatch.setattr(config, "MAX_PAGE_BYTES", 1000)
    m = client.post("/api/manga", json={"title": "M"}).json()
    ch = client.post(f"/api/manga/{m['id']}/chapters", json={}).json()
    assert client.put(f"/api/chapters/{ch['id']}/pages/1", content=png_bytes(), headers=OCTET).status_code == 413


def test_upload_page_number_bounds(client):
    m = client.post("/api/manga", json={"title": "M"}).json()
    ch = client.post(f"/api/manga/{m['id']}/chapters", json={}).json()
    for n in (0, -1, config.MAX_PAGES_PER_CHAPTER + 1):
        assert client.put(f"/api/chapters/{ch['id']}/pages/{n}", content=png_bytes(), headers=OCTET).status_code == 400


def test_finalize_requires_contiguous_pages(client):
    m = client.post("/api/manga", json={"title": "M"}).json()
    ch = client.post(f"/api/manga/{m['id']}/chapters", json={}).json()
    assert client.post(f"/api/chapters/{ch['id']}/finalize").status_code == 400  # nothing uploaded
    for n in (1, 3):
        client.put(f"/api/chapters/{ch['id']}/pages/{n}", content=png_bytes(), headers=OCTET)
    assert client.post(f"/api/chapters/{ch['id']}/finalize").status_code == 400  # gap at 2
    client.put(f"/api/chapters/{ch['id']}/pages/2", content=png_bytes(), headers=OCTET)
    assert client.post(f"/api/chapters/{ch['id']}/finalize").status_code == 200


def test_no_uploads_after_finalize(client):
    _, cid = make_chapter(client)
    client.post(f"/api/chapters/{cid}/finalize")
    assert client.put(f"/api/chapters/{cid}/pages/1", content=png_bytes(), headers=OCTET).status_code == 409
    assert client.post(f"/api/chapters/{cid}/finalize").status_code == 409


# ---- delete --------------------------------------------------------------------------------------------
def test_delete_chapter_removes_rows_and_files(client):
    mid, cid = make_chapter(client)
    client.post(f"/api/chapters/{cid}/finalize")
    client.put(f"/api/chapters/{cid}/reading-state", json={"beat_id": "b001", "y": 10})
    cdir = db.chapter_dir(mid, cid)
    assert cdir.exists()
    assert client.delete(f"/api/chapters/{cid}").status_code == 204
    assert not cdir.exists()
    assert client.get(f"/api/chapters/{cid}").status_code == 404
    with db.db() as con:
        assert con.execute("SELECT COUNT(*) FROM reading_state").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM app_state WHERE key='last_chapter'").fetchone()[0] == 0


def test_delete_manga_cascades(client):
    mid, cid = make_chapter(client)
    client.post(f"/api/chapters/{cid}/finalize")
    assert client.delete(f"/api/manga/{mid}").status_code == 204
    assert not db.manga_dir(mid).exists()
    with db.db() as con:
        for t in ("chapter", "reading_state", "stage_run"):
            assert con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0


def test_cancel_queued_chapter_then_retry(client):
    _, cid = make_chapter(client)
    client.post(f"/api/chapters/{cid}/finalize")
    assert client.post(f"/api/chapters/{cid}/cancel").json()["status"] == "cancelled"
    assert client.post(f"/api/chapters/{cid}/cancel").status_code == 409
    assert client.post(f"/api/chapters/{cid}/retry").json()["status"] == "queued"
    assert client.post(f"/api/chapters/{cid}/retry").status_code == 409


# ---- reading state: survives a restart -------------------------------------------------------------------
def test_reading_state_roundtrip_and_continue(client):
    mid, cid = make_chapter(client)
    with db.db() as con:
        con.execute("UPDATE chapter SET status='ready' WHERE id=?", (cid,))
    assert client.get(f"/api/chapters/{cid}/reading-state").json() is None
    client.put(f"/api/chapters/{cid}/reading-state", json={"beat_id": "b042", "y": 12345.5, "rate": 1.25, "pace": 450, "expressive": False})
    s = client.get(f"/api/chapters/{cid}/reading-state").json()
    assert (s["beat_id"], s["y"], s["rate"], s["pace"], s["expressive"]) == ("b042", 12345.5, 1.25, 450, 0)
    # a later save that omits the settings keeps them
    client.put(f"/api/chapters/{cid}/reading-state", json={"beat_id": "b050", "y": 20000})
    s = client.get(f"/api/chapters/{cid}/reading-state").json()
    assert (s["beat_id"], s["rate"], s["pace"]) == ("b050", 1.25, 450)
    cont = client.get("/api/manga").json()["continue"]
    assert cont["id"] == cid and cont["manga_id"] == mid


@pytest.mark.parametrize("body", [{"beat_id": "x1"}, {"beat_id": "b1;drop"}, {"y": -5}, {"rate": 99}, {"pace": 1}])
def test_reading_state_validation(client, body):
    _, cid = make_chapter(client)
    assert client.put(f"/api/chapters/{cid}/reading-state", json=body).status_code == 422


def test_data_survives_reopening_the_database(client):
    """The 'restart' guarantee: nothing lives only in memory."""
    mid, cid = make_chapter(client)
    client.put(f"/api/chapters/{cid}/reading-state", json={"beat_id": "b007", "y": 99})
    with db.db() as con:  # a brand-new connection, as after a restart
        r = con.execute("SELECT beat_id, y FROM reading_state WHERE chapter_id=?", (cid,)).fetchone()
        assert (r["beat_id"], r["y"]) == ("b007", 99)
        assert con.execute("SELECT title FROM manga WHERE id=?", (mid,)).fetchone()["title"] == "Manga"


# ---- security ------------------------------------------------------------------------------------------
def test_foreign_origin_is_refused_on_writes(client):
    r = client.post("/api/manga", json={"title": "x"}, headers={"Origin": "http://evil.example"})
    assert r.status_code == 403
    assert client.get("/api/manga").json()["manga"] == []  # nothing was created


def test_same_origin_write_is_allowed(client):
    assert client.post("/api/manga", json={"title": "x"}, headers={"Origin": "http://localhost"}).status_code == 201


def test_foreign_host_is_refused(client):
    assert client.get("/api/manga", headers={"Host": "evil.example"}).status_code == 400


def test_bundle_path_traversal_is_refused(client):
    mid, cid = make_chapter(client)
    bdir = db.chapter_dir(mid, cid) / "bundle"
    bdir.mkdir(parents=True)
    (bdir / "script.json").write_text("{}")
    (db.chapter_dir(mid, cid) / "secret.txt").write_text("nope")
    assert client.get(f"/bundle/{cid}/script.json").status_code == 200
    for p in ("../secret.txt", "..%2fsecret.txt", "%2e%2e/secret.txt", "sub/../../secret.txt"):
        assert client.get(f"/bundle/{cid}/{p}").status_code == 404, p


def test_unknown_api_paths_are_404_not_the_app(client):
    assert client.get("/api/nope").status_code == 404
    assert client.get("/bundle/999/x").status_code == 404


def test_db_helpers_refuse_to_delete_outside_the_library(tmp_path):
    outside = tmp_path / "keep"
    outside.mkdir()
    with pytest.raises(ValueError):
        db.remove_tree(outside)
    assert outside.exists()


def test_bundle_files_are_served_with_real_media_types(client):
    mid, cid = make_chapter(client)
    bdir = db.chapter_dir(mid, cid) / "bundle"
    (bdir / "audio").mkdir(parents=True)
    for name in ("script.json", "audio/a.ogg", "strip.webp", "x.bin"):
        (bdir / name).write_bytes(b"data")
    want = {"script.json": "application/json", "audio/a.ogg": "audio/ogg", "strip.webp": "image/webp", "x.bin": "application/octet-stream"}
    for name, kind in want.items():
        r = client.get(f"/bundle/{cid}/{name}")
        assert r.status_code == 200 and r.headers["content-type"].startswith(kind), name
        assert r.headers["x-content-type-options"] == "nosniff"
