import { useCallback, useEffect, useState } from "react";

type FsDocument = Document & {
  webkitFullscreenEnabled?: boolean;
  webkitFullscreenElement?: Element | null;
  webkitExitFullscreen?: () => Promise<void> | void;
};
type FsElement = HTMLElement & { webkitRequestFullscreen?: () => Promise<void> | void };

const fsDoc = () => document as FsDocument;
const fsActive = () => !!(fsDoc().fullscreenElement ?? fsDoc().webkitFullscreenElement);

/**
 * Full screen for the whole page (so the dialogs and toasts stay inside it).
 * Not available everywhere (iPhone Safari has no page full screen): `supported` is false there and
 * the buttons are not shown. Entering needs a user gesture, so it can never start on its own.
 */
export function useFullscreen() {
  const supported = !!(fsDoc().fullscreenEnabled || fsDoc().webkitFullscreenEnabled);
  const [active, setActive] = useState(fsActive());

  useEffect(() => {
    const on = () => setActive(fsActive());
    document.addEventListener("fullscreenchange", on);
    document.addEventListener("webkitfullscreenchange", on);
    return () => {
      document.removeEventListener("fullscreenchange", on);
      document.removeEventListener("webkitfullscreenchange", on);
    };
  }, []);

  const toggle = useCallback(async () => {
    try {
      if (fsActive()) {
        await (fsDoc().exitFullscreen?.() ?? fsDoc().webkitExitFullscreen?.());
      } else {
        const el = document.documentElement as FsElement;
        await (el.requestFullscreen?.() ?? el.webkitRequestFullscreen?.());
      }
    } catch {
      /* refused by the browser (no gesture, or blocked): nothing useful to show */
    }
  }, []);

  const exit = useCallback(() => {
    if (fsActive()) void Promise.resolve(fsDoc().exitFullscreen?.() ?? fsDoc().webkitExitFullscreen?.()).catch(() => undefined);
  }, []);

  return { supported, active, toggle, exit };
}

/** A boolean remembered in localStorage. Storage can be blocked or full, so every access is guarded. */
export function usePersistentFlag(key: string, initial = false): [boolean, (v: boolean) => void] {
  const [value, setValue] = useState<boolean>(() => {
    try {
      const v = window.localStorage.getItem(key);
      return v === null ? initial : v === "1";
    } catch {
      return initial;
    }
  });
  const set = useCallback(
    (v: boolean) => {
      setValue(v);
      try {
        window.localStorage.setItem(key, v ? "1" : "0");
      } catch {
        /* not remembered; still works for this visit */
      }
    },
    [key],
  );
  return [value, set];
}
