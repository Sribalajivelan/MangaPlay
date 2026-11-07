/** Mirrors bundles/<ep>/script.json (schema_version 1). Hand-written for the spike; the design
 *  generates this from the Pydantic models (JSON Schema -> TS) in Phase 1. */

export type Box = [number, number, number, number]; // x0, y0, x1, y1 in strip px

export type BeatType =
  | "speech" | "thought" | "narration" | "system" | "reaction"
  | "sfx" | "credit" | "note" | "skip" | "caption";

export interface Beat {
  id: string;
  bbox: Box;
  bubble: Box;
  source: "directed" | "draft";
  type: BeatType;
  speaker: string;
  text: string;
  tts_text: string;
  emotion: string;
  delivery: string;
  confidence: number | null;
  speed: number;
  gain: number;
  audio: string | null;
  audio_ms: number;
  /** expressive version: character age + emotion applied (optional: older bundles have only the plain version) */
  audio_x?: string | null;
  audio_x_ms?: number;
  x_speed?: number;
  x_gain?: number;
  x_pitch?: number;
  /** present when a person or a policy corrected the Director's choice */
  override?: { by: "user" | "policy"; was: string; muted?: boolean };
}

export interface Slice {
  file: string;
  y: number;
  h: number;
}

export interface Script {
  schema_version: number;
  episode: string;
  reading_direction: "vertical";
  strip: { width: number; height: number; slices: Slice[] };
  cast: { id: string; name: string }[];
  voices: Record<string, string>;
  beats: Beat[];
}

// ---- library (backend: docs/08-LIBRARY-DESIGN.md) ---------------------------------------------------

export type ChapterStatus = "uploading" | "queued" | "processing" | "ready" | "failed" | "cancelled";

export interface Chapter {
  id: number;
  manga_id: number;
  number: number | null;
  title: string;
  status: ChapterStatus;
  stage: string | null;
  progress: number;
  detail: string | null;
  error: string | null;
  page_count: number;
  cost_usd: number;
  created_at: string;
  updated_at: string;
  ready_at: string | null;
  bundle_url: string | null;
}

export interface MangaSummary {
  id: number;
  title: string;
  created_at: string;
  updated_at: string;
  chapters: number;
  ready: number;
  processing: number;
  first_ready_chapter: number | null;
}

export interface ContinueInfo {
  id: number;
  manga_id: number;
  manga_title: string;
  title: string;
  number: number | null;
}

export interface ReadingState {
  beat_id: string | null;
  y: number;
  rate: number | null;
  pace: number | null;
  expressive: number | null;
}

export interface SaveState {
  beat_id: string | null;
  y: number;
  rate: number;
  pace: number;
  expressive: boolean;
}
