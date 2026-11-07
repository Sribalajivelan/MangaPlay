"""Command line helpers.

  python -m server.cli import-chapter --title "My Manga" --number 1 --images <folder> --run <run_dir> --bundle <bundle_dir>
      Move a chapter that was processed by hand (during the spike) into the library as READY, keeping its
      Director work, so nothing has to be paid for twice.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from . import config, db, stages, voices


def import_chapter(title: str, number: float, images: Path, run: Path, bundle: Path, voices_file: Path, chapter_title: str = "") -> int:
    db.init_db()
    with db.db() as con:
        m = con.execute("SELECT id FROM manga WHERE title=?", (title,)).fetchone()
        t = db.now()
        if m:
            manga_id = m["id"]
        else:
            manga_id = con.execute("INSERT INTO manga(title, created_at, updated_at) VALUES(?,?,?)", (title, t, t)).lastrowid
        n = len(sorted(p for p in images.iterdir() if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}))
        cid = con.execute(
            "INSERT INTO chapter(manga_id, number, title, status, page_count, created_at, updated_at, ready_at, detail) VALUES(?,?,?,?,?,?,?,?,?)",
            (manga_id, number, chapter_title, "ready", n, t, t, t, "imported")).lastrowid
    mdir, cdir = db.manga_dir(manga_id), db.chapter_dir(manga_id, cid)
    (cdir / "source").mkdir(parents=True)
    pages = sorted(p for p in images.iterdir() if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"})
    for i, p in enumerate(pages, 1):
        shutil.copyfile(p, cdir / "source" / f"{i:03d}{p.suffix.lower().replace('.jpeg', '.jpg')}")
    # run files the reader pipeline may need again (rebuilds); the large verify/overlay pictures are skipped
    shutil.copytree(run, cdir / "run", ignore=shutil.ignore_patterns("verify", "overlay_*", "_headless_test", "reviewed", "reviewer_input"))
    shutil.copytree(images, cdir / "run" / "images", dirs_exist_ok=True)
    shutil.copytree(bundle, cdir / "bundle", ignore=shutil.ignore_patterns("_*.log"))
    mdir.mkdir(parents=True, exist_ok=True)
    cast = json.loads((run / "cast" / "cast.json").read_text(encoding="utf-8"))
    (mdir / "cast.json").write_text(json.dumps(cast, ensure_ascii=False, indent=1), encoding="utf-8")
    voices.save(mdir / "voices.json", voices.assign(cast, voices.load(voices_file)))
    (cdir / "bundle" / "build.json").write_text(json.dumps({
        "images": str((cdir / "run" / "images").resolve()), "run": str((cdir / "run").resolve()),
        "cast": str((mdir / "cast.json").resolve()), "voices": str((mdir / "voices.json").resolve())}), encoding="utf-8")

    class _Ctx:  # only what _make_cover needs
        images = cdir / "run" / "images"
        manga_dir = mdir

    stages._make_cover(_Ctx())  # type: ignore[arg-type]
    return cid


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("import-chapter")
    i.add_argument("--title", required=True); i.add_argument("--number", type=float, default=1)
    i.add_argument("--chapter-title", default="")
    i.add_argument("--images", type=Path, required=True); i.add_argument("--run", type=Path, required=True)
    i.add_argument("--bundle", type=Path, required=True)
    i.add_argument("--voices", type=Path, default=config.ROOT / "spike" / "package" / "voices.json")
    a = ap.parse_args()
    cid = import_chapter(a.title, a.number, a.images, a.run, a.bundle, a.voices, a.chapter_title)
    print(f"imported as chapter {cid} in {config.LIBRARY}")


if __name__ == "__main__":
    main()
