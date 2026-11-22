import "server-only";

import { createServiceSupabaseClient } from "@/lib/eth-scanner/service-supabase";
import { summarizeSiteHits, type SiteRow } from "./board";

export type SiteBoard = {
  connected: boolean;
  note: string;
  leaderboard: SiteRow[];
};

/** The same service client Blend uses. The page renders this directly so curl sees the rows. */
export async function loadSiteBoard(): Promise<SiteBoard> {
  const sb = createServiceSupabaseClient();
  if (!sb) return { connected: false, note: "", leaderboard: [] };
  const { data, error } = await sb
    .from("site_scan_hits")
    .select("host,url,heat,peak_heat,score_state,pending_stages,findings,mode,created_at,updated_at")
    .order("peak_heat", { ascending: false })
    .limit(500);
  if (error) return { connected: true, note: "site_scan_hits is not ready", leaderboard: [] };
  return { connected: true, note: "", leaderboard: summarizeSiteHits(data ?? [], 100) };
}
