"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api-client";
import { jobPercent, jobState, relTime, TONE_STYLE } from "@/lib/job-state";
import type { JobSummary } from "@/lib/types";

function Row({ job, refresh }: { job: JobSummary; refresh: () => void }) {
  const [busy, setBusy] = useState(false);
  const state = jobState(job);
  const style = TONE_STYLE[state.tone];
  const active = job.status === "queued" || job.status === "preparing" || job.status === "rendering";

  async function cancel() {
    if (
      !confirm(
        "Cancel this job? An ingest stops at the next stage; progress so far is kept. " +
          "A render runs to completion.",
      )
    ) {
      return;
    }
    setBusy(true);
    await api.deleteJob(job.id).catch(() => {});
    setBusy(false);
    refresh();
  }

  return (
    <li className="flex items-start gap-3 px-5 py-4">
      <span className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${style.dot}`} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className={`text-xs font-semibold uppercase tracking-wide ${style.text}`}>{state.label}</span>
          <span className="text-[11px] text-neutral-500 dark:text-neutral-400">{relTime(job.createdAt)}</span>
        </div>
        <Link href={`/job/${job.id}`} className="mt-1 block truncate text-sm font-medium hover:underline">
          {job.title || job.id}
        </Link>
        <p className="mt-0.5 text-xs text-neutral-500 dark:text-neutral-400">{state.detail}</p>

        {(job.total ?? 0) > 0 && (
          <div className="mt-2 flex items-center gap-2">
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

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Link
            href={`/job/${job.id}`}
            className="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-indigo-500"
          >
            Open job →
          </Link>
          {active && (
            <button
              onClick={cancel}
              disabled={busy}
              className="rounded-lg border border-red-200 px-3 py-1.5 text-xs font-medium text-red-600 transition hover:bg-red-50 disabled:opacity-50 dark:border-red-900 dark:hover:bg-red-950"
            >
              {busy ? "…" : "Cancel"}
            </button>
          )}
          {job.clickupUrl && (
            <a
              href={job.clickupUrl}
              target="_blank"
              rel="noreferrer"
              className="rounded-lg border border-neutral-200 px-3 py-1.5 text-xs font-medium text-neutral-600 transition hover:bg-neutral-50 dark:border-neutral-800 dark:text-neutral-300 dark:hover:bg-neutral-800"
            >
              ClickUp ↗
            </a>
          )}
        </div>
      </div>
    </li>
  );
}

export default function QueuePage() {
  const [jobs, setJobs] = useState<JobSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const refresh = useCallback(() => setNonce((n) => n + 1), []);

  // Poll: a preparing job's stage/counters move every few seconds, and this list
  // is the only place they're visible without opening the job.
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    async function load() {
      try {
        const j = await api.listJobs();
        if (cancelled) return;
        setJobs(j);
        setError(null);
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : String(e));
      }
      // Re-arm through failures, same as the job page — one blip must not freeze
      // the queue on stale rows forever.
      if (!cancelled) timer = setTimeout(load, 5000);
    }
    load();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [nonce]);

  return (
    <main className="mx-auto w-full max-w-4xl flex-1 px-6 py-12">
      <h1 className="text-2xl font-semibold tracking-tight">Production queue</h1>
      <p className="mt-1 text-sm text-neutral-500 dark:text-neutral-400">
        Jobs prepared by ingest, waiting for review before render.
      </p>

      {error && (
        <p className="mt-6 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">
          {error}
        </p>
      )}

      {jobs === null && !error && (
        <p className="mt-8 text-sm text-neutral-500 dark:text-neutral-400">Loading…</p>
      )}

      {jobs && jobs.length === 0 && (
        <p className="mt-8 text-sm text-neutral-500 dark:text-neutral-400">
          No jobs yet — ingest a row to see it here.
        </p>
      )}

      {jobs && jobs.length > 0 && (
        <ul className="mt-8 divide-y divide-neutral-200 rounded-xl border border-neutral-200 bg-white dark:divide-neutral-800 dark:border-neutral-800 dark:bg-neutral-900">
          {jobs.map((job) => (
            <Row key={job.id} job={job} refresh={refresh} />
          ))}
        </ul>
      )}
    </main>
  );
}
