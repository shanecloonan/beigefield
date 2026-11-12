/**
 * Kick a Lane A scan for one /test address (or a whitelisted local fixture).
 * Defensive only. Spawns python -m eth_scanner (system Python or the
 * portable CPython bundled for Vercel). Never a scanner runtime on GET.
 */

import { NextResponse } from "next/server";
import { capabilityNote, fixtureCatalog, pythonCapability, scannerCapabilities } from "@/lib/eth-scanner/capabilities";
import { latestWrittenReceipt } from "@/lib/eth-scanner/local-store";
import { laneAPersistInput, persistTestScanRun } from "@/lib/eth-scanner/persist-test-results";
import { runLaneA, scanInFlight } from "@/lib/eth-scanner/run-lane-a";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 180;

function json(body: unknown, status = 200) {
  return NextResponse.json(body, {
    status,
    headers: {
      "Cache-Control": "no-store",
      "X-Robots-Tag": "noindex, nofollow",
    },
  });
}

export async function GET() {
  const caps = scannerCapabilities();
  return json({
    ok: true,
    ...caps,
    python_runtime: pythonCapability(),
    running: scanInFlight(),
    fixtures: fixtureCatalog(),
    note: capabilityNote(caps),
  });
}

export async function POST(req: Request) {
  let body: unknown = {};
  try {
    const text = await req.text();
    body = text ? JSON.parse(text) : {};
  } catch {
    return json({ ok: false, error: "invalid json" }, 400);
  }
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    return json({ ok: false, error: "expected a JSON object" }, 400);
  }
  const { address, tvl, fixture } = body as { address?: unknown; tvl?: unknown; fixture?: unknown };
  if (scanInFlight()) {
    return json({ ok: false, error: "a Lane A scan is already running" }, 429);
  }

  const started = Date.now();
  const out = await runLaneA({
    address: typeof address === "string" ? address : undefined,
    tvl: typeof tvl === "number" || typeof tvl === "string" ? Number(tvl) : undefined,
    fixture: typeof fixture === "string" ? fixture : undefined,
  });
  if (!out.ok) {
    const status = /already running/.test(out.error)
      ? 429
      : /pass a 0x|unknown fixture|tvl must/.test(out.error)
        ? 400
        : /unavailable|not importable|could not start|no system Python|portable CPython/.test(out.error)
          ? 503
          : 500;
    return json({ ...out, note: capabilityNote(out) }, status);
  }
  // Serverless instances don't share /tmp, so a follow-up GET to
  // /api/test/receipt can land on a cold instance with no work dir. Inline
  // the receipt this run just wrote so the desk can always download it.
  const written = latestWrittenReceipt(out.result.address);
  const duration_ms = Date.now() - started;
  const payload = {
    ...out,
    duration_ms,
    note: capabilityNote(out),
    receipt_url: `/api/test/receipt?address=${encodeURIComponent(out.result.address)}`,
    receipt_markdown: written?.markdown ?? null,
    receipt_filename: written?.filename ?? null,
  };
  // Soft-fail detailed persist — page must keep working if Supabase is down.
  const persisted = await persistTestScanRun(
    laneAPersistInput({
      ...payload,
      tvl: typeof tvl === "number" || typeof tvl === "string" ? Number(tvl) : null,
    }),
  );
  return json({
    ...payload,
    persist: persisted.ok
      ? {
          ok: true,
          run_id: persisted.run_id,
          findings_count: persisted.findings_count,
          finding_ids: persisted.finding_ids,
        }
      : { ok: false, skipped: persisted.skipped ?? false, error: persisted.error },
  });
}
