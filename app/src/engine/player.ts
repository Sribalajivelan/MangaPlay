import type { Beat, Script } from "../types";
import {
  DEFAULT_OPTIONS,
  activeAt,
  buildTimeline,
  cameraAt,
  currentAt,
  nearestBeatIndex,
  timelineEnd,
  type Cue,
  type VoicedBeat,
} from "./timeline";

export type Status = "idle" | "playing" | "paused" | "ended";

export interface Frame {
  /** camera position, strip px */
  y: number;
  /** index into the voiced-beat list being spoken right now, or -1 */
  active: number;
}

export interface PlayerEvents {
  onFrame: (f: Frame) => void;
  onStatus: (s: Status) => void;
  onError: (msg: string) => void;
}

const LOOKAHEAD_MS = 4000; // schedule audio this far ahead of the clock
const PREFETCH = 8; // decode this many upcoming clips

/** Which recording of a line to use: the expressive one when asked for and available, else the plain one. */
const useX = (b: Beat, expressive: boolean) => expressive && !!b.audio_x && (b.audio_x_ms ?? 0) > 0;
const fileFor = (b: Beat, x: boolean) => (useX(b, x) ? b.audio_x! : b.audio);
const msFor = (b: Beat, x: boolean) => (useX(b, x) ? (b.audio_x_ms as number) : b.audio_ms);
const gainFor = (b: Beat, x: boolean) => (useX(b, x) ? (b.x_gain ?? b.gain) : b.gain);

/**
 * Audio-as-clock player. The Web Audio clock (ctx.currentTime) is the single source of time:
 * clips are started at exact context times, the camera position is computed from the same clock,
 * and pause = ctx.suspend() freezes both together. Seeking rebuilds the timeline and re-schedules.
 */
export class Player {
  status: Status = "idle";
  rate = 1;
  /** play the expressive recordings (age + emotion) when the bundle has them */
  expressive = true;
  /** camera speed through art between lines, strip px per second at rate 1 */
  pace: number = DEFAULT_OPTIONS.travelPxPerSec;
  /** visible height in strip px; the view keeps this up to date on resize */
  viewH = 800;
  /** latest camera position, strip px */
  currentY = 0;

  voiced: { beatIndex: number; vb: VoicedBeat }[];

  private ctx: AudioContext | null = null;
  private master: GainNode | null = null;
  private buffers = new Map<string, Promise<AudioBuffer>>();
  private sources: AudioBufferSourceNode[] = [];
  private cues: Cue[] = [];
  private offset = 0; // voiced index of cues[0]
  private startY = 0;
  private baseTime = 0; // ctx time at timeline t = 0
  private nextToSchedule = 0;
  private generation = 0; // invalidates in-flight scheduling after a seek
  private cacheBust = 0;
  private changedSinceLoad = new Set<string>();
  private raf = 0;
  private timer = 0;

  constructor(
    private script: Script,
    private baseUrl: string,
    private ev: PlayerEvents,
  ) {
    this.voiced = Player.computeVoiced(script, this.expressive);
  }

  private static computeVoiced(script: Script, expressive: boolean): { beatIndex: number; vb: VoicedBeat }[] {
    return script.beats
      .map((b, beatIndex) => ({ b, beatIndex }))
      .filter(({ b }) => fileFor(b, expressive) && msFor(b, expressive) > 0)
      .map(({ b, beatIndex }) => ({
        beatIndex,
        vb: { id: b.id, centerY: (b.bbox[1] + b.bbox[3]) / 2, audioMs: msFor(b, expressive) },
      }));
  }

  /**
   * Swap in a re-built script (after a voice correction) without recreating the player: playback
   * state and the decoded audio of untouched lines are kept; only the changed lines are re-fetched.
   * The caller restarts playback if it wants to hear the change (voiced indexes can shift).
   */
  updateScript(next: Script, changedIds: string[]): void {
    this.stop();
    this.script = next;
    this.voiced = Player.computeVoiced(next, this.expressive);
    this.buffers.clear(); // keyed by file; re-fetch lazily (unchanged files come from the HTTP cache)
    // audio files are overwritten in place, so any URL the browser cached for a changed line is stale
    this.cacheBust = Date.now();
    this.changedSinceLoad = new Set([...this.changedSinceLoad, ...changedIds]);
  }

