/**
 * One verified-contract sample for the /test Lane A button.
 * Read-only Etherscan lookup. Does not start a scan and does not persist.
 * The page posts the returned address to POST /api/test/run itself, once.
 */

import { NextResponse } from "next/server";
import { EtherscanSampleError, sampleErrorStatus, sampleVerifiedContract } from "@/lib/eth-scanner/random-verified";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 60;

function json(body: unknown, status = 200) {
  return NextResponse.json(body, {
    status,
    headers: {
      "Cache-Control": "no-store",
      "X-Robots-Tag": "noindex, nofollow",
    },
  });
}

export function GET() {
  return json(
    { ok: false, error: "POST once to sample a contract. This route does not scan and does not repeat." },
    405,
  );
}

export async function POST() {
  try {
    const sample = await sampleVerifiedContract();
    return json({ ok: true, ...sample });
  } catch (err) {
    if (err instanceof EtherscanSampleError) {
      return json({ ok: false, error: err.message, kind: err.kind }, sampleErrorStatus(err));
    }
    return json(
      { ok: false, error: "Couldn't pick a verified contract. Click again — nothing was scanned." },
      502,
    );
  }
}
