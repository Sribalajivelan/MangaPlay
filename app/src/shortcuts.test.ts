import { describe, expect, it } from "vitest";
import { shortcutFor, targetKindOf, type KeyInfo } from "./shortcuts";

const key = (k: string, over: Partial<KeyInfo> = {}): KeyInfo => ({
  key: k,
  ctrlKey: false,
  metaKey: false,
  altKey: false,
  repeat: false,
  ...over,
});
const other = { targetKind: "other" as const, dialogOpen: false };

describe("shortcutFor", () => {
  it("maps the documented keys", () => {
    expect(shortcutFor(key(" "), other)).toBe("toggle-play");
    expect(shortcutFor(key("f"), other)).toBe("fullscreen");
    expect(shortcutFor(key("F"), other)).toBe("fullscreen");
    expect(shortcutFor(key("h"), other)).toBe("toggle-panel");
    expect(shortcutFor(key("H"), other)).toBe("toggle-panel");
    expect(shortcutFor(key("ArrowLeft"), other)).toBe("prev");
    expect(shortcutFor(key("ArrowRight"), other)).toBe("next");
  });

  it("ignores every other key", () => {
    for (const k of ["a", "Enter", "Escape", "ArrowUp", "ArrowDown", "Tab", "1"]) expect(shortcutFor(key(k), other)).toBeNull();
  });

  it("never steals browser shortcuts", () => {
    for (const mod of ["ctrlKey", "metaKey", "altKey"] as const) {
      expect(shortcutFor(key("f", { [mod]: true }), other)).toBeNull(); // Ctrl+F is find
      expect(shortcutFor(key("ArrowLeft", { [mod]: true }), other)).toBeNull(); // Alt+Left is back
    }
  });

  it("does not repeat a toggle while a key is held", () => {
    expect(shortcutFor(key("h", { repeat: true }), other)).toBeNull();
    expect(shortcutFor(key(" ", { repeat: true }), other)).toBeNull();
  });

  it("leaves typing contexts alone (inputs, selects, the volume slider)", () => {
    const typing = { targetKind: "typing" as const, dialogOpen: false };
    for (const k of [" ", "f", "h", "ArrowLeft", "ArrowRight"]) expect(shortcutFor(key(k), typing)).toBeNull();
  });

  it("lets a focused button keep Space, but still allows F, H and the arrows", () => {
    const button = { targetKind: "button" as const, dialogOpen: false };
    expect(shortcutFor(key(" "), button)).toBeNull(); // the button's own click handles it; no double toggle
    expect(shortcutFor(key("f"), button)).toBe("fullscreen");
    expect(shortcutFor(key("h"), button)).toBe("toggle-panel");
    expect(shortcutFor(key("ArrowRight"), button)).toBe("next");
  });

  it("is silent while a dialog is open", () => {
    const dialog = { targetKind: "other" as const, dialogOpen: true };
    for (const k of [" ", "f", "h", "ArrowLeft"]) expect(shortcutFor(key(k), dialog)).toBeNull();
  });
});

describe("targetKindOf", () => {
  const el = (closestTo: string | null) =>
    ({ closest: (sel: string) => (closestTo && sel.includes(closestTo) ? {} : null) }) as unknown as Element;

  it("classifies targets", () => {
    expect(targetKindOf(null)).toBe("other");
    expect(targetKindOf(el("input"))).toBe("typing");
    expect(targetKindOf(el("select"))).toBe("typing");
    expect(targetKindOf(el("button"))).toBe("button");
    expect(targetKindOf(el(null))).toBe("other");
  });

  it("prefers typing over button when both match", () => {
    const both = { closest: () => ({}) } as unknown as Element; // matches every selector
    expect(targetKindOf(both)).toBe("typing");
  });
});
