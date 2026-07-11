import path from "node:path";
import { deploySite } from "@remotion/lambda";

const region = process.env.AWS_REGION ?? "us-west-2";
const siteName = process.env.REMOTION_SITE_NAME ?? "heritage-render";
// Reuse the existing Remotion Lambda site bucket already in use on this
// account — do not create/getOrCreate a new one.
const bucketName =
  process.env.REMOTION_RENDER_BUCKET ?? "remotionlambda-uswest2-wwdsm4roaj";

async function main() {
  console.log(`[deploy-site] region=${region} siteName=${siteName}`);
  console.log(`[deploy-site] bucket=${bucketName}`);
  const entryPoint = path.resolve(process.cwd(), "src/index.ts");

  const { serveUrl, siteName: deployedName } = await deploySite({
    bucketName,
    entryPoint,
    region,
    siteName,
    options: {
      onBundleProgress: (progress) => {
        if (progress % 10 === 0) console.log(`  bundling ${progress}%`);
      },
      onUploadProgress: ({ sizeUploaded, totalSize }) => {
        const pct = Math.round((sizeUploaded / totalSize) * 100);
        if (pct % 10 === 0) console.log(`  uploading ${pct}%`);
      },
    },
  });

  console.log(`[deploy-site] deployed as "${deployedName}"`);
  console.log("");
  console.log("Add this to your .env:");
  console.log(`REMOTION_SERVE_URL=${serveUrl}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
