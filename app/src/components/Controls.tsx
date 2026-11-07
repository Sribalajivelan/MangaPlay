import type { Status } from "../engine/player";

import { PACES } from "../engine/timeline";

interface Props {
  status: Status;
  rate: number;
  pace: number;
  onPace: (pxPerSec: number) => void;
  expressive: boolean;
  hasExpressive: boolean;
  onExpressive: (on: boolean) => void;
  canCorrect: boolean;
  busy: string | null;
  corrections: number;
  onWrongVoice: () => void;
  volume: number;
  index: number;
  total: number;
  caption: string;
  speaker: string;
  source: "directed" | "draft" | null;
  onToggle: () => void;
  onPrev: () => void;
  onNext: () => void;
  onRate: (r: number) => void;
  onVolume: (v: number) => void;
  fsSupported: boolean;
  fsActive: boolean;
  onFullscreen: () => void;
  onHidePanel: () => void;
}

const RATES = [0.75, 1, 1.25, 1.5, 2];

export function Controls(p: Props) {
  const label = p.status === "playing" ? "Pause" : p.status === "paused" ? "Resume" : p.status === "ended" ? "Replay" : "Play";
  return (
    <div className="controls" role="region" aria-label="Playback controls">
      {p.busy && <p className="busy" role="status">{p.busy}</p>}
      {p.corrections > 0 && <p className="muted">{p.corrections} correction{p.corrections === 1 ? "" : "s"} saved</p>}
      {p.caption && (
        <p className="caption" aria-live="polite">
          <span className="speaker">{p.speaker}</span>
          {p.source === "draft" && <span className="badge" title="Not yet reviewed by the Director agent">draft</span>}
          <span className="line">{p.caption}</span>
        </p>
      )}
      <div className="row">
        <button onClick={p.onPrev} aria-label="Previous line" disabled={p.index <= 0 && p.status === "idle"}>
          ⏮
        </button>
        <button id="ctl-play" className="primary" onClick={p.onToggle} aria-label={label} title={`${label} (Space)`}>
          {p.status === "playing" ? "⏸" : "▶"} <span className="lbl">{label}</span>
        </button>
        <button onClick={p.onNext} aria-label="Next line">
          ⏭
        </button>
        <span className="pos" aria-label="Position">
          {p.index >= 0 ? p.index + 1 : 0} / {p.total}
        </span>
        <label className="field">
          <span>Speed</span>
          <select value={p.rate} onChange={(e) => p.onRate(Number(e.target.value))}>
            {RATES.map((r) => (
              <option key={r} value={r}>
                {r}x
              </option>
            ))}
          </select>
        </label>
        <button onClick={p.onWrongVoice} disabled={!p.canCorrect || !!p.busy} title="Pick who really says the line shown above">
          Wrong voice?
        </button>
        {p.hasExpressive && (
          <label className="field" title="Expressive: voices adjusted for character age and emotion. Plain: the basic voices.">
            <span>Voice</span>
            <select value={p.expressive ? "x" : "p"} onChange={(e) => p.onExpressive(e.target.value === "x")}>
              <option value="x">Expressive</option>
              <option value="p">Plain</option>
            </select>
          </label>
        )}
        <label className="field" title="How fast the picture scrolls between spoken lines">
          <span>Scroll</span>
          <select value={p.pace} onChange={(e) => p.onPace(Number(e.target.value))}>
            {PACES.map((x) => (
              <option key={x.label} value={x.pxPerSec}>
                {x.label}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Vol</span>
          <input type="range" min={0} max={1} step={0.05} value={p.volume} onChange={(e) => p.onVolume(Number(e.target.value))} />
        </label>
        {p.fsSupported && (
          <button onClick={p.onFullscreen} aria-pressed={p.fsActive} title="Full screen (F)">
            {p.fsActive ? "Exit full screen" : "Full screen"}
          </button>
        )}
        <button onClick={p.onHidePanel} title="Hide this panel (H). Space, F, H and the arrow keys still work." aria-label="Hide the control panel">
          Hide panel ▾
        </button>
      </div>
    </div>
  );
}
