// Shared forward-to-Python-API logic, used by the catch-all proxy
// (/api/proxy/*) and by the compatibility routes (/ingest, /health) that
// keep external callers (n8n) working against the same bare paths they used
// before the UI and API were combined into one container/one public port.
import { NextRequest, NextResponse } from "next/server";

export async function forward(req: NextRequest, path: string) {
  const base = process.env.PIPELINE_API_URL;
  const secret = process.env.INGEST_SECRET;
  if (!base || !secret) {
    return NextResponse.json(
      { error: "PIPELINE_API_URL/INGEST_SECRET not configured" },
      { status: 500 },
    );
  }
  const target = `${base}/${path}${req.nextUrl.search}`;
  const contentType = req.headers.get("Content-Type") || "application/json";
  const init: RequestInit = {
    method: req.method,
    headers: { "x-ingest-secret": secret, "Content-Type": contentType },
  };
  if (req.method !== "GET" && req.method !== "HEAD") {
    if (contentType.startsWith("application/json")) {
      const body = await req.text();
      if (body) init.body = body;
    } else {
      init.body = await req.arrayBuffer();
    }
  }
  const res = await fetch(target, init);
  const text = await res.text();
  return new NextResponse(text, {
    status: res.status,
    headers: { "Content-Type": "application/json" },
  });
}
