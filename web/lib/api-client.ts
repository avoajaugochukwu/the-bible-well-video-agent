"use client";
// Browser-side calls, all routed through /api/proxy/* (see app/api/proxy) so
// the shared pipeline secret never reaches client JS.
import type { AssetSource, Character, CharacterVariant, Job, JobSummary, Scene } from "./types";

// Parse before checking res.ok loses the real error whenever the body isn't JSON
// — a dead/hung pipeline API makes Next return its own HTML 500, and `res.json()`
// turns that into "Unexpected end of JSON input", burying the actual cause.
async function parse<T>(res: Response, path: string): Promise<T> {
  const text = await res.text();
  let data: { error?: string } | null = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    // non-JSON body (Next error page, proxy crash) — surface a slice of it verbatim
  }
  if (!res.ok) throw new Error(data?.error || `${res.status} ${path}: ${text.slice(0, 200)}`);
  return data as T;
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/proxy/${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  return parse<T>(res, path);
}

export interface PexelsResult {
  id: number;
  url: string;
  width?: number;
  height?: number;
  duration?: number;
  thumbnail_url?: string;
  photographer?: string;
}

export interface VideoStatus {
  job_id: string;
  status: string;
  video?: { url: string; width: number; height: number; duration_s: number; fps: number } | null;
  error?: string | null;
}

export const api = {
  listJobs: () => call<{ jobs: JobSummary[] }>("jobs").then((r) => r.jobs),
  getJob: (id: string) => call<Job>(`jobs/${id}`),
  render: (id: string) => call(`jobs/${id}/render`, { method: "POST" }),
  deleteJob: (id: string) =>
    call<{ ok: boolean; was_in_flight: boolean; note: string | null }>(`jobs/${id}`, { method: "DELETE" }),
  retryIngest: (id: string) =>
    call<{ ok: boolean; status: string }>("ingest", { method: "POST", body: JSON.stringify({ row_id: id }) }),

  regenerateImage: (id: string, sceneNumber: number, prompt: string) =>
    call<Scene>(`jobs/${id}/scenes/${sceneNumber}/regenerate-image`, {
      method: "POST",
      body: JSON.stringify({ prompt }),
    }),

  approveWardrobe: (id: string) =>
    call<{ ok: boolean; status: string }>(`jobs/${id}/approve-wardrobe`, { method: "POST" }),

  // Returns the whole updated Character when variantId is omitted (a base-image
  // regenerate), or just the updated CharacterVariant when variantId is passed
  // — mirrors src/ingest_server.py's h_regenerate_character_image exactly.
  regenerateCharacterImage: (id: string, characterId: string, prompt: string, variantId?: string) =>
    call<Character | CharacterVariant>(`jobs/${id}/characters/${characterId}/regenerate-image`, {
      method: "POST",
      body: JSON.stringify({ prompt, variantId: variantId ?? null }),
    }),

  generateVideo: (id: string, sceneNumber: number, prompt?: string) =>
    call<{ job_id: string; status: string }>(`jobs/${id}/scenes/${sceneNumber}/generate-video`, {
      method: "POST",
      body: JSON.stringify({ prompt: prompt || undefined }),
    }),

  videoStatus: (jobId: string) => call<VideoStatus>(`video-status/${jobId}`),

  commitVideo: (id: string, sceneNumber: number, videoJobId: string) =>
    call<Scene>(`jobs/${id}/scenes/${sceneNumber}/commit-video`, {
      method: "POST",
      body: JSON.stringify({ job_id: videoJobId }),
    }),

  pexelsSearch: (kind: "image" | "video", query: string) =>
    call<{ results: PexelsResult[] }>(
      `pexels/search?kind=${kind}&query=${encodeURIComponent(query)}`,
    ).then((r) => r.results),

  pickAsset: (id: string, sceneNumber: number, kind: "image" | "video", url: string, source: AssetSource = "pexels") =>
    call<Scene>(`jobs/${id}/scenes/${sceneNumber}/pick-asset`, {
      method: "POST",
      body: JSON.stringify({ kind, url, source }),
    }),

  uploadAsset: async (id: string, sceneNumber: number, kind: "image" | "video", file: File) => {
    const qs = new URLSearchParams({ kind, filename: file.name });
    const res = await fetch(`/api/proxy/jobs/${id}/scenes/${sceneNumber}/upload-asset?${qs}`, {
      method: "POST",
      headers: { "Content-Type": file.type || "application/octet-stream" },
      body: file,
    });
    return parse<Scene>(res, "upload-asset");
  },

  activateAsset: (id: string, sceneNumber: number, kind: "image" | "video", assetId: string) =>
    call<Scene>(`jobs/${id}/scenes/${sceneNumber}/activate-asset`, {
      method: "POST",
      body: JSON.stringify({ kind, assetId }),
    }),

  deleteAsset: (id: string, sceneNumber: number, kind: "image" | "video", assetId: string) =>
    call<Scene>(`jobs/${id}/scenes/${sceneNumber}/asset/${kind}/${assetId}`, { method: "DELETE" }),
};
