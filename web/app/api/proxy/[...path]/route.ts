// Thin server-side proxy to src/ingest_server.py (the Python pipeline API).
// Every mutation there costs real money (OpenAI, video-gen, Remotion Lambda),
// so it's gated by a shared secret — this proxy is the only place that secret
// lives, kept out of any browser-visible env var or bundle.
import { NextRequest } from "next/server";
import { forward } from "@/lib/proxy-forward";

type Ctx = { params: Promise<{ path: string[] }> };

export async function GET(req: NextRequest, { params }: Ctx) {
  return forward(req, (await params).path.join("/"));
}
export async function POST(req: NextRequest, { params }: Ctx) {
  return forward(req, (await params).path.join("/"));
}
export async function DELETE(req: NextRequest, { params }: Ctx) {
  return forward(req, (await params).path.join("/"));
}