  /** Voiced index of a beat id, or -1 if that beat is not spoken (e.g. after "don't read this"). */
  indexOfBeat(id: string): number {
    return this.voiced.findIndex((v) => v.vb.id === id);
  }

  // ---- public API -------------------------------------------------------------------------

  /** Start (or restart) reading from the given voiced-beat index. Must be called from a user gesture the first time. */
  async playFrom(voicedIndex: number): Promise<void> {
    const i = Math.max(0, Math.min(voicedIndex, this.voiced.length - 1));
    if (!this.voiced.length) return;
    const ctx = this.ensureContext();
    if (ctx.state === "suspended") await ctx.resume();

    const gen = ++this.generation;
    this.stopSources();
    this.offset = i;
    this.startY = this.currentY;
    this.cues = buildTimeline(this.voiced.slice(i).map((v) => v.vb), {
      ...DEFAULT_OPTIONS,
      rate: this.rate,
      travelPxPerSec: this.pace,
      viewH: this.viewH,
      stripH: this.script.strip.height,
      startY: this.startY,
    });
    this.nextToSchedule = 0;

    try {
      // the first lines must be decoded before the clock starts, or the first cue would be late
      await Promise.all(this.voiced.slice(i, i + 2).map((_, k) => this.buffer(i + k)));
    } catch (e) {
      this.ev.onError(`Could not load audio: ${(e as Error).message}`);
      return;
    }
    if (gen !== this.generation) return; // superseded while loading

    this.baseTime = ctx.currentTime + 0.08;
    this.setStatus("playing");
    this.startLoops();
    this.tick();
  }

  pause(): void {
    if (this.status !== "playing" || !this.ctx) return;
    void this.ctx.suspend();
    this.stopLoops();
    this.setStatus("paused");
  }

  async resume(): Promise<void> {
    if (this.status === "paused" && this.ctx) {
      await this.ctx.resume();
      this.setStatus("playing");
      this.startLoops();
    } else if (this.status === "idle" || this.status === "ended") {
      await this.playFrom(this.status === "ended" ? 0 : this.nearestIndex());
    }
  }

  /** Stop and forget the current run (the camera stays where it is). */
  stop(): void {
    this.generation++;
    this.stopLoops();
    this.stopSources();
    this.cues = [];
    if (this.ctx?.state === "running") void this.ctx.suspend();
    this.setStatus("idle");
  }

  async setRate(rate: number): Promise<void> {
    this.rate = rate;
    await this.restartInPlace();
  }

  /** Switch between expressive and plain recordings; keeps the current line. */
  async setExpressive(on: boolean): Promise<void> {
    if (on === this.expressive) return;
    const id = this.voiced[this.currentVoicedIndex()]?.vb.id;
    const running = this.status === "playing" || this.status === "paused";
    const wasPaused = this.status === "paused";
    this.stop();
    this.expressive = on;
    this.voiced = Player.computeVoiced(this.script, on);
    this.buffers.clear();
    if (running) {
      const i = id ? this.indexOfBeat(id) : -1;
      await this.playFrom(i >= 0 ? i : this.nearestIndex());
      if (wasPaused) this.pause();
    }
  }

  async setPace(pxPerSec: number): Promise<void> {
    this.pace = pxPerSec;
    await this.restartInPlace();
  }

  /** Rebuild the timeline from the current line after a setting changed. */
  private async restartInPlace(): Promise<void> {
    if (this.status === "playing" || this.status === "paused") {
      const was = this.status;
      await this.playFrom(this.currentVoicedIndex());
      if (was === "paused") this.pause();
    }
  }

  setVolume(v: number): void {
    if (this.master) this.master.gain.value = v;
    this.volume = v;
  }
  private volume = 1;

  /** The camera was moved by the user, not by us. */
  setCameraY(y: number): void {
    this.currentY = y;
  }

  /** Voiced index the reader is looking at (used to resume after a manual scroll). */
  nearestIndex(): number {
    return nearestBeatIndex(this.voiced.map((v) => v.vb), this.currentY, { viewH: this.viewH, anchor: DEFAULT_OPTIONS.anchor });
  }

  currentVoicedIndex(): number {
    if (!this.cues.length) return this.nearestIndex();
    return this.offset + currentAt(this.cues, this.nowMs());
  }

  dispose(): void {
    this.stop();
    void this.ctx?.close();
    this.ctx = null;
  }

