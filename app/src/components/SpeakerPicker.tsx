import { useEffect, useRef } from "react";

interface Props {
  cast: { id: string; name: string }[];
  current: string;
  text: string;
  corrected: boolean;
  onPick: (speaker: string) => void;
  onMute: () => void;
  onReset: () => void;
  onClose: () => void;
}

const SPECIAL = [
  { id: "narrator", name: "Narrator" },
  { id: "system", name: "System window" },
  { id: "announcer", name: "Announcer" },
];

/** "Who really says this line?" Opens over the player; choosing re-renders just that line's voice. */
export function SpeakerPicker({ cast, current, text, corrected, onPick, onMute, onReset, onClose }: Props) {
  const first = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    first.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const characters = cast.filter((c) => !["narrator", "system", "announcer", "unknown"].includes(c.id));
  const options = [...characters, ...SPECIAL];

  return (
    <div className="picker-backdrop" onClick={onClose}>
      <div className="picker" role="dialog" aria-modal="true" aria-label="Choose who speaks this line" onClick={(e) => e.stopPropagation()}>
        <h2>Who says this?</h2>
        <p className="picker-line">“{text}”</p>
        <div className="picker-options">
          {options.map((o, i) => (
            <button
              key={o.id}
              ref={i === 0 ? first : undefined}
              className={o.id === current ? "chosen" : ""}
              onClick={() => onPick(o.id)}
              aria-pressed={o.id === current}
            >
              {o.name}
              {o.id === current && <span className="sr"> (current)</span>}
            </button>
          ))}
        </div>
        <div className="picker-actions">
          <button onClick={onMute}>Don’t read this line</button>
          {corrected && <button onClick={onReset}>Undo my correction</button>}
          <button onClick={onClose}>Cancel</button>
        </div>
      </div>
    </div>
  );
}
