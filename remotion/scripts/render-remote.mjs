import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import {
  renderMediaOnLambda,
  getRenderProgress,
} from "@remotion/lambda/client";

const region = process.env.AWS_REGION ?? "us-west-2";
const functionName = process.env.REMOTION_LAMBDA_FUNCTION_NAME;
const serveUrl = process.env.REMOTION_SERVE_URL;
const composition = process.env.REMOTION_COMPOSITION_ID ?? "HeritageScenes";
const POLL_MS = 4000;

const die = (m) => {
  console.error(`[render-remote] ${m}`);
  process.exit(1);
};

// This account has multiple `remotionlambda-*` buckets in us-west-2, so
// auto-detection is ambiguous. Pin output to the bucket hosting the serve
// URL — same pattern as remotion-test-2's render.mjs.
const forceBucketName = serveUrl?.match(/remotionlambda-[a-z0-9-]+/)?.[0];

async function main() {
  if (!functionName) die("REMOTION_LAMBDA_FUNCTION_NAME not set (run deploy:lambda first)");
  if (!serveUrl) die("REMOTION_SERVE_URL not set (run deploy:site first)");

  const scenesPath = path.resolve(process.cwd(), "src/scenes.json");
  const { scenes, narrationUrl } = JSON.parse(await readFile(scenesPath, "utf8"));
  console.log(`[render-remote] composition=${composition} scenes=${scenes.length} narrationUrl=${narrationUrl ?? "(none)"}`);
  console.log(`[render-remote] functionName=${functionName}`);
  console.log(`[render-remote] serveUrl=${serveUrl}`);

  // Sum of per-scene duration_frames (ignores the few-frame crossfade overlap
  // HeritageScenes.tsx trims off the total — close enough for chunk sizing).
  const DEFAULT_SCENE_DURATION_FRAMES = 180;
  const totalDurationInFrames = scenes.reduce(
    (sum, s) => sum + (s.duration_frames ?? DEFAULT_SCENE_DURATION_FRAMES),
    0,
  );

  const start = await renderMediaOnLambda({
    region,
    functionName,
    serveUrl,
    forceBucketName,
    composition,
    inputProps: { scenes, narrationUrl },
    codec: "h264",
    privacy: "public",
    maxRetries: 1,
    // remotion-test-2's benchmarked Lambda cost levers, reused verbatim (no
    // re-benchmark) — same posture as this project's memory/disk sizing in
    // deploy-lambda.mjs.
    imageFormat: "jpeg",
    jpegQuality: 80,
    framesPerLambda: Math.max(80, Math.ceil(totalDurationInFrames / 190)),
    concurrencyPerLambda: 2,
  });

  console.log(`[render-remote] renderId=${start.renderId} bucket=${start.bucketName}`);

  let progress;
  for (;;) {
    try {
      progress = await getRenderProgress({
        renderId: start.renderId,
        bucketName: start.bucketName,
        functionName,
        region,
      });
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      console.warn(`\n[render-remote] progress poll transient error: ${msg} — retrying`);
      await new Promise((r) => setTimeout(r, POLL_MS));
      continue;
    }

    if (progress.fatalErrorEncountered) {
      console.error("\n[render-remote] fatal error:");
      console.error(JSON.stringify(progress.errors, null, 2));
      process.exit(1);
    }

    if (progress.done) {
      console.log(`\n[render-remote] done — ${progress.outputFile}`);
      console.log(
        `[render-remote] cost ~$${progress.costs?.accruedSoFar?.toFixed(4) ?? "?"}`,
      );
      break;
    }

    const pct = Math.round((progress.overallProgress ?? 0) * 100);
    process.stdout.write(`\r[render-remote] ${pct}%  `);
    await new Promise((r) => setTimeout(r, POLL_MS));
  }

  if (!progress?.outputFile) {
    die("render reported done but no outputFile was returned");
  }

  const outDir = path.resolve(process.cwd(), "out");
  await mkdir(outDir, { recursive: true });
  const outPath = path.join(outDir, "preview-lambda.mp4");

  console.log(`[render-remote] downloading ${progress.outputFile} -> ${outPath}`);
  const res = await fetch(progress.outputFile);
  if (!res.ok) die(`download failed: ${res.status} ${res.statusText}`);
  const buf = Buffer.from(await res.arrayBuffer());
  await writeFile(outPath, buf);
  console.log(`[render-remote] saved ${(buf.length / 1024 / 1024).toFixed(2)}MB to ${outPath}`);
}

main().catch((err) => {
  console.error("\n[render-remote] failed:", err);
  process.exit(1);
});
