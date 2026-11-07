import type { Status } from "../engine/player";

interface Props {
  status: Status;
  busy: string | null;
  fsSupported: boolean;
  fsActive: boolean;
  onToggle: () => void;
  onPrev: () => void;
  onNext: () => void;
  onFullscreen: () => void;
  onShowPanel: () => void;
}

/** What is left on screen when the bottom panel is hidden: just enough to keep control. */
export function MiniBar(p: Props) {
  const label = p.status === "playing" ? "Pause" : p.status === "paused" ? "Resume" : p.status === "ended" ? "Replay" : "Play";
  return (
    <div className="minibar" role="toolbar" aria-label="Playback controls (compact)">
      {p.busy && (
        <span className="minibar-busy" role="status">
          {p.busy}
        </span>
      )}
      <button onClick={p.onPrev} aria-label="Previous line" title="Previous line (Left arrow)">
        ⏮
      </button>
      <button id="mini-play" className="primary" onClick={p.onToggle} aria-label={label} title={`${label} (Space)`}>
        {p.status === "playing" ? "⏸" : "▶"}
      </button>
      <button onClick={p.onNext} aria-label="Next line" title="Next line (Right arrow)">
        ⏭
      </button>
      {p.fsSupported && (
        <button onClick={p.onFullscreen} aria-pressed={p.fsActive} aria-label={p.fsActive ? "Exit full screen" : "Full screen"} title="Full screen (F)">
          ⛶
        </button>
      )}
      <button id="mini-show" onClick={p.onShowPanel} aria-label="Show the control panel" title="Show the control panel (H)">
        ▲
      </button>
    </div>
  );
}
