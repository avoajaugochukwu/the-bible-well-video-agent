// Thin server-side proxy to src/ingest_server.py (the Python pipeline API).
// Every mutation there costs real money (OpenAI, video-gen, Remotion Lambda),
// so it's gated by a shared secret — this proxy is the only place that secret
// lives, kept out of any browser-visible env var or bundle.
import { NextRequest, NextResponse } from "next/server";

async function forward(req: NextRequest, path: string[]) {
  const base = process.env.PIPELINE_API_URL;
  const secret = process.env.INGEST_SECRET;
  if (!base || !secret) {
    return NextResponse.json(
      { error: "PIPELINE_API_URL/INGEST_SECRET not configured" },
      { status: 500 },
    );
  }
  const target = `${base}/${path.join("/")}${req.nextUrl.search}`;
  const init: RequestInit = {
    method: req.method,
    headers: { "x-ingest-secret": secret, "Content-Type": "application/json" },
  };
  if (req.method !== "GET" && req.method !== "HEAD") {
    const body = await req.text();
    if (body) init.body = body;
  }
  const res = await fetch(target, init);
  const text = await res.text();
  return new NextResponse(text, {
    status: res.status,
    headers: { "Content-Type": "application/json" },
  });
}

type Ctx = { params: Promise<{ path: string[] }> };

export async function GET(req: NextRequest, { params }: Ctx) {
  return forward(req, (await params).path);
}
export async function POST(req: NextRequest, { params }: Ctx) {
  return forward(req, (await params).path);
}
export async function DELETE(req: NextRequest, { params }: Ctx) {
  return forward(req, (await params).path);
}
