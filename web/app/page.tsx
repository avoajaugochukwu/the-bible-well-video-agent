"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api-client";
import { StatusBadge } from "@/components/StatusBadge";
import type { JobSummary } from "@/lib/types";

export default function QueuePage() {
  const [jobs, setJobs] = useState<JobSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listJobs().then(setJobs).catch((e) => setError(e.message));
  }, []);

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
            <li key={job.id}>
              <Link
                href={`/job/${job.id}`}
                className="flex items-center justify-between gap-4 px-5 py-4 transition hover:bg-neutral-50 dark:hover:bg-neutral-800/60"
              >
                <div className="min-w-0">
                  <p className="truncate font-medium">{job.title || job.id}</p>
                  <p className="mt-0.5 text-xs text-neutral-500 dark:text-neutral-400">
                    {job.sceneCount} scenes · {new Date(job.createdAt).toLocaleString()}
                  </p>
                </div>
                <StatusBadge status={job.status} />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
