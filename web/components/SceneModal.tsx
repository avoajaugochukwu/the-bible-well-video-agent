"use client";
import { useEffect, useRef, useState } from "react";
import { api, type PexelsResult } from "@/lib/api-client";
import type { AssetHistoryItem, Character, Scene } from "@/lib/types";
import { activeAssetUrl, resolveCharacterRefsUsed } from "@/lib/types";

type Tab = "ai-image" | "ai-video" | "pexels-image" | "pexels-video";

const TABS: { key: Tab; label: string }[] = [
  { key: "ai-image", label: "AI Image" },
  { key: "ai-video", label: "AI Video" },
  { key: "pexels-image", label: "Pexels Image" },
  { key: "pexels-video", label: "Pexels Video" },
];

function HistoryStrip({
  items,
  activeId,
  onActivate,
  onDelete,
}: {
  items: AssetHistoryItem[];
  activeId?: string | null;
  onActivate: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  if (items.length === 0) return null;
  return (
    <div className="mt-4 flex gap-2 overflow-x-auto pb-1">
      {[...items].reverse().map((item) => (
        <div key={item.id} className="group relative shrink-0">
          <button
            onClick={() => onActivate(item.id)}
            className={`h-16 w-28 overflow-hidden rounded-md border-2 bg-neutral-100 dark:bg-neutral-800 ${
              item.id === activeId
                ? "border-indigo-500"
                : "border-transparent opacity-70 hover:opacity-100"
            }`}
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={item.url} alt="" className="h-full w-full object-cover" />
          </button>
          <button
            onClick={() => onDelete(item.id)}
            className="absolute -right-1 -top-1 hidden h-5 w-5 items-center justify-center rounded-full bg-red-600 text-xs text-white group-hover:flex"
            title="Delete"
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );
}

function DetailRow({ label, value }: { label: string; value?: string | null }) {
  if (!value) return null;
  return (
    <p className="leading-snug text-neutral-600 dark:text-neutral-300">
      <span className="font-medium text-sky-600 dark:text-sky-400">{label}</span> {value}
    </p>
  );
}

export function SceneModal({
  jobId,
  scene,
  characters,
  onClose,
  onSceneUpdated,
}: {
  jobId: string;
  scene: Scene;
  characters: Character[];
  onClose: () => void;
  onSceneUpdated: (scene: Scene) => void;
}) {
  const [tab, setTab] = useState<Tab>("ai-image");
  const [prompt, setPrompt] = useState(scene.imagePrompt);
  const [videoPrompt, setVideoPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [videoProgress, setVideoProgress] = useState<string | null>(null);
  const [pexelsQuery, setPexelsQuery] = useState("");
  const [pexelsResults, setPexelsResults] = useState<PexelsResult[]>([]);
  const [copied, setCopied] = useState(false);
  const imageFileInput = useRef<HTMLInputElement>(null);
  const videoFileInput = useRef<HTMLInputElement>(null);

  const active = activeAssetUrl(scene);

  async function downloadActive() {
    if (!active) return;
    const res = await fetch(active.url);
    const blob = await res.blob();
    const blobUrl = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = blobUrl;
    a.download = active.url.split("/").pop() || `scene-${scene.sceneNumber}`;
    a.click();
    URL.revokeObjectURL(blobUrl);
  }

  function copyActiveUrl() {
    if (!active) return;
    navigator.clipboard.writeText(active.url);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, []);

  function upload(kind: "image" | "video", file: File | undefined) {
    if (!file) return;
    run(() => api.uploadAsset(jobId, scene.sceneNumber, kind, file), onSceneUpdated);
  }

  async function run<T>(fn: () => Promise<T>, onDone?: (v: T) => void) {
    setBusy(true);
    setError(null);
    try {
      const v = await fn();
      onDone?.(v);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  function activate(kind: "image" | "video", id: string) {
    run(() => api.activateAsset(jobId, scene.sceneNumber, kind, id), onSceneUpdated);
  }
  function del(kind: "image" | "video", id: string) {
    run(() => api.deleteAsset(jobId, scene.sceneNumber, kind, id), onSceneUpdated);
  }

  async function generateVideo() {
    setBusy(true);
    setError(null);
    setVideoProgress("submitting…");
    try {
      const { job_id } = await api.generateVideo(jobId, scene.sceneNumber, videoPrompt || undefined);
      setVideoProgress("queued…");
      for (;;) {
        await new Promise((r) => setTimeout(r, 4000));
        const status = await api.videoStatus(job_id);
        if (status.error) throw new Error(status.error);
        if (status.video) {
          setVideoProgress("saving clip…");
          const updated = await api.commitVideo(jobId, scene.sceneNumber, job_id);
          onSceneUpdated(updated);
          setVideoProgress(null);
          break;
        }
        setVideoProgress(status.status);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setVideoProgress(null);
    } finally {
      setBusy(false);
    }
  }

  async function searchPexels() {
    if (!pexelsQuery.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const kind = tab === "pexels-video" ? "video" : "image";
      setPexelsResults(await api.pexelsSearch(kind, pexelsQuery));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  function pickPexels(result: PexelsResult) {
    const kind = tab === "pexels-video" ? "video" : "image";
    run(() => api.pickAsset(jobId, scene.sceneNumber, kind, result.url, "pexels"), onSceneUpdated);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div
        className="flex h-[95vh] w-[95vw] max-w-none flex-col overflow-hidden rounded-2xl bg-white shadow-xl dark:bg-neutral-900"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-neutral-200 px-5 py-4 dark:border-neutral-800">
          <div>
            <p className="text-sm font-medium">
              Scene {scene.sceneNumber}
              {scene.durationSeconds != null && (
                <span className="ml-2 rounded-full bg-indigo-100 px-2 py-0.5 text-xs font-semibold text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300">
                  {Math.ceil(scene.durationSeconds)}s
                </span>
              )}
            </p>
            <p className="mt-0.5 line-clamp-1 text-xs text-neutral-500 dark:text-neutral-400">
              {scene.scriptSnippet}
            </p>
            {resolveCharacterRefsUsed(scene, characters).length > 0 && (
              <p className="mt-1 text-[11px] text-neutral-500 dark:text-neutral-400">
                {resolveCharacterRefsUsed(scene, characters)
                  .map((ref) => `${ref.label}: ${ref.contextLabel}`)
                  .join("  ·  ")}
              </p>
            )}
          </div>
          <button onClick={onClose} className="text-neutral-400 hover:text-neutral-700 dark:hover:text-neutral-200">
            ✕
          </button>
        </div>

        <div className="flex flex-1 overflow-hidden">
          <div className="flex w-[60%] flex-col overflow-y-auto border-r border-neutral-200 p-5 dark:border-neutral-800">
            <div className="aspect-video w-full overflow-hidden rounded-lg bg-black">
              {active ? (
                active.kind === "video" ? (
                  <video src={active.url} className="h-full w-full object-contain" controls />
                ) : (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={active.url} alt="" className="h-full w-full object-contain" />
                )
              ) : (
                <div className="flex h-full w-full items-center justify-center text-sm text-neutral-500">
                  no image yet
                </div>
              )}
            </div>

            <div className="mt-3 flex flex-wrap items-center gap-3">
              {active && (
                <>
                  <button
                    onClick={downloadActive}
                    className="text-xs font-medium text-neutral-500 hover:text-neutral-800 dark:hover:text-neutral-200"
                  >
                    Download active {active.kind}
                  </button>
                  <button
                    onClick={copyActiveUrl}
                    title="Copy url"
                    className="text-neutral-500 hover:text-neutral-800 dark:hover:text-neutral-200"
                  >
                    {copied ? (
                      <span className="text-xs font-medium">Copied</span>
                    ) : (
                      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
                        <rect x="9" y="9" width="13" height="13" rx="2" />
                        <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                      </svg>
                    )}
                  </button>
                </>
              )}
              <button
                disabled={busy}
                onClick={() => imageFileInput.current?.click()}
                className="rounded-lg border border-neutral-300 px-3 py-1.5 text-xs font-medium disabled:opacity-50 dark:border-neutral-700"
              >
                Upload image
              </button>
              <button
                disabled={busy}
                onClick={() => videoFileInput.current?.click()}
                className="rounded-lg border border-neutral-300 px-3 py-1.5 text-xs font-medium disabled:opacity-50 dark:border-neutral-700"
              >
                Upload video
              </button>
              {scene.asset.mode === "video" && scene.asset.activeVideoId && (
                <button
                  onClick={() => del("video", scene.asset.activeVideoId!)}
                  className="text-xs font-medium text-red-600 hover:text-red-700"
                >
                  Delete video (fall back to image)
                </button>
              )}
              <input
                ref={imageFileInput}
                type="file"
                accept="image/*"
                className="hidden"
                onChange={(e) => upload("image", e.target.files?.[0])}
              />
              <input
                ref={videoFileInput}
                type="file"
                accept="video/*"
                className="hidden"
                onChange={(e) => upload("video", e.target.files?.[0])}
              />
            </div>

            <details className="mt-4 rounded-lg border border-neutral-200 dark:border-neutral-800">
              <summary className="cursor-pointer select-none px-3 py-2 text-xs font-medium text-neutral-600 dark:text-neutral-300">
                Agent details
                <span className="ml-2 font-normal text-neutral-400">
                  #{scene.sceneNumber}
                  {scene.visualMode ? ` · ${scene.visualMode}` : ""}
                </span>
              </summary>
              <div className="space-y-1.5 border-t border-neutral-200 px-3 py-3 text-xs dark:border-neutral-800">
                <p className="italic text-neutral-500 dark:text-neutral-400">{scene.scriptSnippet}</p>
                {scene.imagePrompt && (
                  <p className="text-emerald-700 dark:text-emerald-400">{scene.imagePrompt}</p>
                )}
                <DetailRow label="loc" value={scene.location} />
                <DetailRow label="chars" value={scene.characterIds?.length ? scene.characterIds.join(", ") : "—"} />
                <DetailRow label="staging" value={scene.staging} />
                <DetailRow label="anchor" value={scene.recognitionCue} />
                <DetailRow label="hero" value={scene.heroSubject} />
                <DetailRow label="type" value={scene.sceneType} />
              </div>
            </details>
          </div>

          <div className="flex w-[40%] flex-col overflow-hidden">
            <div className="flex border-b border-neutral-200 px-5 dark:border-neutral-800">
              {TABS.map((t) => (
                <button
                  key={t.key}
                  onClick={() => setTab(t.key)}
                  className={`-mb-px border-b-2 px-3 py-3 text-sm font-medium transition ${
                    tab === t.key
                      ? "border-indigo-500 text-indigo-600 dark:text-indigo-400"
                      : "border-transparent text-neutral-500 hover:text-neutral-800 dark:hover:text-neutral-200"
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </div>

            <div className="flex-1 overflow-y-auto px-5 py-4">
              {error && (
                <p className="mb-3 rounded-md bg-red-50 px-3 py-2 text-xs text-red-700 dark:bg-red-950 dark:text-red-300">
                  {error}
                </p>
              )}

              {tab === "ai-image" && (
                <div>
                  <textarea
                    value={prompt}
                    onChange={(e) => setPrompt(e.target.value)}
                    rows={4}
                    className="w-full rounded-lg border border-neutral-300 bg-white p-3 text-sm dark:border-neutral-700 dark:bg-neutral-800"
                  />
                  <button
                    disabled={busy || !prompt.trim()}
                    onClick={() => run(() => api.regenerateImage(jobId, scene.sceneNumber, prompt), onSceneUpdated)}
                    className="mt-3 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
                  >
                    {scene.asset.imageHistory.length ? "Regenerate image" : "Generate image"}
                  </button>
                  <p className="mt-4 text-xs font-medium text-neutral-500 dark:text-neutral-400">History</p>
                  <HistoryStrip
                    items={scene.asset.imageHistory}
                    activeId={scene.asset.activeImageId}
                    onActivate={(id) => activate("image", id)}
                    onDelete={(id) => del("image", id)}
                  />
                </div>
              )}

              {tab === "ai-video" && (
                <div>
                  <textarea
                    value={videoPrompt}
                    onChange={(e) => setVideoPrompt(e.target.value)}
                    rows={2}
                    placeholder="Optional motion prompt — what moves (camera / subject). Leave blank for automatic motion."
                    className="w-full rounded-lg border border-neutral-300 bg-white p-3 text-sm dark:border-neutral-700 dark:bg-neutral-800"
                  />
                  <button
                    disabled={busy || !active}
                    onClick={generateVideo}
                    className="mt-3 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
                  >
                    Generate video from current image
                  </button>
                  {videoProgress && (
                    <p className="mt-2 text-xs text-neutral-500 dark:text-neutral-400">{videoProgress}</p>
                  )}
                  {!active && (
                    <p className="mt-2 text-xs text-neutral-500 dark:text-neutral-400">
                      Generate or pick an image first — video is generated from a scene&apos;s image.
                    </p>
                  )}
                  <p className="mt-4 text-xs font-medium text-neutral-500 dark:text-neutral-400">History</p>
                  <HistoryStrip
                    items={scene.asset.videoHistory}
                    activeId={scene.asset.activeVideoId ?? undefined}
                    onActivate={(id) => activate("video", id)}
                    onDelete={(id) => del("video", id)}
                  />
                </div>
              )}

              {(tab === "pexels-image" || tab === "pexels-video") && (
                <div>
                  <div className="flex gap-2">
                    <input
                      value={pexelsQuery}
                      onChange={(e) => setPexelsQuery(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && searchPexels()}
                      placeholder="Search Pexels…"
                      className="flex-1 rounded-lg border border-neutral-300 bg-white px-3 py-2 text-sm dark:border-neutral-700 dark:bg-neutral-800"
                    />
                    <button
                      disabled={busy || !pexelsQuery.trim()}
                      onClick={searchPexels}
                      className="rounded-lg bg-neutral-800 px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-neutral-100 dark:text-neutral-900"
                    >
                      Search
                    </button>
                  </div>
                  <div className="mt-4 grid grid-cols-2 gap-2">
                    {pexelsResults.map((r) => (
                      <button
                        key={r.id}
                        onClick={() => pickPexels(r)}
                        className="group relative aspect-video overflow-hidden rounded-md bg-neutral-100 dark:bg-neutral-800"
                      >
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img
                          src={r.thumbnail_url || r.url}
                          alt=""
                          className="h-full w-full object-cover transition group-hover:scale-105"
                        />
                        {r.photographer && (
                          <span className="absolute bottom-1 left-1 rounded bg-black/60 px-1.5 py-0.5 text-[10px] text-white">
                            {r.photographer}
                          </span>
                        )}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
