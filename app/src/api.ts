import type { Chapter, ContinueInfo, MangaSummary, ReadingState, SaveState } from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function errorText(res: Response): Promise<string> {
  try {
    const j = (await res.json()) as { detail?: unknown };
    if (typeof j.detail === "string") return j.detail;
    if (Array.isArray(j.detail)) return j.detail.map((d) => (d as { msg?: string }).msg ?? "invalid").join("; ");
  } catch {
    /* not JSON */
  }
  return `HTTP ${res.status}`;
}

async function request<T>(method: string, url: string, body?: unknown, keepalive = false): Promise<T> {
  const res = await fetch(url, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    keepalive,
  });
  if (!res.ok) throw new ApiError(res.status, await errorText(res));
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export interface MangaDetail {
  manga: { id: number; title: string };
  chapters: Chapter[];
}

export const api = {
  listManga: () => request<{ manga: MangaSummary[]; continue: ContinueInfo | null }>("GET", "/api/manga"),
  createManga: (title: string) => request<MangaSummary>("POST", "/api/manga", { title }),
  getManga: (id: number) => request<MangaDetail>("GET", `/api/manga/${id}`),
  renameManga: (id: number, title: string) => request<MangaSummary>("PATCH", `/api/manga/${id}`, { title }),
  deleteManga: (id: number) => request<void>("DELETE", `/api/manga/${id}`),

  createChapter: (mangaId: number, body: { title: string; number: number | null }) =>
    request<Chapter>("POST", `/api/manga/${mangaId}/chapters`, body),
  finalize: (id: number) => request<Chapter>("POST", `/api/chapters/${id}/finalize`),
  getChapter: (id: number) => request<Chapter>("GET", `/api/chapters/${id}`),
  deleteChapter: (id: number) => request<void>("DELETE", `/api/chapters/${id}`),
  cancelChapter: (id: number) => request<Chapter>("POST", `/api/chapters/${id}/cancel`),
  retryChapter: (id: number) => request<Chapter>("POST", `/api/chapters/${id}/retry`),

  getReadingState: (id: number) => request<ReadingState | null>("GET", `/api/chapters/${id}/reading-state`),
  // keepalive lets the last save finish even while the tab is closing
  putReadingState: (id: number, s: SaveState) => request<{ ok: boolean }>("PUT", `/api/chapters/${id}/reading-state`, s, true),
};

/** Upload one page as raw bytes (the server sniffs the file type and picks the stored name). */
export function uploadPage(
  chapterId: number,
  n: number,
  file: File,
  onBytes: (loaded: number) => void,
  signal: AbortSignal,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", `/api/chapters/${chapterId}/pages/${n}`);
    xhr.setRequestHeader("Content-Type", "application/octet-stream");
    xhr.upload.onprogress = (e) => onBytes(e.loaded);
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) return resolve();
      let msg = `HTTP ${xhr.status}`;
      try {
        const d = (JSON.parse(xhr.responseText) as { detail?: string }).detail;
        if (d) msg = d;
      } catch {
        /* not JSON */
      }
      reject(new ApiError(xhr.status, msg));
    };
    xhr.onerror = () => reject(new ApiError(0, "network error"));
    xhr.onabort = () => reject(new DOMException("aborted", "AbortError"));
    signal.addEventListener("abort", () => xhr.abort(), { once: true });
    xhr.send(file);
  });
}

const IMAGE_RE = /\.(png|jpe?g|webp)$/i;

/** Keep the images of a chosen folder, in natural order (2 before 10), as a person would read them. */
export function pickImages(files: FileList | File[]): File[] {
  const path = (f: File) => (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name;
  return Array.from(files)
    .filter((f) => IMAGE_RE.test(f.name))
    .sort((a, b) => path(a).localeCompare(path(b), undefined, { numeric: true, sensitivity: "base" }));
}

export const formatBytes = (n: number) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1e3))} KB`);

export const STAGE_LABEL: Record<string, string> = {
  ingest: "Preparing pages",
  detect: "Finding speech bubbles",
  ocr: "Reading the text",
  fuse: "Organising the text",
  packets: "Cutting the scenes",
  cast: "Identifying the characters",
  direct: "Directing who speaks",
  voices: "Choosing voices",
  package: "Recording the audio",
};
