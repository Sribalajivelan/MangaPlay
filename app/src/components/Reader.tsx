import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { Box, ReadingState, SaveState, Script } from "../types";
import { Player, type Frame, type Status } from "../engine/player";
import { DEFAULT_OPTIONS } from "../engine/timeline";
import { Controls } from "./Controls";
import { SpeakerPicker } from "./SpeakerPicker";
import { MiniBar } from "./MiniBar";
import { useFullscreen, usePersistentFlag } from "../hooks";
import { shortcutFor, targetKindOf } from "../shortcuts";

const pct = (v: number, total: number) => `${(v / total) * 100}%`;

function boxStyle(b: Box, w: number, h: number) {
  return { left: pct(b[0], w), top: pct(b[1], h), width: pct(b[2] - b[0], w), height: pct(b[3] - b[1], h) };
}

interface ReaderProps {
  script: Script;
  baseUrl: string;
  chapterId: number;
  /** where the reader left off last time (null on a first read) */
  saved: ReadingState | null;
  /** called with the current position and settings; the page decides when to send it to the server */
  onSave: (s: SaveState) => void;
}

export function Reader({ script: initial, baseUrl, chapterId, saved, onSave }: ReaderProps) {
  const [script, setScript] = useState(initial);
  const scrollerRef = useRef<HTMLDivElement>(null);
  const stripRef = useRef<HTMLDivElement>(null);
  const scale = useRef(1);
  const restored = useRef(false);

  const [status, setStatus] = useState<Status>("idle");
  const [active, setActive] = useState(-1); // voiced index being spoken
  const [lastActive, setLastActive] = useState(-1); // keeps the caption up between lines
  const [rate, setRate] = useState(saved?.rate ?? 1);
  const [pace, setPace] = useState<number>(saved?.pace ?? DEFAULT_OPTIONS.travelPxPerSec);
  const [expressive, setExpressive] = useState(saved?.expressive == null ? true : !!saved.expressive);
  const [volume, setVolume] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const fs = useFullscreen();
  const [panelHidden, setPanelHiddenFlag] = usePersistentFlag("mr.panelHidden", false);
  // moving focus keeps keyboard and screen-reader users oriented when the button they used disappears
  const setPanelHidden = useCallback(
    (hidden: boolean) => {
      setPanelHiddenFlag(hidden);
      window.requestAnimationFrame(() => document.getElementById(hidden ? "mini-show" : "ctl-play")?.focus());
    },
    [setPanelHiddenFlag],
  );

  const player = useMemo(() => {
    const p = new Player(script, baseUrl, {
      onFrame: (f: Frame) => {
        const el = scrollerRef.current;
        if (el) el.scrollTop = f.y * scale.current;
        setActive(f.active);
        if (f.active >= 0) setLastActive(f.active);
      },
      onStatus: setStatus,
      onError: setError,
    });
    // saved settings go in before anything plays; the scroll position is restored once the strip is measured
    p.rate = saved?.rate ?? 1;
    p.pace = saved?.pace ?? DEFAULT_OPTIONS.travelPxPerSec;
    if (saved?.expressive === 0) void p.setExpressive(false);
    if (saved) p.setCameraY(saved.y);
    return p;
    // created once per bundle; corrections swap the script in through player.updateScript
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [baseUrl]);
  useEffect(() => () => player.dispose(), [player]);

  // keep display scale and the player's viewport height (in strip px) current
  useLayoutEffect(() => {
    const measure = () => {
      const strip = stripRef.current;
      const scroller = scrollerRef.current;
      if (!strip || !scroller) return;
      scale.current = strip.clientWidth / script.strip.width;
      player.viewH = scroller.clientHeight / scale.current;
      if (player.status !== "playing") player.setCameraY(scroller.scrollTop / scale.current);
    };
    measure();
    if (!restored.current) {
      restored.current = true;
      const el = scrollerRef.current;
      if (el && saved && saved.y > 0) el.scrollTop = saved.y * scale.current;
    }
    const ro = new ResizeObserver(measure);
    if (stripRef.current) ro.observe(stripRef.current);
    if (scrollerRef.current) ro.observe(scrollerRef.current);
    return () => ro.disconnect();
  }, [player, script.strip.width]);

  // If the reader grabs the scroll position, auto-scroll steps aside (and resumes from where they are).
  useEffect(() => {
    const el = scrollerRef.current;
    if (!el) return;
    const intervene = () => {
      if (player.status === "playing") player.pause();
    };
    const onScroll = () => {
      if (player.status !== "playing") player.setCameraY(el.scrollTop / scale.current);
    };
    el.addEventListener("wheel", intervene, { passive: true });
    el.addEventListener("touchmove", intervene, { passive: true });
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      el.removeEventListener("wheel", intervene);
      el.removeEventListener("touchmove", intervene);
      el.removeEventListener("scroll", onScroll);
    };
  }, [player]);

  const shownRef = useRef(-1);
  const settingsRef = useRef({ rate, pace, expressive });
  const saveNow = useCallback(() => {
    const i = shownRef.current;
    const beat = i >= 0 && player.voiced[i] ? script.beats[player.voiced[i].beatIndex] : null;
    onSave({ beat_id: beat?.id ?? null, y: Math.max(0, Math.round(player.currentY)), ...settingsRef.current });
  }, [player, script, onSave]);

  useEffect(() => {
    settingsRef.current = { rate, pace, expressive };
    saveNow(); // a changed setting is saved right away
  }, [rate, pace, expressive, saveNow]);

  useEffect(() => {
    if (status === "playing") {
      const t = window.setInterval(saveNow, 5000);
      return () => window.clearInterval(t);
    }
    saveNow(); // paused, ended or idle: a good moment to save
  }, [status, saveNow]);

  useEffect(() => {
    const el = scrollerRef.current;
    if (!el) return;
    let t = 0;
    const onScrollEnd = () => {
      window.clearTimeout(t);
      t = window.setTimeout(() => player.status !== "playing" && saveNow(), 800);
    };
    const leaving = () => saveNow();
    el.addEventListener("scroll", onScrollEnd, { passive: true });
    window.addEventListener("pagehide", leaving);
    document.addEventListener("visibilitychange", leaving);
    return () => {
      window.clearTimeout(t);
      el.removeEventListener("scroll", onScrollEnd);
      window.removeEventListener("pagehide", leaving);
      document.removeEventListener("visibilitychange", leaving);
      saveNow(); // leaving the page inside the app
    };
  }, [player, saveNow]);

  const playFrom = useCallback((i: number) => void player.playFrom(i), [player]);

  const onToggle = useCallback(() => {
    setError(null);
    if (player.status === "playing") player.pause();
    else if (player.status === "paused") {
      // the reader may have scrolled while paused: continue from where they are, not from the old spot
      void player.playFrom(player.nearestIndex());
    } else void player.resume();
  }, [player]);

  const step = useCallback(
    (d: number) => void player.playFrom(player.currentVoicedIndex() + d),
    [player],
  );

  const onRate = useCallback(
    (r: number) => {
      setRate(r);
      void player.setRate(r);
    },
    [player],
  );

  const onPace = useCallback(
    (p: number) => {
      setPace(p);
      void player.setPace(p);
    },
    [player],
  );

  const onExpressive = useCallback(
    (on: boolean) => {
      setExpressive(on);
      void player.setExpressive(on);
    },
    [player],
  );

  const onVolume = useCallback(
    (v: number) => {
      setVolume(v);
      player.setVolume(v);
    },
    [player],
  );

  const applyCorrection = useCallback(
    async (beatId: string, payload: { speaker?: string; muted?: boolean; reset?: boolean }) => {
      setPickerOpen(false);
      player.pause();
      setBusy("Re-rendering this line's voice…");
      setError(null);
      try {
        const res = await fetch(`/api/chapters/${chapterId}/override`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ beat: beatId, ...payload }),
        });
        if (!res.ok) {
          const detail = ((await res.json().catch(() => ({}))) as { detail?: string }).detail;
          throw new Error(detail ?? `HTTP ${res.status}`);
        }
        const fresh = (await (await fetch(`${baseUrl}script.json?ts=${Date.now()}`, { cache: "no-store" })).json()) as Script;
        player.updateScript(fresh, [beatId]);
        setScript(fresh);
        const idx = player.indexOfBeat(beatId);
        setLastActive(idx);
        // hear the result straight away (a muted line has no index: just stay put)
        if (idx >= 0) await player.playFrom(idx);
      } catch (e) {
        setError(`Could not save the correction: ${(e as Error).message}`);
      } finally {
        setBusy(null);
      }
    },
    [player, chapterId, baseUrl],
  );

  // keyboard: Space, F, H, Left/Right (rules and their tests live in shortcuts.ts)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const action = shortcutFor(e, { targetKind: targetKindOf(e.target as Element | null), dialogOpen: pickerOpen });
      if (!action) return;
      e.preventDefault();
      if (action === "toggle-play") onToggle();
      else if (action === "fullscreen") void fs.toggle();
      else if (action === "toggle-panel") setPanelHidden(!panelHidden);
      else step(action === "prev" ? -1 : 1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [pickerOpen, onToggle, step, fs, panelHidden, setPanelHidden]);

  // leaving the reader must not leave the whole app stuck in full screen
  useEffect(() => fs.exit, [fs.exit]);

  const { width: W, height: H } = script.strip;
  const castName = useMemo(() => new Map(script.cast.map((c) => [c.id, c.name])), [script.cast]);
  const shown = active >= 0 ? active : lastActive;
  shownRef.current = shown;
  const shownBeat = shown >= 0 ? script.beats[player.voiced[shown].beatIndex] : null;
  const activeBeat = active >= 0 ? script.beats[player.voiced[active].beatIndex] : null;

  return (
    <div className={panelHidden ? "reader panel-hidden" : "reader"}>
      <div className="scroller" ref={scrollerRef}>
        <div className="strip" ref={stripRef} style={{ aspectRatio: `${W} / ${H}` }}>
          {script.strip.slices.map((s) => (
            <img
              key={s.file}
              className="slice"
              src={baseUrl + s.file}
              width={W}
              height={s.h}
              loading="lazy"
              decoding="async"
              alt=""
              draggable={false}
            />
          ))}
          {player.voiced.map((v, i) => {
            const b = script.beats[v.beatIndex];
            return (
              <button
                key={b.id}
                className="hit"
                style={boxStyle(b.bubble, W, H)}
                onClick={() => playFrom(i)}
                aria-label={`Play from: ${b.tts_text.slice(0, 60)}`}
                tabIndex={-1}
              />
            );
          })}
          {activeBeat && <div className="highlight" style={boxStyle(activeBeat.bubble, W, H)} />}
        </div>
      </div>

      {error && (
        <div className="toast" role="alert">
          {error}
        </div>
      )}

      {pickerOpen && shownBeat && (
        <SpeakerPicker
          cast={script.cast}
          current={shownBeat.speaker}
          text={shownBeat.tts_text}
          corrected={shownBeat.override?.by === "user"}
          onPick={(speaker) => void applyCorrection(shownBeat.id, { speaker })}
          onMute={() => void applyCorrection(shownBeat.id, { muted: true })}
          onReset={() => void applyCorrection(shownBeat.id, { reset: true })}
          onClose={() => setPickerOpen(false)}
        />
      )}

      {panelHidden ? (
        <MiniBar
          status={status}
          busy={busy}
          fsSupported={fs.supported}
          fsActive={fs.active}
          onToggle={onToggle}
          onPrev={() => step(-1)}
          onNext={() => step(1)}
          onFullscreen={() => void fs.toggle()}
          onShowPanel={() => setPanelHidden(false)}
        />
      ) : (
      <Controls
        fsSupported={fs.supported}
        fsActive={fs.active}
        onFullscreen={() => void fs.toggle()}
        onHidePanel={() => setPanelHidden(true)}
        expressive={expressive}
        hasExpressive={script.beats.some((b) => !!b.audio_x)}
        onExpressive={onExpressive}
        canCorrect={!!shownBeat}
        busy={busy}
        corrections={script.beats.filter((b) => b.override?.by === "user").length}
        onWrongVoice={() => {
          player.pause();
          setPickerOpen(true);
        }}
        status={status}
        rate={rate}
        pace={pace}
        onPace={onPace}
        volume={volume}
        index={shown}
        total={player.voiced.length}
        caption={shownBeat?.tts_text ?? ""}
        speaker={shownBeat ? (castName.get(shownBeat.speaker) ?? shownBeat.speaker) : ""}
        source={shownBeat?.source ?? null}
        onToggle={onToggle}
        onPrev={() => step(-1)}
        onNext={() => step(1)}
        onRate={onRate}
        onVolume={onVolume}
      />
      )}
    </div>
  );
}
