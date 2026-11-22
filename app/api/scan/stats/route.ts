/**
 * All-time website scan board. Read-only. Findings are stored already redacted.
 */

import { NextResponse } from "next/server";
import { summarizeSiteHits } from "@/lib/site-scanner/board";
import { createServiceSupabaseClient } from "@/lib/eth-scanner/service-supabase";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function json(body: unknown, status = 200) {
  return NextResponse.json(body, {
    status,
    headers: { "Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow" },
  });
}

export async function GET() {
  const sb = createServiceSupabaseClient();
  if (!sb) {
    return json({ ok: true, connected: false, scanned: 0, leaderboard: [] });
  }
  const { data, error } = await sb
    .from("site_scan_hits")
    .select("host,url,heat,peak_heat,score_state,pending_stages,findings,mode,created_at,updated_at")
    .order("peak_heat", { ascending: false })
    .limit(500);
  if (error) {
    return json({ ok: true, connected: true, scanned: 0, leaderboard: [], note: "site_scan_hits is not ready" });
  }
  const leaderboard = summarizeSiteHits(data ?? [], 100);
  return json({ ok: true, connected: true, scanned: leaderboard.length, leaderboard });
}
