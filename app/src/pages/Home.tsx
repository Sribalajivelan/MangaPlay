import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { ConfirmDialog } from "../components/ui";
import type { ContinueInfo, MangaSummary } from "../types";

export function Home() {
  const nav = useNavigate();
  const [manga, setManga] = useState<MangaSummary[] | null>(null);
  const [cont, setCont] = useState<ContinueInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [creating, setCreating] = useState(false);
  const [confirm, setConfirm] = useState<MangaSummary | null>(null);
  const [deleting, setDeleting] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await api.listManga();
      setManga(r.manga);
      setCont(r.continue);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // keep the counts fresh while anything is being processed
  const anyBusy = manga?.some((m) => m.processing > 0) ?? false;
  useEffect(() => {
    if (!anyBusy) return;
    const t = window.setInterval(() => void load(), 4000);
    return () => window.clearInterval(t);
  }, [anyBusy, load]);

  async function create(e: FormEvent) {
    e.preventDefault();
    if (!title.trim()) return;
    setCreating(true);
    try {
      const m = await api.createManga(title);
      setTitle("");
      nav(`/manga/${m.id}`); // straight to "add the first chapter"
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setCreating(false);
    }
  }

  async function remove() {
    if (!confirm) return;
    setDeleting(true);
    try {
      await api.deleteManga(confirm.id);
      setConfirm(null);
      await load();
    } catch (err) {
      setError((err as Error).message);
      setConfirm(null);
    } finally {
      setDeleting(false);
    }
  }

  return (
    <main className="page">
      <header className="home-header">
        <h1>MangaPlay</h1>
        <p className="muted">Your manga &amp; webtoon library</p>
      </header>

      {error && (
        <p className="notice err" role="alert">
          {error}
        </p>
      )}

      {cont && (
        <Link className="continue" to={`/read/${cont.id}`}>
          <span className="continue-label">Continue reading</span>
          <strong>{cont.manga_title}</strong>
          <span>{cont.number != null ? `Chapter ${cont.number}` : cont.title}</span>
        </Link>
      )}

      <form className="inline-form" onSubmit={create}>
        <label>
          <span className="sr">New manga title</span>
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="New manga title" maxLength={200} />
        </label>
        <button className="btn primary" disabled={creating || !title.trim()}>
          Create manga
        </button>
      </form>

      {manga === null && !error && <p className="muted">Loading…</p>}
      {manga?.length === 0 && (
        <p className="empty">
          No manga yet. Give your first one a title above, then add a chapter by choosing the folder with its images.
        </p>
      )}

      <ul className="grid">
        {manga?.map((m) => (
          <li key={m.id} className="card">
            <Link to={`/manga/${m.id}`} className="card-main" aria-label={`Open ${m.title}`}>
              <div className="cover">
                <img src={`/api/manga/${m.id}/cover`} alt="" loading="lazy" onError={(e) => (e.currentTarget.style.display = "none")} />
                <span className="cover-fallback" aria-hidden="true">
                  {m.title.slice(0, 1).toUpperCase()}
                </span>
              </div>
              <strong className="card-title">{m.title}</strong>
              <span className="muted">
                {m.chapters === 0 ? "No chapters yet" : `${m.chapters} chapter${m.chapters === 1 ? "" : "s"} · ${m.ready} ready`}
                {m.processing > 0 && ` · ${m.processing} processing`}
              </span>
            </Link>
            <div className="card-actions">
              {m.first_ready_chapter != null && (
                <Link className="btn" to={`/read/${m.first_ready_chapter}`}>
                  Read
                </Link>
              )}
              <button className="btn danger-quiet" onClick={() => setConfirm(m)}>
                Delete
              </button>
            </div>
          </li>
        ))}
      </ul>

      {confirm && (
        <ConfirmDialog title={`Delete “${confirm.title}”?`} confirmLabel="Delete manga" busy={deleting} onConfirm={() => void remove()} onCancel={() => setConfirm(null)}>
          <p>
            This removes the manga with {confirm.chapters} chapter{confirm.chapters === 1 ? "" : "s"}, their voices and your reading position. Anything still
            processing is stopped. This cannot be undone.
          </p>
        </ConfirmDialog>
      )}
    </main>
  );
}
