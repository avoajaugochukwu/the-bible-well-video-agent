import { deployFunction, getFunctions } from "@remotion/lambda";

const region = process.env.AWS_REGION ?? "us-west-2";

async function main() {
  console.log(`[deploy-lambda] region=${region}`);

  const existing = await getFunctions({ region, compatibleOnly: true });
  for (const fn of existing) {
    console.log(`[deploy-lambda] existing function: ${fn.functionName}`);
  }

  const { functionName, alreadyExisted } = await deployFunction({
    region,
    timeoutInSeconds: 900,
    // Same combo remotion-test-2 benchmarked: ~30% cheaper than 10240 at
    // bit-identical output, validated OOM-free. Reused here, no re-benchmark.
    memorySizeInMb: 3072,
    createCloudWatchLogGroup: true,
    diskSizeInMb: 10240,
  });

  console.log(
    `[deploy-lambda] ${alreadyExisted ? "reused" : "deployed"} function: ${functionName}`,
  );
  console.log("");
  console.log("Add this to your .env:");
  console.log(`REMOTION_LAMBDA_FUNCTION_NAME=${functionName}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
