"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api-client";
import { SceneModal } from "@/components/SceneModal";
import { jobPercent, jobState, relTime, TONE_STYLE } from "@/lib/job-state";
import type { Job, Scene } from "@/lib/types";
import { activeAssetUrl } from "@/lib/types";

const POLL_STATUSES = new Set(["rendering", "queued", "preparing"]);

export default function JobPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openScene, setOpenScene] = useState<number | null>(null);
  const [rendering, setRendering] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [pollNonce, setPollNonce] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    // Tracked here rather than read off `job` state: the closure would see a stale
    // value, and this is the only thing that decides whether to keep polling.
    let lastStatus: string | null = null;
    async function load() {
      try {
        const j = await api.getJob(id);
        if (cancelled) return;
        setJob(j);
        setError(null);
        lastStatus = j.status;
        if (POLL_STATUSES.has(j.status)) timer = setTimeout(load, 5000);
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : String(e));
        // Re-arm through the failure. Rescheduling only on success meant one blip
        // (Next restarting, a dropped keep-alive socket) froze the page on stale
        // data forever — the job kept moving, the screen didn't, and the banner
        // never cleared even once the API came back.
        if (lastStatus === null || POLL_STATUSES.has(lastStatus)) timer = setTimeout(load, 5000);
      }
    }
    load();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [id, pollNonce]);

  async function triggerRender() {
    setRendering(true);
    setError(null);
    try {
      await api.render(id);
      setJob((j) => (j ? { ...j, status: "rendering" } : j));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRendering(false);
    }
  }

  async function retryIngest() {
    setRetrying(true);
    setError(null);
    try {
      await api.retryIngest(id);
      // Optimistic: h_ingest flips a failed job straight back to 'queued'
      // server-side, so reflect that immediately instead of leaving the old
      // "failed" state on screen until the next poll — bumping pollNonce
      // restarts the fetch/poll loop right away.
      setJob((j) => (j ? { ...j, status: "queued", error: undefined, failedStage: undefined } : j));
      setPollNonce((n) => n + 1);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRetrying(false);
    }
  }

  async function handleDelete() {
    if (
      !confirm(
        "Delete this job? An in-flight ingest stops at the next stage boundary (the stage already " +
          "running still finishes and still spends what it was going to spend); a render runs to completion.",
      )
    ) {
      return;
    }
    setDeleting(true);
    setError(null);
    try {
      await api.deleteJob(id);
      router.push("/");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setDeleting(false);
    }
  }

  function updateScene(updated: Scene) {
    setJob((j) => (j ? { ...j, scenes: j.scenes.map((s) => (s.sceneNumber === updated.sceneNumber ? updated : s)) } : j));
  }

  if (error && !job) {
    return (
      <main className="mx-auto w-full max-w-5xl flex-1 px-6 py-12">
        <Link href="/" className="text-sm text-indigo-600 hover:underline">
          ← Queue
        </Link>
        <p className="mt-6 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">
          {error}
        </p>
      </main>
    );
  }

  if (!job) {
    return (
      <main className="mx-auto w-full max-w-5xl flex-1 px-6 py-12">
        <p className="text-sm text-neutral-500 dark:text-neutral-400">Loading…</p>
      </main>
    );
  }

  const openSceneData = job.scenes.find((s) => s.sceneNumber === openScene) ?? null;
  // Same words the queue row shows — see lib/job-state.ts.
  const state = jobState(job);
  const style = TONE_STYLE[state.tone];

  return (
    <main className="w-full flex-1 px-6 py-10">
      <Link href="/" className="text-sm text-indigo-600 hover:underline">
        ← Queue
      </Link>

      <div className="mt-4 flex flex-wrap items-center justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${style.dot}`} />
            <span className={`text-xs font-semibold uppercase tracking-wide ${style.text}`}>{state.label}</span>
            <span className="text-[11px] text-neutral-500 dark:text-neutral-400">{relTime(job.createdAt)}</span>
          </div>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">{job.title || job.id}</h1>
          <p className="mt-0.5 text-xs text-neutral-500 dark:text-neutral-400">{state.detail}</p>
          {(job.total ?? 0) > 0 && (
            <div className="mt-2 flex max-w-md items-center gap-2">
              <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-neutral-200 dark:bg-neutral-800">
                <div
                  className={`h-full rounded-full transition-all ${style.bar}`}
                  style={{ width: `${jobPercent(job)}%` }}
                />
              </div>
              <span className="shrink-0 text-[11px] tabular-nums text-neutral-500 dark:text-neutral-400">
                {job.completed ?? 0}/{job.total}
              </span>
            </div>
          )}
        </div>
        <div className="flex items-center gap-3">
          {job.renderUrl && (
            <a
              href={job.renderUrl}
              target="_blank"
              rel="noreferrer"
              className="text-sm font-medium text-indigo-600 hover:underline"
            >
              View rendered video
            </a>
          )}
          {job.status === "failed" && (job.failedStage === "prepare" || (!job.failedStage && job.scenes.length === 0)) ? (
            <button
              onClick={retryIngest}
              disabled={retrying}
              className="rounded-lg bg-indigo-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-500 disabled:opacity-50"
            >
              {retrying ? "Retrying…" : "Retry ingest"}
            </button>
          ) : (
            <button
              onClick={triggerRender}
              // Scenes are on screen before their images exist now — don't let a
              // half-prepared job be sent to Lambda.
              disabled={rendering || job.status === "rendering" || job.status === "preparing" || job.status === "queued"}
              className="rounded-lg bg-indigo-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-500 disabled:opacity-50"
            >
              {job.status === "rendering" ? "Rendering…" : "Render"}
            </button>
          )}
          <button
            onClick={handleDelete}
            disabled={deleting}
            className="rounded-lg border border-red-200 px-4 py-2.5 text-sm font-medium text-red-600 transition hover:bg-red-50 disabled:opacity-50 dark:border-red-900 dark:hover:bg-red-950"
          >
            {deleting ? "Deleting…" : "Delete"}
          </button>
        </div>
      </div>

      {error && (
        <p className="mt-4 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">
          {error}
        </p>
      )}
      {job.error && (
        <p className="mt-4 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">
          Last {job.failedStage === "prepare" ? "ingest" : "render"} failed: {job.error}
        </p>
      )}

      <div className="mt-8 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {job.scenes.map((scene) => {
          const active = activeAssetUrl(scene);
          return (
            <button
              key={scene.sceneNumber}
              onClick={() => setOpenScene(scene.sceneNumber)}
              className="group overflow-hidden rounded-xl border border-neutral-200 bg-white text-left shadow-sm transition hover:shadow-md dark:border-neutral-800 dark:bg-neutral-900"
            >
              <div className="relative aspect-video bg-neutral-100 dark:bg-neutral-800">
                {active ? (
                  active.kind === "video" ? (
                    <video src={active.url} className="h-full w-full object-cover" muted loop autoPlay playsInline />
                  ) : (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={active.url} alt="" className="h-full w-full object-cover" />
                  )
                ) : job.status === "preparing" ? (
                  // Scenes are published before their images exist now, so an
                  // empty tile means "still coming", not "failed" — it fills in
                  // on one of the next polls.
                  <div className="flex h-full w-full animate-pulse items-center justify-center bg-neutral-200 text-xs text-neutral-400 dark:bg-neutral-800">
                    generating…
                  </div>
                ) : (
                  <div className="flex h-full w-full items-center justify-center text-xs text-neutral-400">
                    no image
                  </div>
                )}
                <span className="absolute left-1.5 top-1.5 rounded bg-black/60 px-1.5 py-0.5 text-[10px] font-semibold text-white">
                  {scene.sceneNumber}
                </span>
                {active?.kind === "video" && (
                  <span className="absolute right-1.5 top-1.5 rounded bg-indigo-600 px-1.5 py-0.5 text-[10px] font-semibold text-white">
                    video
                  </span>
                )}
                {scene.durationSeconds != null && (
                  <span className="absolute bottom-1.5 right-1.5 rounded bg-black/60 px-1.5 py-0.5 text-[10px] font-semibold text-white">
                    {Math.ceil(scene.durationSeconds)}s
                  </span>
                )}
              </div>
              <div className="p-2.5">
                <p className="line-clamp-2 text-xs text-neutral-600 dark:text-neutral-300">{scene.scriptSnippet}</p>
                <div className="mt-1.5 flex gap-1">
                  {scene.sceneType && (
                    <span className="rounded bg-neutral-100 px-1.5 py-0.5 text-[10px] uppercase text-neutral-500 dark:bg-neutral-800 dark:text-neutral-400">
                      {scene.sceneType}
                    </span>
                  )}
                  {scene.visualMode && (
                    <span className="rounded bg-neutral-100 px-1.5 py-0.5 text-[10px] uppercase text-neutral-500 dark:bg-neutral-800 dark:text-neutral-400">
                      {scene.visualMode}
                    </span>
                  )}
                </div>
              </div>
            </button>
          );
        })}
      </div>

      {openSceneData && (
        <SceneModal
          jobId={job.id}
          scene={openSceneData}
          onClose={() => setOpenScene(null)}
          onSceneUpdated={updateScene}
        />
      )}
    </main>
  );
}
