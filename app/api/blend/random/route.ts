import { NextResponse } from "next/server";
import { sampleVerifiedContract, EtherscanSampleError, sampleErrorStatus } from "@/lib/eth-scanner/random-verified";
import { blendEtherscanKeys, blendRandomEnabled, runBlendCli } from "@/lib/eth-scanner/run-blend";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 300;

function json(body: unknown, status = 200) {
  return NextResponse.json(body, {
    status,
    headers: { "Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow" },
  });
}

export async function POST() {
  if (!blendRandomEnabled()) {
    return json(
      {
        ok: false,
        error: "Random scanning is off. Set ETH_SCANNER_BLEND_RANDOM=1 to pull one verified contract through the gauntlet.",
      },
      403,
    );
  }
  const keys = blendEtherscanKeys();
  if (!keys) {
    return json(
      {
        ok: false,
        error: "No Etherscan API key is set. Add ETHERSCAN_API_KEYS to the environment. Nothing was scanned.",
      },
      503,
    );
  }
  try {
    const sample = await sampleVerifiedContract({ keys });
    const ran = await runBlendCli(["--address", sample.address, "--json"], 180_000);
    if (!ran.ok) return json({ ok: false, error: ran.error, sample }, 503);
    return json({ ok: true, sample, receipt: ran.data });
  } catch (err) {
    if (err instanceof EtherscanSampleError) {
      return json({ ok: false, error: err.message }, sampleErrorStatus(err));
    }
    const message = err instanceof Error ? err.message : "The random sample failed.";
    return json({ ok: false, error: message }, 502);
  }
}
