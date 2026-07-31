// Job/scene shapes for the bible-well production UI. One row per job in
// Supabase (bible_well_jobs), payload is this whole Job as JSONB — same
// single-table-JSONB pattern as military/lib/review/types.ts.

export type JobStatus = "queued" | "ready" | "rendering" | "rendered" | "failed";

export type AssetSource = "gpt-image" | "pexels" | "upload" | "video-gen";

/** One past generation/pick for a scene — appended, never overwritten, so the
 * user can pick any previous image or video back into the active slot. */
export interface AssetHistoryItem {
  id: string;
  url: string;
  source: AssetSource;
  prompt?: string;
  createdAt: string;
}

export interface SceneAsset {
  imageHistory: AssetHistoryItem[];
  videoHistory: AssetHistoryItem[];
  activeImageId?: string;
  activeVideoId?: string;
  /** Which of image/video actually renders — video only wins while one is
   * active; deleting/clearing the active video falls back to the image. */
  mode: "image" | "video";
}

export interface Scene {
  sceneNumber: number;
  scriptSnippet: string;
  sceneType?: string;
  visualMode?: "concrete" | "abstract";
  characterIds: string[];
  heroSubject?: string;
  imagePrompt: string;
  /** Real Whisper+DTW-aligned narration length for this scene, in seconds —
   * how long a video clip needs to be to cover it. */
  durationSeconds?: number;
  asset: SceneAsset;
}

export interface Job {
  id: string; // Baserow row_id
  createdAt: string;
  status: JobStatus;
  title?: string;
  clickupUrl?: string;
  scenes: Scene[];
  renderUrl?: string;
  error?: string;
}

export interface JobSummary {
  id: string;
  createdAt: string;
  status: JobStatus;
  title?: string;
  sceneCount: number;
}

/** Mirrors src/supabase_jobs.py's _resolve_asset — which url actually renders
 * for this scene right now (video wins while one is active). */
export function activeAssetUrl(scene: Scene): { url: string; kind: "image" | "video" } | null {
  const { asset } = scene;
  if (asset.mode === "video") {
    const video = asset.videoHistory.find((v) => v.id === asset.activeVideoId);
    if (video) return { url: video.url, kind: "video" };
  }
  const image = asset.imageHistory.find((i) => i.id === asset.activeImageId);
  return image ? { url: image.url, kind: "image" } : null;
}

export function jobSummary(job: Job): JobSummary {
  return {
    id: job.id,
    createdAt: job.createdAt,
    status: job.status,
    title: job.title,
    sceneCount: job.scenes.length,
  };
}
