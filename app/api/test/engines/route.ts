/**
 * Multi-engine desk: engine/corpus catalogue + status (GET), local engine
 * runs against whitelisted fixtures / the defensive property harness, or
 * normalization of pasted engine output (POST). Funds-at-risk triage only.
 */

import path from "node:path";
import { NextResponse } from "next/server";
import { corpusCatalog, ACCEPTANCE_PRIORS } from "@/lib/eth-scanner/desk/corpora";
import { engineCatalog, isEngineId } from "@/lib/eth-scanner/desk/engines";
import { FUNDS_AT_RISK_CLASSES } from "@/lib/eth-scanner/desk/findings";
import { engineStatuses, parsePasted, runDesk, sourceFixtureCatalog } from "@/lib/eth-scanner/desk/runtime";
import { acquireScan, releaseScan, scanInFlight } from "@/lib/eth-scanner/scan-lock";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 300;

const MAX_BODY = 2 * 1024 * 1024 + 4096;

function json(body: unknown, status = 200) {
  return NextResponse.json(body, {
    status,
    headers: { "Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow" },
  });
}

export async function GET() {
  const statuses = engineStatuses();
  const engines = engineCatalog().map((e) => {
    const st = statuses.find((s) => s.id === e.id)!;
    // Never leak absolute host paths — basename only.
    return { ...e, ...st, binary: st.binary ? path.basename(st.binary) : null };
  });
  return json({
    ok: true,
    on_vercel: Boolean(process.env.VERCEL),
    running: scanInFlight(),
    engines,
    corpora: corpusCatalog(),
    classes: FUNDS_AT_RISK_CLASSES,
    priors: ACCEPTANCE_PRIORS,
    fixtures: sourceFixtureCatalog(),
    summary: {
      installed: statuses.filter((s) => s.status === "installed").length,
      stub: statuses.filter((s) => s.status === "stub").length,
      missing: statuses.filter((s) => s.status === "missing").length,
    },
  });
}

export async function POST(req: Request) {
  const text = await req.text();
  if (text.length > MAX_BODY) return json({ ok: false, error: "body too large (2 MB max)" }, 413);
  let body: Record<string, unknown>;
  try {
    const parsed = text ? JSON.parse(text) : {};
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error();
    body = parsed;
  } catch {
    return json({ ok: false, error: "expected a JSON object" }, 400);
  }

  // Paste mode: normalize engine output produced on another machine.
  if (typeof body.output === "string") {
    if (!isEngineId(body.engine)) return json({ ok: false, error: "unknown engine" }, 400);
    return json(parsePasted(body.engine, body.output));
  }

  if (!acquireScan()) return json({ ok: false, error: "a scan is already running" }, 429);
  try {
    const out = await runDesk({ engines: body.engines, fixture: body.fixture });
    return json(out, out.ok ? 200 : 400);
  } finally {
    releaseScan();
  }
}
