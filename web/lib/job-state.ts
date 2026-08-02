// The single place that decides what a job's state IS and what it's CALLED.
//
// The queue row and the job page header both call this, so they can never drift
// apart — same reason sleep-stories/lib/jobs/render-state.ts exists. Derived on
// read from whatever the last poll returned; nothing here is stored.

import type { JobStatus } from "./types";

export type Tone = "idle" | "working" | "ready" | "done" | "error";

export interface JobState {
  /** Short, uppercase. Sits next to the status dot. */
  label: string;
  /** One sentence under the title — progress, error, or what to do next. */
  detail: string;
  tone: Tone;
}

/** Only the colours live here; the words come from jobState() above so there's
 * still exactly one source for them. `working` pulses — a job that is actually
 * spending money should never look the same as one waiting for a human. */
export const TONE_STYLE: Record<Tone, { dot: string; text: string; bar: string }> = {
  idle: { dot: "bg-neutral-400", text: "text-neutral-500 dark:text-neutral-400", bar: "bg-neutral-400" },
  working: { dot: "bg-amber-500 animate-pulse", text: "text-amber-600 dark:text-amber-400", bar: "bg-amber-500" },
  ready: { dot: "bg-blue-500", text: "text-blue-600 dark:text-blue-400", bar: "bg-blue-500" },
  done: { dot: "bg-emerald-500", text: "text-emerald-600 dark:text-emerald-400", bar: "bg-emerald-500" },
  error: { dot: "bg-red-500", text: "text-red-600 dark:text-red-400", bar: "bg-red-500" },
};

/** Everything either a Job or a JobSummary can offer — both shapes satisfy it. */
export interface JobStateInput {
  status: JobStatus;
  currentStage?: string;
  total?: number;
  completed?: number;
  sceneCount?: number;
  error?: string;
  failedStage?: "prepare" | "render";
}

export function jobState(job: JobStateInput): JobState {
  const total = job.total ?? job.sceneCount ?? 0;
  const completed = job.completed ?? 0;
  const counted = total > 0 ? ` ${completed}/${total}` : "";
  switch (job.status) {
    case "queued":
      return { label: "QUEUED", detail: "Waiting its turn in the ingest queue", tone: "idle" };
    case "awaiting_wardrobe_approval":
      return {
        label: "REVIEW WARDROBE",
        detail: "Review character outfits before scene images generate",
        tone: "ready",
      };
    case "preparing": {
      // currentStage is already a sentence-cased verb phrase ("Generating
      // images"), so it doubles as both the label and the head of the detail.
      const stage = job.currentStage || "Preparing";
      return { label: stage.toUpperCase(), detail: `${stage}${counted}…`, tone: "working" };
    }
    case "ready":
      return { label: "READY", detail: `${total} scenes prepared — review, then render`, tone: "ready" };
    case "rendering":
      return { label: "RENDERING", detail: "Remotion Lambda is rendering the video", tone: "working" };
    case "rendered":
      return { label: "RENDERED", detail: "Rendered and pushed to ClickUp", tone: "done" };
    case "failed":
      return {
        label: "FAILED",
        detail: job.error || `${job.failedStage === "prepare" ? "Ingest" : "Render"} failed`,
        tone: "error",
      };
  }
}

/** Progress-bar width, 0-100. */
export function jobPercent(job: JobStateInput): number {
  const total = job.total ?? 0;
  return total > 0 ? Math.round(((job.completed ?? 0) / total) * 100) : 0;
}

export function relTime(iso: string): string {
  const s = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 1000));
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  return h < 24 ? `${h}h ago` : `${Math.round(h / 24)}d ago`;
}
