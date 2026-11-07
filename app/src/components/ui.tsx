import { useEffect, useRef, type ReactNode } from "react";
import type { ChapterStatus } from "../types";

const LABELS: Record<ChapterStatus, string> = {
  uploading: "Uploading",
  queued: "In the queue",
  processing: "Processing",
  ready: "Ready to read",
  failed: "Failed",
  cancelled: "Cancelled",
};

/** Colour is never the only signal: the label says it too. */
export function StatusBadge({ status }: { status: ChapterStatus }) {
  return (
    <span className="badge-status" data-status={status}>
      {LABELS[status]}
    </span>
  );
}

export function ProgressBar({ value, label }: { value: number; label: string }) {
  const pct = Math.round(Math.max(0, Math.min(1, value)) * 100);
  return (
    <div className="progress" role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}>
      <div className="progress-fill" style={{ width: `${pct}%` }} />
    </div>
  );
}

interface ConfirmProps {
  title: string;
  children: ReactNode;
  confirmLabel: string;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

/** In-page confirmation for destructive actions (focus starts on the safe choice; Escape cancels). */
export function ConfirmDialog({ title, children, confirmLabel, busy, onConfirm, onCancel }: ConfirmProps) {
  const cancelRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    cancelRef.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && !busy && onCancel();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel, busy]);
  return (
    <div className="dialog-backdrop" onClick={() => !busy && onCancel()}>
      <div className="dialog" role="alertdialog" aria-modal="true" aria-label={title} onClick={(e) => e.stopPropagation()}>
        <h2>{title}</h2>
        <div className="dialog-body">{children}</div>
        <div className="dialog-actions">
          <button ref={cancelRef} className="btn" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
          <button className="btn danger" onClick={onConfirm} disabled={busy}>
            {busy ? "Deleting…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