  // ---- internals --------------------------------------------------------------------------

  private ensureContext(): AudioContext {
    if (!this.ctx) {
      this.ctx = new AudioContext();
      this.master = this.ctx.createGain();
      this.master.gain.value = this.volume;
      this.master.connect(this.ctx.destination);
    }
    return this.ctx;
  }

  private nowMs(): number {
    return this.ctx ? (this.ctx.currentTime - this.baseTime) * 1000 : 0;
  }

  private buffer(voicedIdx: number): Promise<AudioBuffer> {
    const beat = this.script.beats[this.voiced[voicedIdx].beatIndex];
    const cacheKey = `${this.expressive ? "x" : "p"}:${beat.id}`;
    let p = this.buffers.get(cacheKey);
    if (!p) {
      const ctx = this.ensureContext();
      // corrected lines are re-rendered under the same file name: bypass the HTTP cache for those only
      const bust = this.changedSinceLoad.has(beat.id) ? `?v=${this.cacheBust}` : "";
      const file = fileFor(beat, this.expressive) as string;
      p = fetch(this.baseUrl + file + bust, bust ? { cache: "reload" } : undefined)
        .then((r) => {
          if (!r.ok) throw new Error(`${file}: HTTP ${r.status}`);
          return r.arrayBuffer();
        })
        .then((ab) => ctx.decodeAudioData(ab));
      p.catch(() => this.buffers.delete(cacheKey)); // allow a retry
      this.buffers.set(cacheKey, p);
    }
    return p;
  }

  private tick = (): void => {
    if (!this.ctx || this.status !== "playing") return;
    const t = this.nowMs();
    while (this.nextToSchedule < this.cues.length && this.cues[this.nextToSchedule].speakStart <= t + LOOKAHEAD_MS) {
      void this.schedule(this.nextToSchedule++, this.generation);
    }
    // keep the next few clips decoded
    const cur = this.currentVoicedIndex();
    for (let k = cur; k < Math.min(this.voiced.length, cur + PREFETCH); k++) void this.buffer(k).catch(() => {});
  };

  private async schedule(cueIdx: number, gen: number): Promise<void> {
    const voicedIdx = this.offset + cueIdx;
    try {
      const buf = await this.buffer(voicedIdx);
      if (gen !== this.generation || !this.ctx || !this.master) return;
      const beat = this.script.beats[this.voiced[voicedIdx].beatIndex];
      const src = this.ctx.createBufferSource();
      src.buffer = buf;
      src.playbackRate.value = this.rate;
      const g = this.ctx.createGain();
      g.gain.value = gainFor(beat, this.expressive);
      src.connect(g).connect(this.master);
      // if decoding was slow the cue may already be late: start now rather than skip it
      src.start(Math.max(this.baseTime + this.cues[cueIdx].speakStart / 1000, this.ctx.currentTime));
      src.onended = () => {
        this.sources = this.sources.filter((s) => s !== src);
        src.disconnect();
      };
      this.sources.push(src);
    } catch (e) {
      this.ev.onError(`Audio for ${this.voiced[voicedIdx].vb.id} failed: ${(e as Error).message}`);
    }
  }

  private frame = (): void => {
    if (this.status !== "playing") return;
    const t = this.nowMs();
    const y = cameraAt(this.cues, t, this.startY);
    this.currentY = y;
    const a = activeAt(this.cues, t);
    this.ev.onFrame({ y, active: a === -1 ? -1 : this.offset + a });
    if (t >= timelineEnd(this.cues) + 400) {
      this.stopLoops();
      this.setStatus("ended");
      this.ev.onFrame({ y, active: -1 });
      return;
    }
    this.raf = requestAnimationFrame(this.frame);
  };

  private startLoops(): void {
    this.stopLoops();
    this.raf = requestAnimationFrame(this.frame);
    this.timer = window.setInterval(this.tick, 120);
  }

  private stopLoops(): void {
    cancelAnimationFrame(this.raf);
    window.clearInterval(this.timer);
  }

  private stopSources(): void {
    for (const s of this.sources) {
      try {
        s.onended = null;
        s.stop();
        s.disconnect();
      } catch {
        /* already stopped */
      }
    }
    this.sources = [];
  }

  private setStatus(s: Status): void {
    this.status = s;
    this.ev.onStatus(s);
  }
}
