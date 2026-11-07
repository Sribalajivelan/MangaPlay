import { useRef, useState, type FormEvent } from "react";
import { api, formatBytes, pickImages, uploadPage } from "../api";
import { ProgressBar } from "./ui";

const MAX_PAGES = 400;
const MAX_PAGE_BYTES = 40 * 1024 * 1024;

interface Props {
  mangaId: number;
  nextNumber: number;
  onAdded: () => void;
}

/** Choose a folder of page images, upload them one by one, then hand the chapter to the processing queue. */
export function AddChapter({ mangaId, nextNumber, onAdded }: Props) {
  const folderInput = useRef<HTMLInputElement>(null);
  const filesInput = useRef<HTMLInputElement>(null);
  const abort = useRef<AbortController | null>(null);

  const [title, setTitle] = useState("");
  const [number, setNumber] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [ignored, setIgnored] = useState(0);
  const [phase, setPhase] = useState<"idle" | "uploading">("idle");
  const [done, setDone] = useState(0);
  const [partial, setPartial] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const totalBytes = files.reduce((n, f) => n + f.size, 0);
  const tooMany = files.length > MAX_PAGES;
  const tooBig = files.find((f) => f.size > MAX_PAGE_BYTES);
  const problem = tooMany ? `A chapter can have up to ${MAX_PAGES} pages.` : tooBig ? `${tooBig.name} is larger than ${formatBytes(MAX_PAGE_BYTES)}.` : null;

  function choose(list: FileList | null) {
    if (!list) return;
    const images = pickImages(list);
    setIgnored(list.length - images.length);
    setFiles(images);
    setError(null);
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!files.length || problem) return;
    setPhase("uploading");
    setDone(0);
    setError(null);
    const ctl = new AbortController();
    abort.current = ctl;
    let chapterId: number | null = null;
    let page = 0;
    try {
      const num = number.trim() === "" ? null : Number(number);
      if (num !== null && !(num >= 0)) throw new Error("Chapter number must be a number");
      const ch = await api.createChapter(mangaId, { title, number: num });
      chapterId = ch.id;
      for (const [i, f] of files.entries()) {
        page = i + 1;
        setPartial(0);
        // one retry per page: a flaky moment should not throw away a long upload
        for (let attempt = 1; ; attempt++) {
          try {
            await uploadPage(ch.id, page, f, setPartial, ctl.signal);
            break;
          } catch (err) {
            if ((err as Error).name === "AbortError" || attempt === 2) throw err;
          }
        }
        setDone(page);
      }
      await api.finalize(ch.id);
      setFiles([]);
      setTitle("");
      setNumber("");
      onAdded();
    } catch (err) {
      const cancelled = (err as Error).name === "AbortError";
      // never leave a half-uploaded chapter behind
      if (chapterId !== null) await api.deleteChapter(chapterId).catch(() => undefined);
      setError(cancelled ? "Upload cancelled." : `Upload stopped at page ${page || 1}: ${(err as Error).message}`);
      onAdded();
    } finally {
      abort.current = null;
      setPhase("idle");
    }
  }

  const uploading = phase === "uploading";
  const progress = files.length ? (done + (partial && files[done] ? Math.min(1, partial / files[done].size) : 0)) / files.length : 0;

  return (
    <section className="add-chapter" aria-labelledby="add-chapter-h">
      <h2 id="add-chapter-h">Add a chapter</h2>
      <form onSubmit={submit}>
        <div className="fields">
          <label>
            Chapter number
            <input type="number" min={0} step="any" value={number} onChange={(e) => setNumber(e.target.value)} placeholder={`${nextNumber}`} disabled={uploading} />
          </label>
          <label>
            Title <span className="muted">(optional)</span>
            <input value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} disabled={uploading} />
          </label>
        </div>

        <div className="pickers">
          <input
            ref={folderInput}
            type="file"
            className="sr"
            tabIndex={-1}
            // not in React's types, but supported by Chrome, Edge, Firefox and Safari
            {...({ webkitdirectory: "", directory: "" } as Record<string, string>)}
            multiple
            onChange={(e) => choose(e.target.files)}
          />
          <input ref={filesInput} type="file" className="sr" tabIndex={-1} accept="image/png,image/jpeg,image/webp" multiple onChange={(e) => choose(e.target.files)} />
          <button type="button" className="btn" onClick={() => folderInput.current?.click()} disabled={uploading}>
            Choose images folder…
          </button>
          <button type="button" className="btn" onClick={() => filesInput.current?.click()} disabled={uploading}>
            or choose image files…
          </button>
        </div>

        {files.length > 0 && (
          <p className="muted" aria-live="polite">
            {files.length} image{files.length === 1 ? "" : "s"} selected ({formatBytes(totalBytes)}), in the order {files[0].name} … {files[files.length - 1].name}
            {ignored > 0 && `. ${ignored} other file${ignored === 1 ? " was" : "s were"} ignored.`}
          </p>
        )}
        {problem && <p className="notice err">{problem}</p>}
        {error && (
          <p className="notice err" role="alert">
            {error}
          </p>
        )}

        {uploading && (
          <div aria-live="polite">
            <ProgressBar value={progress} label="Upload progress" />
            <p className="muted">
              Uploading page {Math.min(done + 1, files.length)} of {files.length}…{" "}
              <button type="button" className="link" onClick={() => abort.current?.abort()}>
                Cancel
              </button>
            </p>
          </div>
        )}

        <button className="btn primary" disabled={!files.length || !!problem || uploading}>
          {uploading ? "Uploading…" : "Add chapter and start processing"}
        </button>
      </form>
    </section>
  );
}
