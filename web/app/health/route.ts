// Compatibility passthrough for external health checks against the old bare
// /health path — see app/ingest/route.ts for why this exists.
import { NextRequest } from "next/server";
import { forward } from "@/lib/proxy-forward";

export async function GET(req: NextRequest) {
  return forward(req, "health");
}
