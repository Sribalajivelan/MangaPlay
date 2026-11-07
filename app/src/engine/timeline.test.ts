import { describe, expect, it } from "vitest";
import {
  DEFAULT_OPTIONS,
  activeAt,
  buildTimeline,
  cameraAt,
  currentAt,
  nearestBeatIndex,
  targetY,
  timelineEnd,
  type TimelineOptions,
  type VoicedBeat,
} from "./timeline";

const opts = (over: Partial<TimelineOptions> = {}): TimelineOptions => ({
  ...DEFAULT_OPTIONS,
  viewH: 1000,
  stripH: 20000,
  startY: 0,
  ...over,
});

const beats: VoicedBeat[] = [
  { id: "a", centerY: 1000, audioMs: 2000 },
  { id: "b", centerY: 1100, audioMs: 1500 },
  { id: "c", centerY: 9000, audioMs: 3000 },
];

describe("buildTimeline", () => {
  it("is sequential and never overlaps", () => {
    const cues = buildTimeline(beats, opts());
    for (let i = 0; i < cues.length; i++) {
      expect(cues[i].travelStart).toBeLessThanOrEqual(cues[i].speakStart);
      expect(cues[i].speakStart).toBeLessThan(cues[i].speakEnd);
      if (i > 0) expect(cues[i].travelStart).toBeGreaterThanOrEqual(cues[i - 1].speakEnd);
    }
  });

  it("speech lasts exactly the clip length at rate 1 and half as long at rate 2", () => {
    const one = buildTimeline(beats, opts({ rate: 1 }));
    const two = buildTimeline(beats, opts({ rate: 2 }));
    expect(one[0].speakEnd - one[0].speakStart).toBeCloseTo(2000);
    expect(two[0].speakEnd - two[0].speakStart).toBeCloseTo(1000);
    expect(timelineEnd(two)).toBeCloseTo(timelineEnd(one) / 2);
  });

  it("clamps travel time for tiny and huge moves", () => {
    const cues = buildTimeline(beats, opts({ maxTravelMs: 5000 }));
    // b is only 100px below a (about 330 ms at 300 px/s): raised to the minimum travel time
    expect(cues[1].speakStart - cues[1].travelStart).toBeCloseTo(DEFAULT_OPTIONS.minTravelMs);
    // c is ~7700px away (about 26 s at 300 px/s): capped at the maximum given here
    expect(cues[2].speakStart - cues[2].travelStart).toBeCloseTo(5000);
  });

  it("moves through art slowly enough to look at: about 300 px per second by default", () => {
    // 3000 px of art between two lines must take around 10 s, not the 3.6 s cap of the first version
    const far: VoicedBeat[] = [
      { id: "x", centerY: 1000, audioMs: 1000 },
      { id: "y", centerY: 4000, audioMs: 1000 },
    ];
    const cues = buildTimeline(far, opts({ startY: targetY(1000, opts()) }));
    const travelMs = cues[1].speakStart - cues[1].travelStart;
    expect(travelMs).toBeGreaterThan(8000);
    expect(travelMs).toBeLessThan(12000);
  });

  it("a faster pace shortens travel proportionally", () => {
    const far: VoicedBeat[] = [{ id: "y", centerY: 4000, audioMs: 1000 }];
    const slow = buildTimeline(far, opts({ travelPxPerSec: 200, startY: 0 }));
    const fast = buildTimeline(far, opts({ travelPxPerSec: 800, startY: 0 }));
    expect(slow[0].speakStart / fast[0].speakStart).toBeCloseTo(4, 0);
  });

  it("does not travel when already in place", () => {
    const y = targetY(1000, opts());
    const cues = buildTimeline(beats, opts({ startY: y }));
    expect(cues[0].travelStart).toBe(cues[0].speakStart);
  });

  it("keeps the camera inside the strip", () => {
    const o = opts();
    expect(targetY(50, o)).toBe(0);
    expect(targetY(19990, o)).toBe(o.stripH - o.viewH);
  });
});

describe("cameraAt / activeAt", () => {
  const o = opts();
  const cues = buildTimeline(beats, o);

  it("holds the start position before the first travel and the last target after the end", () => {
    expect(cameraAt(cues, -5, 0)).toBe(cues[0].fromY);
    expect(cameraAt(cues, timelineEnd(cues) + 5000, 0)).toBe(cues[2].toY);
  });

  it("is exactly on target while a beat is spoken", () => {
    for (const c of cues) {
      const mid = (c.speakStart + c.speakEnd) / 2;
      expect(cameraAt(cues, mid, 0)).toBe(c.toY);
    }
  });

  it("eases monotonically between two beats", () => {
    const c = cues[2];
    let prev = -Infinity;
    for (let i = 0; i <= 20; i++) {
      const t = c.travelStart + ((c.speakStart - c.travelStart) * i) / 20;
      const y = cameraAt(cues, t, 0);
      expect(y).toBeGreaterThanOrEqual(prev);
      prev = y;
    }
    expect(prev).toBeCloseTo(c.toY);
  });

  it("reports the active cue only while speaking", () => {
    expect(activeAt(cues, cues[0].speakStart + 1)).toBe(0);
    expect(activeAt(cues, cues[0].speakEnd + 1)).toBe(-1); // gap
    expect(activeAt(cues, cues[2].travelStart + 1)).toBe(-1); // travelling
    expect(activeAt(cues, cues[2].speakStart + 1)).toBe(2);
  });

  it("currentAt is the speaking cue, else the next one", () => {
    expect(currentAt(cues, cues[1].speakStart + 1)).toBe(1);
    expect(currentAt(cues, cues[1].speakEnd + 1)).toBe(2);
    expect(currentAt(cues, timelineEnd(cues) + 1)).toBe(2);
  });
});

describe("nearestBeatIndex", () => {
  it("picks the first beat at or below the reading line", () => {
    const o = { viewH: 1000, anchor: 0.38 };
    expect(nearestBeatIndex(beats, 0, o)).toBe(0);
    expect(nearestBeatIndex(beats, 5000, o)).toBe(2);
    expect(nearestBeatIndex(beats, 19000, o)).toBe(2); // past the end -> last
  });
});
