/**
 * All-time website scan board. Read-only. Findings are stored already redacted.
 */

import { NextResponse } from "next/server";
import { loadSiteBoard } from "@/lib/site-scanner/load";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  const board = await loadSiteBoard();
  return NextResponse.json(
    {
      ok: true,
      connected: board.connected,
      scanned: board.leaderboard.length,
      note: board.note || undefined,
      leaderboard: board.leaderboard,
    },
    { headers: { "Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow" } },
  );
}
