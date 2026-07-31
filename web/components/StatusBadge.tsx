import type { JobStatus } from "@/lib/types";

const STYLES: Record<JobStatus, string> = {
  queued: "bg-neutral-200 text-neutral-700 dark:bg-neutral-800 dark:text-neutral-300",
  ready: "bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-300",
  rendering: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  rendered: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  failed: "bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300",
};

export function StatusBadge({ status }: { status: JobStatus }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${STYLES[status]}`}>
      {status}
    </span>
  );
}
