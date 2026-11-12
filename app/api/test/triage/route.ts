/**
 * Update triage status for a persisted /test finding.
 * Service-role writes only. Fail soft when Supabase is unset/down.
 */

import { NextResponse } from "next/server";
import {
  TRIAGE_STATUSES,
  type TriageStatus,
  updateFindingTriage,
} from "@/lib/eth-scanner/persist-test-results";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function json(body: unknown, status = 200) {
  return NextResponse.json(body, {
    status,
    headers: {
      "Cache-Control": "no-store",
      "X-Robots-Tag": "noindex, nofollow",
    },
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

  const { finding_id, to_status, note, actor } = body as {
    finding_id?: unknown;
    to_status?: unknown;
    note?: unknown;
    actor?: unknown;
  };

  if (typeof finding_id !== "string" || !finding_id.trim()) {
    return json({ ok: false, error: "finding_id required" }, 400);
  }
  if (typeof to_status !== "string" || !TRIAGE_STATUSES.includes(to_status as TriageStatus)) {
    return json({ ok: false, error: `to_status must be one of: ${TRIAGE_STATUSES.join(", ")}` }, 400);
  }

  const out = await updateFindingTriage({
    finding_id: finding_id.trim(),
    to_status: to_status as TriageStatus,
    note: typeof note === "string" ? note : null,
    actor: typeof actor === "string" ? actor : "desk",
  });

  if (!out.ok) {
    const status = out.skipped ? 503 : /not found/i.test(out.error) ? 404 : 500;
    return json(out, status);
  }
  return json(out);
}
