// One-off: creates bible_well_jobs in Supabase if it doesn't exist yet, then
// exits. `npx tsx scripts/ensure-table.ts` (needs web/.env.local loaded).
import { config } from "dotenv";
config({ path: ".env.local" });
import { db } from "../lib/db";

async function main() {
  await db.execute(
    `CREATE TABLE IF NOT EXISTS bible_well_jobs (
       id TEXT PRIMARY KEY,
       created_at TEXT NOT NULL,
       status TEXT NOT NULL,
       payload JSONB NOT NULL
     )`,
  );
  const rs = await db.execute(
    `SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'bible_well_jobs' ORDER BY ordinal_position`,
  );
  console.log("bible_well_jobs columns:", rs.rows);
  process.exit(0);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
