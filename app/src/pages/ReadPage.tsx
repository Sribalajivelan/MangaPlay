import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { Reader } from "../components/Reader";
import type { Chapter, ReadingState, SaveState, Script } from "../types";

const SAVE_EVERY_MS = 1500;

export function ReadPage() {
  const { chapterId } = useParams();
  const id = Number(chapterId);
  const [chapter, setChapter] = useState<Chapter | null>(null);
  const [script, setScript] = useState<Script | null>(null);
  const [saved, setSaved] = useState<ReadingState | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setScript(null);
    setError(null);
    (async () => {
      try {
        const ch = await api.getChapter(id);
        if (ch.status !== "ready") throw new Error(`This chapter is not ready yet (${ch.status}).`);
        const [state, res] = await Promise.all([api.getReadingState(id), fetch(`/bundle/${id}/script.json`)]);
        if (!res.ok || !(res.headers.get("content-type") ?? "").includes("json")) throw new Error("The chapter's files are missing.");
        const s = (await res.json()) as Script;
        if (s.schema_version !== 1) throw new Error(`Unsupported bundle version ${s.schema_version}`);
        if (!cancelled) {
          setChapter(ch);
          setSaved(state);
          setScript(s);
        }
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id]);

  // Save the position without flooding the server: at most one request per interval, always sending the latest.
  const pending = useRef<SaveState | null>(null);
  const lastSent = useRef(0);
  const timer = useRef(0);
  const lastKey = useRef("");

  const flush = useCallback(() => {
    window.clearTimeout(timer.current);
    timer.current = 0;
    const s = pending.current;
    if (!s) return;
    pending.current = null;
    const key = `${s.beat_id}|${Math.round(s.y / 5)}|${s.rate}|${s.pace}|${s.expressive}`;
    if (key === lastKey.current) return; // nothing changed
    lastKey.current = key;
    lastSent.current = Date.now();
    void api.putReadingState(id, s).catch(() => {
      lastKey.current = ""; // try again next time
    });
  }, [id]);

  const onSave = useCallback(
    (s: SaveState) => {
      pending.current = s;
      const wait = SAVE_EVERY_MS - (Date.now() - lastSent.current);
      if (wait <= 0) flush();
      else if (!timer.current) timer.current = window.setTimeout(flush, wait);
    },
    [flush],
  );

  useEffect(() => flush, [flush]); // leaving the page sends whatever is pending

  if (error) {
    return (
      <main className="page">
        <Link to="/" className="back">
          ← Library
        </Link>
        <p className="notice err" role="alert">
          {error}
        </p>
      </main>
    );
  }
  if (!script || !chapter) {
    return (
      <main className="page">
        <p className="muted">Loading the chapter…</p>
      </main>
    );
  }

  return (
    <>
      <Link to={`/manga/${chapter.manga_id}`} className="reader-back" title="Back to the chapter list">
        ← Chapters
      </Link>
      <Reader key={id} script={script} baseUrl={`/bundle/${id}/`} chapterId={id} saved={saved} onSave={onSave} />
    </>
  );
}
