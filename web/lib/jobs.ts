// Job persistence in Supabase — same table-per-app-JSONB-blob pattern as
// military/lib/review/store.ts, own table so this app doesn't collide with
// military's rows. The Python pipeline (src/run.py) writes the initial
// 'ready' row itself via Supabase's PostgREST REST API (SUPABASE_URL +
// SUPABASE_SECRET_KEY) rather than a Postgres driver — this file is the only
// place that talks to the table directly from Node.
import { db } from "./db";
import type { Job, JobStatus, JobSummary } from "./types";
import { jobSummary } from "./types";

const TABLE = "bible_well_jobs";

let tableReady = false;
async function ensureTable(): Promise<void> {
  if (tableReady) return;
  await db.execute(
    `CREATE TABLE IF NOT EXISTS ${TABLE} (
       id TEXT PRIMARY KEY,
       created_at TEXT NOT NULL,
       status TEXT NOT NULL,
       payload JSONB NOT NULL
     )`,
  );
  tableReady = true;
}

export async function saveJob(job: Job): Promise<void> {
  await ensureTable();
  await db.execute({
    sql: `INSERT INTO ${TABLE} (id, created_at, status, payload) VALUES (?,?,?,?::jsonb)
          ON CONFLICT(id) DO UPDATE SET status=excluded.status, payload=excluded.payload`,
    args: [job.id, job.createdAt, job.status, JSON.stringify(job)],
  });
}

export async function getJob(id: string): Promise<Job | null> {
  await ensureTable();
  const rs = await db.execute({ sql: `SELECT payload FROM ${TABLE} WHERE id = ?`, args: [id] });
  const row = rs.rows[0];
  return row ? (row.payload as Job) : null;
}

export async function listJobs(): Promise<JobSummary[]> {
  await ensureTable();
  const rs = await db.execute(`SELECT payload FROM ${TABLE} ORDER BY created_at DESC`);
  return rs.rows.map((r) => jobSummary(r.payload as Job));
}

export async function setJobStatus(id: string, status: JobStatus, patch?: Partial<Job>): Promise<Job | null> {
  const job = await getJob(id);
  if (!job) return null;
  const next: Job = { ...job, ...patch, status };
  await saveJob(next);
  return next;
}

export async function deleteJob(id: string): Promise<boolean> {
  await ensureTable();
  const rs = await db.execute({ sql: `DELETE FROM ${TABLE} WHERE id = ?`, args: [id] });
  return (rs.rowsAffected ?? 0) > 0;
}
