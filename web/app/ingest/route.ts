// Compatibility passthrough: n8n calls POST /ingest directly (predates this
// UI). Now that the UI and the Python API share one container/one public
// port, this just forwards to the Python service the same way /api/proxy
// does, so n8n's existing webhook URL keeps working unchanged.
import { NextRequest } from "next/server";
import { forward } from "@/lib/proxy-forward";

export async function POST(req: NextRequest) {
  return forward(req, "ingest");
}
