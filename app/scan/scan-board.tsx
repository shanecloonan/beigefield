import Link from "next/link";
import type { SiteRow } from "@/lib/site-scanner/board";

type SiteBoard = {
  connected: boolean;
  note: string;
  leaderboard: SiteRow[];
  runs: { run_id: string; started_at: string | null; finished_at: string | null; hosts_scanned: number; finding_count: number }[];
};

export default function ScanBoard({ board }: { board: SiteBoard }) {
  const rows = board.leaderboard;
  return (
    <main className="min-h-screen bg-brand-950 text-brand-100">
      <div className="max-w-[1100px] mx-auto px-5 sm:px-8 pt-10 pb-16">
        <Link href="/" className="inline-block mb-10 text-[11px] tracking-[0.2em] uppercase text-brand-400 hover:text-gold">
          ← Beigefield
        </Link>
        <p className="text-[11px] tracking-[0.2em] uppercase text-gold/80 font-semibold mb-2">Beigefield · Scan</p>
        <h1 className="text-3xl sm:text-4xl font-semibold tracking-tight text-brand-50">Scan</h1>
        <p className="mt-3 max-w-2xl text-sm text-brand-300">
          Public pages are checked for headers, cookies, TLS, libraries, and leaked tokens.
          Heat is the evidence. Active path checks run only on owned or in-scope hosts. Secrets are redacted.
        </p>
        <p className="mt-2 text-[11px] text-brand-500">
          {board.connected ? "Store connected." : "Store not configured. The board fills after the scheduled job writes."}
          {board.note ? ` ${board.note}` : ""}
        </p>

        <h2 className="mt-8 text-[11px] tracking-[0.14em] uppercase text-brand-500">Recent runs</h2>
        <div className="mt-2 overflow-x-auto rounded-lg border border-brand-800">
          <table className="w-full text-left text-sm">
            <thead className="text-[11px] tracking-[0.14em] uppercase text-brand-500">
              <tr>
                <th className="px-3 py-2">Started</th>
                <th className="px-3 py-2">Finished</th>
                <th className="px-3 py-2">Hosts</th>
                <th className="px-3 py-2">Findings</th>
              </tr>
            </thead>
            <tbody>
              {board.runs.length === 0 ? (
                <tr>
                  <td className="px-3 py-6 text-brand-400" colSpan={4}>No scans recorded yet.</td>
                </tr>
              ) : board.runs.map((run) => (
                <tr key={run.run_id} className="border-t border-brand-800">
                  <td className="px-3 py-2 text-brand-300">{run.started_at || "—"}</td>
                  <td className="px-3 py-2 text-brand-300">{run.finished_at || "—"}</td>
                  <td className="px-3 py-2 tabular-nums">{run.hosts_scanned}</td>
                  <td className="px-3 py-2 tabular-nums">{run.finding_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="mt-8 overflow-x-auto rounded-lg border border-brand-800">
          <table className="w-full text-left text-sm">
            <thead className="text-[11px] tracking-[0.14em] uppercase text-brand-500">
              <tr>
                <th className="px-3 py-2">Host</th>
                <th className="px-3 py-2">Heat</th>
                <th className="px-3 py-2">Peak</th>
                <th className="px-3 py-2">Mode</th>
                <th className="px-3 py-2">Score</th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 ? (
                <tr>
                  <td className="px-3 py-6 text-brand-400" colSpan={5}>No hits stored yet.</td>
                </tr>
              ) : rows.map((row) => (
                <tr key={row.host} className="border-t border-brand-800">
                  <td className="px-3 py-2 font-mono text-xs text-brand-100">{row.host}</td>
                  <td className="px-3 py-2 tabular-nums">{row.heat}</td>
                  <td className="px-3 py-2 tabular-nums">{row.peak_heat}</td>
                  <td className="px-3 py-2 text-brand-300">{row.mode}</td>
                  <td className="px-3 py-2 text-brand-300">
                    {row.score_state || "—"}
                    {row.pending_stages?.length ? ` · pending ${row.pending_stages.join(", ")}` : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="mt-8 space-y-4">
          {rows.map((row) => (
            <section key={row.host} className="rounded-lg border border-brand-800 bg-brand-900/40 p-4">
              <h2 className="text-lg text-brand-50">{row.host}</h2>
              <p className="mt-1 text-xs text-brand-400">
                Heat {row.heat} · peak {row.peak_heat}
                {row.scanned_at ? ` · ${row.scanned_at}` : ""}
              </p>
              {row.tech.length > 0 ? (
                <p className="mt-2 text-xs text-brand-300">
                  {row.tech.map((item) => (
                    <span key={`${item.name}-${item.version}-${item.source}`} className="mr-3">
                      {item.name}{item.version ? ` ${item.version}` : ""}
                      {item.eol ? " · end of life" : ""}
                    </span>
                  ))}
                </p>
              ) : null}
              {row.render ? (
                <p className="mt-2 text-xs text-brand-300">
                  {row.render.status === "challenged"
                    ? "Render stopped on a bot check."
                    : `Rendered · ${row.render.scripts} scripts · ${row.render.console_errors} console errors`}
                  {row.render.storage_keys.length ? ` · storage ${row.render.storage_keys.join(", ")}` : ""}
                </p>
              ) : null}
              <ul className="mt-4 space-y-3">
                {(row.findings || []).length === 0 ? (
                  <li className="text-sm text-brand-400">No evidence facts on this hit.</li>
                ) : row.findings.map((item) => (
                  <li key={item.id || item.title} className="text-sm">
                    <p className="text-brand-50">
                      {item.title} <span className="text-brand-500">+{item.heat ?? 0}</span>
                      {item.stage ? <span className="text-brand-500"> · {item.stage}</span> : null}
                    </p>
                    <p className="text-brand-300">{item.evidence}</p>
                    <p className="text-brand-400">{item.remediation}</p>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      </div>
    </main>
  );
}
