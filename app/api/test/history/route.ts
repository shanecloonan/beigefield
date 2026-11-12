/**
 * Read detailed /test scan history from Supabase (service role).
 */

import { NextResponse } from "next/server";
import { loadTestScanHistory, type TestScanKind } from "@/lib/eth-scanner/persist-test-results";
import { serviceSupabaseConfigured } from "@/lib/eth-scanner/service-supabase";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const KINDS = new Set(["lane-a", "research", "engines", "engines-paste"]);

function json(body: unknown, status = 200) {
  return NextResponse.json(body, {
    status,
    headers: {
      "Cache-Control": "no-store",
      "X-Robots-Tag": "noindex, nofollow",
    },
  });
}

export async function GET(req: Request) {
  const url = new URL(req.url);
  const kindRaw = url.searchParams.get("kind");
  const address = url.searchParams.get("address");
  const limit = Number(url.searchParams.get("limit") || 40);

  if (!serviceSupabaseConfigured()) {
    return json({
      ok: true,
      configured: false,
      runs: [],
      findings: [],
      note: "Supabase service credentials unset — no remote history.",
    });
  }

  const kind = kindRaw && KINDS.has(kindRaw) ? (kindRaw as TestScanKind) : null;
  const out = await loadTestScanHistory({
    kind,
    address,
    limit: Number.isFinite(limit) ? limit : 40,
  });

  return json({
    ok: out.ok,
    configured: true,
    runs: out.runs,
    findings: out.findings,
    error: out.error,
    skipped: out.skipped,
  });
}
