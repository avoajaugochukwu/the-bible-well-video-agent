"use client";
// Browser-side calls, all routed through /api/proxy/* (see app/api/proxy) so
// the shared pipeline secret never reaches client JS.
import type { AssetSource, Job, JobSummary, Scene } from "./types";

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/proxy/${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || `${res.status} ${path}`);
  return data as T;
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

  regenerateImage: (id: string, sceneNumber: number, prompt: string) =>
    call<Scene>(`jobs/${id}/scenes/${sceneNumber}/regenerate-image`, {
      method: "POST",
      body: JSON.stringify({ prompt }),
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

  activateAsset: (id: string, sceneNumber: number, kind: "image" | "video", assetId: string) =>
    call<Scene>(`jobs/${id}/scenes/${sceneNumber}/activate-asset`, {
      method: "POST",
      body: JSON.stringify({ kind, assetId }),
    }),

  deleteAsset: (id: string, sceneNumber: number, kind: "image" | "video", assetId: string) =>
    call<Scene>(`jobs/${id}/scenes/${sceneNumber}/asset/${kind}/${assetId}`, { method: "DELETE" }),
};
