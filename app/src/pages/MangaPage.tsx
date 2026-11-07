import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, STAGE_LABEL, type MangaDetail } from "../api";
import { AddChapter } from "../components/AddChapter";
import { ConfirmDialog, ProgressBar, StatusBadge } from "../components/ui";
import type { Chapter } from "../types";

const ACTIVE = new Set(["uploading", "queued", "processing"]);

function ChapterRow({ c, onChange, onDelete }: { c: Chapter; onChange: () => void; onDelete: (c: Chapter) => void }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const label = c.number != null ? `Chapter ${c.number}` : "Chapter";

  async function act(fn: () => Promise<unknown>) {
    setBusy(true);
    setErr(null);
    try {
      await fn();
      onChange();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className="chapter">
      <div className="ch-head">
        <div>
          <strong>{label}</strong>
          {c.title && <span className="ch-title"> — {c.title}</span>}
          <div className="muted">
            {c.page_count > 0 ? `${c.page_count} pages` : ""}
            {c.cost_usd > 0 ? ` · Claude usage ≈ $${c.cost_usd.toFixed(2)} at list price (not a charge on a subscription)` : ""}
          </div>
        </div>
        <StatusBadge status={c.status} />
      </div>

      {(c.status === "processing" || c.status === "queued") && (
        <div aria-live="polite">
          <ProgressBar value={c.progress} label={`${label} progress`} />
          <p className="muted">
            {c.status === "queued" ? "Waiting for its turn…" : `${c.stage ? (STAGE_LABEL[c.stage] ?? c.stage) : "Starting"}${c.detail && c.detail !== c.stage ? ` — ${c.detail}` : ""}`}
            {c.status === "processing" && ` (${Math.round(c.progress * 100)}%)`}
          </p>
        </div>
      )}
      {c.status === "uploading" && <p className="muted">The upload did not finish. Delete this and add the chapter again.</p>}
      {c.status === "failed" && (
        <p className="notice err" role="alert">
          {c.error ?? "Processing failed."} Finished steps are kept, so Retry continues from where it stopped.
        </p>
      )}
      {err && (
        <p className="notice err" role="alert">
          {err}
        </p>
      )}

      <div className="ch-actions">
        {c.status === "ready" && (
          <Link className="btn primary" to={`/read/${c.id}`}>
            Read
          </Link>
        )}
        {(c.status === "queued" || c.status === "processing") && (
          <button className="btn" disabled={busy} onClick={() => void act(() => api.cancelChapter(c.id))}>
            Cancel
          </button>
        )}
        {(c.status === "failed" || c.status === "cancelled") && (
          <button className="btn primary" disabled={busy} onClick={() => void act(() => api.retryChapter(c.id))}>
            Retry
          </button>
        )}
        <button className="btn danger-quiet" disabled={busy} onClick={() => onDelete(c)}>
          Delete
        </button>
      </div>
    </li>
  );
}

export function MangaPage() {
  const { mangaId } = useParams();
  const id = Number(mangaId);
  const nav = useNavigate();
  const [data, setData] = useState<MangaDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [delChapter, setDelChapter] = useState<Chapter | null>(null);
  const [delManga, setDelManga] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");

  const load = useCallback(async () => {
    try {
      setData(await api.getManga(id));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  // poll while anything is moving through the queue
  const active = data?.chapters.some((c) => ACTIVE.has(c.status)) ?? false;
  useEffect(() => {
    if (!active) return;
    const t = window.setInterval(() => void load(), 2000);
    return () => window.clearInterval(t);
  }, [active, load]);

  async function removeChapter() {
    if (!delChapter) return;
    setDeleting(true);
    try {
      await api.deleteChapter(delChapter.id);
    } catch (e) {
      setError((e as Error).message);
    }
    setDeleting(false);
    setDelChapter(null);
    await load();
  }

  async function removeManga() {
    setDeleting(true);
    try {
      await api.deleteManga(id);
      nav("/");
    } catch (e) {
      setError((e as Error).message);
      setDeleting(false);
      setDelManga(false);
    }
  }

  async function rename() {
    if (!draft.trim()) return;
    try {
      await api.renameManga(id, draft);
      setEditing(false);
      await load();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  if (error && !data) {
    return (
      <main className="page">
        <Link to="/">← Library</Link>
        <p className="notice err" role="alert">
          {error}
        </p>
      </main>
    );
  }
  if (!data) {
    return (
      <main className="page">
        <p className="muted">Loading…</p>
      </main>
    );
  }

  const nextNumber = data.chapters.reduce((m, c) => Math.max(m, c.number ?? 0), 0) + 1;

  return (
    <main className="page">
      <Link to="/" className="back">
        ← Library
      </Link>
      <header className="manga-head">
        {editing ? (
          <form
            className="inline-form"
            onSubmit={(e) => {
              e.preventDefault();
              void rename();
            }}
          >
            <input value={draft} onChange={(e) => setDraft(e.target.value)} maxLength={200} aria-label="Manga title" autoFocus />
            <button className="btn primary">Save</button>
            <button type="button" className="btn" onClick={() => setEditing(false)}>
              Cancel
            </button>
          </form>
        ) : (
          <>
            <h1>{data.manga.title}</h1>
            <button
              className="btn"
              onClick={() => {
                setDraft(data.manga.title);
                setEditing(true);
              }}
            >
              Rename
            </button>
            <button className="btn danger-quiet" onClick={() => setDelManga(true)}>
              Delete manga
            </button>
          </>
        )}
      </header>

      {error && (
        <p className="notice err" role="alert">
          {error}
        </p>
      )}

      <h2>Chapters</h2>
      {data.chapters.length === 0 ? (
        <p className="empty">No chapters yet. Add the first one below.</p>
      ) : (
        <ul className="chapters">
          {data.chapters.map((c) => (
            <ChapterRow key={c.id} c={c} onChange={() => void load()} onDelete={setDelChapter} />
          ))}
        </ul>
      )}

      <AddChapter mangaId={id} nextNumber={nextNumber} onAdded={() => void load()} />

      {delChapter && (
        <ConfirmDialog
          title={`Delete chapter ${delChapter.number ?? ""}?`}
          confirmLabel="Delete chapter"
          busy={deleting}
          onConfirm={() => void removeChapter()}
          onCancel={() => setDelChapter(null)}
        >
          <p>
            This removes the pages, the voices and your reading position for this chapter.
            {ACTIVE.has(delChapter.status) ? " Its processing is stopped first." : ""} This cannot be undone.
          </p>
        </ConfirmDialog>
      )}
      {delManga && (
        <ConfirmDialog
          title={`Delete “${data.manga.title}”?`}
          confirmLabel="Delete manga"
          busy={deleting}
          onConfirm={() => void removeManga()}
          onCancel={() => setDelManga(false)}
        >
          <p>
            This removes all {data.chapters.length} chapter{data.chapters.length === 1 ? "" : "s"}, their voices and your reading positions. Anything still
            processing is stopped. This cannot be undone.
          </p>
        </ConfirmDialog>
      )}
    </main>
  );
}
