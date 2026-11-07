/**
 * Pure playback timeline. No DOM, no audio: given the voiced beats it computes WHEN each beat is
 * spoken and WHERE the camera is at any time. The audio clock drives it (see player.ts), so voice
 * and scroll cannot drift. All positions are in strip pixels; all times are milliseconds from the
 * start of this timeline, already divided by the playback rate.
 */

export interface VoicedBeat {
  id: string;
  /** vertical centre of the beat's text box, strip px */
  centerY: number;
  audioMs: number;
}

export interface TimelineOptions {
  /** playback speed multiplier, 1 = normal */
  rate: number;
  /** visible height expressed in strip px (viewport height / display scale) */
  viewH: number;
  stripH: number;
  /** fraction of the viewport height where the spoken bubble should sit, 0 = top, 1 = bottom */
  anchor: number;
  travelPxPerSec: number;
  minTravelMs: number;
  maxTravelMs: number;
  /** silence after each line, before the camera starts moving to the next */
  gapMs: number;
  /** camera position when the timeline starts */
  startY: number;
}

export const DEFAULT_OPTIONS: Omit<TimelineOptions, "viewH" | "stripH" | "startY"> = {
  rate: 1,
  anchor: 0.38,
  // About 3 s per screen of art, so the picture can actually be looked at while the camera moves.
  // (The first version crossed art at 650 px/s with a 3.6 s cap, i.e. 1400+ px/s over long stretches.)
  travelPxPerSec: 300,
  minTravelMs: 700,
  maxTravelMs: 30000,
  gapMs: 260,
};

/** Reader-facing choices for how fast the camera moves through art between spoken lines. */
export const PACES = [
  { label: "Slow", pxPerSec: 200 },
  { label: "Relaxed", pxPerSec: 300 },
  { label: "Normal", pxPerSec: 450 },
  { label: "Fast", pxPerSec: 800 },
] as const;

export interface Cue {
  /** index into the beats array passed to buildTimeline */
  index: number;
  id: string;
  travelStart: number;
  speakStart: number;
  speakEnd: number;
  fromY: number;
  toY: number;
}

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

/** smoothstep: gentle start and stop, so the scroll feels like a camera, not a conveyor */
export const ease = (t: number) => {
  const x = clamp(t, 0, 1);
  return x * x * (3 - 2 * x);
};

export function targetY(centerY: number, o: Pick<TimelineOptions, "viewH" | "stripH" | "anchor">): number {
  return clamp(centerY - o.viewH * o.anchor, 0, Math.max(0, o.stripH - o.viewH));
}

export function buildTimeline(beats: VoicedBeat[], o: TimelineOptions): Cue[] {
  const rate = o.rate > 0 ? o.rate : 1;
  const cues: Cue[] = [];
  let t = 0;
  let y = o.startY;
  beats.forEach((b, index) => {
    const toY = targetY(b.centerY, o);
    const dist = Math.abs(toY - y);
    const travel = dist < 1 ? 0 : clamp((dist / o.travelPxPerSec) * 1000, o.minTravelMs, o.maxTravelMs) / rate;
    const travelStart = t;
    const speakStart = travelStart + travel;
    const speakEnd = speakStart + b.audioMs / rate;
    cues.push({ index, id: b.id, travelStart, speakStart, speakEnd, fromY: y, toY });
    t = speakEnd + o.gapMs / rate;
    y = toY;
  });
  return cues;
}

/** Camera position at time t (ms). Holds still between a line ending and the next travel starting. */
export function cameraAt(cues: Cue[], t: number, startY: number): number {
  if (!cues.length) return startY;
  for (const c of cues) {
    if (t < c.travelStart) return c.fromY;
    if (t < c.speakStart) return c.fromY + (c.toY - c.fromY) * ease((t - c.travelStart) / (c.speakStart - c.travelStart));
    if (t < c.speakEnd) return c.toY;
  }
  return cues[cues.length - 1].toY;
}

/** Index (into `cues`) of the cue being spoken at time t, or -1 while travelling / in a gap. */
export function activeAt(cues: Cue[], t: number): number {
  for (let i = 0; i < cues.length; i++) {
    if (t >= cues[i].speakStart && t < cues[i].speakEnd) return i;
    if (t < cues[i].speakStart) return -1;
  }
  return -1;
}

/** Index of the cue to treat as "current": the one being spoken, else the next one to start. */
export function currentAt(cues: Cue[], t: number): number {
  for (let i = 0; i < cues.length; i++) if (t < cues[i].speakEnd) return i;
  return Math.max(0, cues.length - 1);
}

export function timelineEnd(cues: Cue[]): number {
  return cues.length ? cues[cues.length - 1].speakEnd : 0;
}

/** First voiced beat at or after the anchor line when the camera is at y (used to resume after manual scrolling). */
export function nearestBeatIndex(beats: VoicedBeat[], y: number, o: Pick<TimelineOptions, "viewH" | "anchor">): number {
  const line = y + o.viewH * o.anchor - 30;
  const i = beats.findIndex((b) => b.centerY >= line);
  return i === -1 ? Math.max(0, beats.length - 1) : i;
}
