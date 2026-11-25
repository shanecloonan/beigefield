import "server-only";

import { createServiceSupabaseClient } from "@/lib/eth-scanner/service-supabase";
import { summarizeRuns, summarizeSiteHits, type SiteRow, type SiteRun } from "./board";

export type SiteBoard = {
  connected: boolean;
  note: string;
  leaderboard: SiteRow[];
  runs: SiteRun[];
};

/** The same service client Blend uses. The page renders this directly so curl sees the rows. */
export async function loadSiteBoard(): Promise<SiteBoard> {
  const sb = createServiceSupabaseClient();
  if (!sb) return { connected: false, note: "", leaderboard: [], runs: [] };
  const { data, error } = await sb
    .from("site_scan_hits")
    .select("host,url,heat,peak_heat,score_state,pending_stages,findings,heat_breakdown,mode,created_at,updated_at")
    .order("peak_heat", { ascending: false })
    .limit(500);
  const history = await sb
    .from("site_scan_runs")
    .select("run_id,started_at,finished_at,hosts_scanned,finding_count")
    .order("started_at", { ascending: false })
    .limit(12);
  let note = "";
  if (error) note = "site_scan_hits is not ready";
  else if (history.error) note = "scan history is not ready";
  return {
    connected: true,
    note,
    leaderboard: error ? [] : summarizeSiteHits(data ?? [], 100),
    runs: history.error ? [] : summarizeRuns(history.data ?? []),
  };
}
