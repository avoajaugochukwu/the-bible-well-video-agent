// Shared Supabase (Postgres) client — same pattern as military/lib/db.ts,
// same Supabase project, this app's own table (bible_well_jobs).
import { Pool, type QueryResult } from "pg";

export type InStatement = string | { sql: string; args?: unknown[] };

let pool: Pool | null = null;

// ponytail: lazy init so importing siblings offline (tests) doesn't throw on
// missing env — we only require the connection string when a query actually runs.
function getPool(): Pool {
  if (pool) return pool;
  const connectionString = process.env.SUPABASE_DB_URL;
  if (!connectionString) throw new Error("SUPABASE_DB_URL is not configured");
  pool = new Pool({
    connectionString,
    ssl: { rejectUnauthorized: false }, // Supabase serves a non-system CA
    max: 5,
    idleTimeoutMillis: 30_000,
  });
  pool.on("error", () => {}); // idle-client drops are handled by the retry below
  return pool;
}

const TRANSIENT = [
  "ECONNRESET",
  "ETIMEDOUT",
  "EPIPE",
  "ENOTFOUND",
  "Connection terminated",
  "socket hang up",
  "server closed the connection",
  "timeout exceeded when trying to connect",
];

export function isTransient(err: unknown): boolean {
  const parts: string[] = [];
  let e: unknown = err;
  // Walk the cause chain — pg wraps the underlying socket error.
  for (let i = 0; e && i < 4; i++) {
    const o = e as { code?: unknown; message?: unknown; cause?: unknown };
    if (o.code) parts.push(String(o.code));
    if (o.message) parts.push(String(o.message));
    e = o.cause;
  }
  const hay = parts.join(" ");
  return TRANSIENT.some((m) => hay.includes(m));
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Rewrite `?` placeholders to Postgres `$1, $2, ...` — same convention as military. */
function toPgSql(sql: string): string {
  let i = 0;
  return sql.replace(/\?/g, () => `$${++i}`);
}

async function run(stmt: InStatement): Promise<QueryResult> {
  const { sql, args } = typeof stmt === "string" ? { sql: stmt, args: [] } : stmt;
  return getPool().query(toPgSql(sql), (args ?? []) as unknown[]);
}

async function execute(stmt: InStatement) {
  const delays = [100, 300, 800]; // 3 retries after the first attempt
  let lastErr: unknown;
  for (let attempt = 0; attempt <= delays.length; attempt++) {
    try {
      const res = await run(stmt);
      return { rows: res.rows as Record<string, unknown>[], rowsAffected: res.rowCount ?? 0 };
    } catch (err) {
      lastErr = err;
      if (attempt === delays.length || !isTransient(err)) throw err;
      const base = delays[attempt];
      await sleep(base + Math.floor(Math.random() * base)); // jitter
    }
  }
  throw lastErr;
}

export const db = { execute };
