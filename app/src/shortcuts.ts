/**
 * Keyboard shortcuts for the reader, as a pure function so the rules can be tested.
 * They matter most when the control panel is hidden, because the buttons are then out of reach.
 *
 *   Space  play / pause        F  full screen        H  hide or show the control panel
 *   Left   previous line       Right  next line
 */
export type ShortcutAction = "toggle-play" | "fullscreen" | "toggle-panel" | "prev" | "next";

/** What the key was pressed on: typing contexts keep all their keys; buttons keep Space/Enter. */
export type TargetKind = "typing" | "button" | "other";

export interface KeyInfo {
  key: string;
  ctrlKey: boolean;
  metaKey: boolean;
  altKey: boolean;
  repeat: boolean;
}

export function shortcutFor(k: KeyInfo, ctx: { targetKind: TargetKind; dialogOpen: boolean }): ShortcutAction | null {
  if (k.ctrlKey || k.metaKey || k.altKey) return null; // never steal browser shortcuts (Ctrl+F, Alt+Left ...)
  if (k.repeat) return null; // holding a key must not flip a toggle back and forth
  if (ctx.dialogOpen) return null; // the dialog owns the keyboard
  if (ctx.targetKind === "typing") return null; // inputs, selects and the volume slider use their own keys

  switch (k.key) {
    case " ":
      // on a focused button, Space already clicks it: do not also toggle playback
      return ctx.targetKind === "button" ? null : "toggle-play";
    case "f":
    case "F":
      return "fullscreen";
    case "h":
    case "H":
      return "toggle-panel";
    case "ArrowLeft":
      return "prev";
    case "ArrowRight":
      return "next";
    default:
      return null;
  }
}

/** Classify an event target. `closest` is used so a click on a button's inner span still counts as the button. */
export function targetKindOf(el: Element | null): TargetKind {
  if (!el || typeof el.closest !== "function") return "other";
  if (el.closest("input, select, textarea, [contenteditable='true']")) return "typing";
  if (el.closest("button, a")) return "button";
  return "other";
}
