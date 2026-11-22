"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { CHAIN_FILTERS } from "@/lib/eth-scanner/chain-filters";
import { groupByEngineRule } from "@/lib/eth-scanner/desk/blend-groups";
type EngineRow = { engine: string; status: string; note?: string; version_pin?: string };
type Finding = {
  id: string;
  rule: string;
  title: string;
  kind: string;
  label: string;
  severity: string;
  agreement_score: number;
  agreement_count: number;
  engines_agreeing: string[];
  caller_profit_delta: number;
  heat_contribution: number;
  evidence: string;
  engine: string;
  incentive?: { who_benefits?: string; what_breaks?: string } | null;
};

type Board = {
  connected: boolean;
  truncated: boolean;
  scanned: number;
  totals: { yes: number; maybe: number; no: number; other: number };
  leaderboard: {
    address: string;
    chain?: string;
    heat: number;
    bucket: string;
    label: string;
    funds_usd: number | null;
    contract_name: string | null;
    liveness?: string;
    peak_heat?: number;
    history_count?: number;
    scanned_at?: string | null;
    stale?: boolean;
  }[];
  flagged?: {
    address: string;
    chain?: string;
    heat: number;
    label: string;
    liveness?: string;
    contract_name: string | null;
  }[];
  requeue?: { address: string; heat: number; peak_heat?: number }[];
};

type Receipt = {
  schema: string;
  bucket: string;
  heat: number;
  engines: EngineRow[];
  findings: Finding[];
  groups: Finding[];
  target?: { address?: string; contracts?: string[]; funds_usd?: number | null };
  heat_breakdown?: { gate_reason?: string; caller_profit_gate?: boolean };
  adaptations?: Record<string, { version?: string; heat_contribution?: number }>;
};

const BUCKET: Record<string, string> = {
  "drain-found": "text-rose-200 border-rose-800/70",
  maybe: "text-amber-200 border-amber-800/70",
  no: "text-brand-300 border-brand-700",
};

function money(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(value);
}

function Stat({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="rounded-lg border border-brand-800 bg-brand-900/40 px-4 py-3">
      <p className="text-[11px] tracking-[0.16em] uppercase text-brand-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums text-brand-50">{value}</p>
      <p className="mt-1 text-[11px] text-brand-400">{hint}</p>
    </div>
  );
}

export default function BlendApp() {
  const [pins, setPins] = useState<Record<string, { version: string }> | null>(null);
  const [random, setRandom] = useState<{ enabled: boolean; etherscan_configured: boolean; reason: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const [sample, setSample] = useState<{ address: string; contract_name: string | null } | null>(null);
  const [board, setBoard] = useState<Board | null>(null);
  const [chain, setChain] = useState("ethereum");
  const [live, setLive] = useState<{
    phase: string;
    status: string;
    message: string;
    current_address: string;
    random_scanned_this_run: number;
    random_enabled: boolean;
    schedule: string;
    lists: { id: string; name: string; scanned: number; total: number; unscanned: number; buckets: { drain: number; maybe: number; no: number } }[];
    random_stream: { address: string; bucket: string; heat: number; at: string | null }[];
    connected: boolean;
    passes?: string[];
  } | null>(null);

  const loadLive = useCallback(async () => {
    const res = await fetch("/api/blend/status", { cache: "no-store" });
    const body = await res.json();
    if (body.ok) setLive(body);
  }, []);

  const loadBoard = useCallback(async () => {
    const res = await fetch(`/api/blend/stats?chain=${encodeURIComponent(chain)}`, { cache: "no-store" });
    const body = await res.json();
    if (body.ok) setBoard(body);
  }, [chain]);

  const loadCatalog = useCallback(async () => {
    const res = await fetch("/api/blend", { cache: "no-store" });
    const body = await res.json();
    if (!body.ok) {
      setError(body.error || "Blend could not load.");
      return;
    }
    setPins(body.pins);
    setRandom(body.random);
    setError(null);
  }, []);

  useEffect(() => {
    const kick = window.setTimeout(() => {
      void loadCatalog();
      void loadLive();
      void loadBoard();
    }, 0);
    const timer = window.setInterval(() => void loadLive(), 20000);
    const boardTimer = window.setInterval(() => void loadBoard(), 60000);
    return () => {
      window.clearTimeout(kick);
      window.clearInterval(timer);
      window.clearInterval(boardTimer);
    };
  }, [loadCatalog, loadLive, loadBoard]);

  const runRandom = useCallback(async () => {
    setBusy("random");
    setReceipt(null);
    setSample(null);
    const res = await fetch("/api/blend/random", { method: "POST" });
    const body = await res.json();
    setBusy(null);
    if (!body.ok) {
      setError(body.error || "Random scan did not run.");
      return;
    }
    setError(null);
    setSample(body.sample);
    setReceipt(body.receipt);
  }, []);

  const groups = groupByEngineRule(receipt?.findings || receipt?.groups || []);

  return (
    <main className="min-h-screen bg-brand-950 text-brand-100">
      <div className="max-w-[1100px] mx-auto px-5 sm:px-8 pt-10 pb-16">
        <Link href="/" className="inline-block mb-10 text-[11px] tracking-[0.2em] uppercase text-brand-400 hover:text-gold">
          ← Beigefield
        </Link>
        <p className="text-[11px] tracking-[0.2em] uppercase text-gold/80 font-semibold mb-2">
          Beigefield · Blend
        </p>
        <h1 className="text-3xl sm:text-4xl font-semibold tracking-tight text-brand-50">Blend</h1>

        <section className="mt-8" aria-labelledby="board-heading">
          <h2 id="board-heading" className="text-[11px] tracking-[0.2em] uppercase text-gold/80 font-semibold">
            Scans
          </h2>
          <div className="mt-3 grid grid-cols-2 sm:grid-cols-4 gap-3">
            <Stat label="Scanned" value={board ? board.scanned.toLocaleString() : "—"} hint="Finished contracts" />
            <Stat label="Yes" value={board ? board.totals.yes.toLocaleString() : "—"} hint="Drain found" />
            <Stat label="Maybe" value={board ? board.totals.maybe.toLocaleString() : "—"} hint="Heat, no drain" />
            <Stat label="No" value={board ? board.totals.no.toLocaleString() : "—"} hint="Cold" />
          </div>
          {board && board.totals.other > 0 && (
            <p className="mt-2 text-xs text-brand-400">Other {board.totals.other.toLocaleString()}</p>
          )}

          {board && (board.flagged || []).length > 0 && (
            <div className="mt-6">
              <h3 className="text-[11px] tracking-[0.2em] uppercase text-brand-400 font-semibold">
                Already drained
              </h3>
              <ul className="mt-2 space-y-1 text-xs">
                {(board.flagged || []).slice(0, 20).map((row) => (
                  <li key={`${row.chain || "ethereum"}:${row.address}`} className="flex items-baseline justify-between gap-3 border-t border-brand-800/60 py-1.5">
                    <span className="min-w-0">
                      {row.contract_name && <span className="mr-2 text-brand-200">{row.contract_name}</span>}
                      <span className="font-mono text-[10px] text-brand-400">{row.address}</span>
                    </span>
                    <span className="shrink-0 uppercase tracking-wider text-brand-400">
                      {row.liveness === "dead" ? "Dead" : "Exploited"}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="mt-8 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <h3 className="text-[11px] tracking-[0.2em] uppercase text-gold/80 font-semibold">
              Highest heat
            </h3>
            <div className="flex flex-wrap gap-1 text-[10px] uppercase tracking-[0.14em]">
              {CHAIN_FILTERS.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setChain(item.id)}
                  className={`rounded border px-1.5 py-1 sm:px-2 ${chain === item.id ? "border-gold/60 text-brand-100" : "border-brand-800 text-brand-500"}`}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>
          <div className="mt-3 overflow-x-auto rounded-lg border border-brand-800/80 max-h-[32rem]">
            <table className="w-full text-xs">
              <thead className="bg-brand-900/80 text-brand-400 text-left sticky top-0">
                <tr>
                  <th className="px-3 py-2 w-10">#</th>
                  <th className="px-3 py-2">Contract</th>
                  <th className="px-3 py-2">Chain</th>
                  <th className="px-3 py-2">Heat</th>
                  <th className="px-3 py-2 hidden sm:table-cell">Latest</th>
                  <th className="px-3 py-2 hidden sm:table-cell">Result</th>
                  <th className="px-3 py-2">Funds</th>
                </tr>
              </thead>
              <tbody>
                {(board?.leaderboard || []).map((row, index) => (
                  <tr key={`${row.chain || "ethereum"}:${row.address}`} className="border-t border-brand-800/60">
                    <td className="px-3 py-2 text-brand-500 tabular-nums">{index + 1}</td>
                    <td className="px-3 py-2">
                      {row.contract_name && <span className="block text-brand-100">{row.contract_name}</span>}
                      <span className="block font-mono text-[10px] text-brand-400">{row.address}</span>
                    </td>
                    <td className="px-3 py-2 uppercase tracking-wider text-brand-400">{row.chain || "ethereum"}</td>
                    <td className="px-3 py-2 tabular-nums text-brand-100">
                      {row.peak_heat ?? row.heat}
                      {row.liveness && row.liveness !== "live" ? (
                        <span className="mt-0.5 block text-[10px] uppercase tracking-wider text-brand-500">
                          {row.liveness === "dead" ? "Dead" : "Exploited"}
                        </span>
                      ) : null}
                      {row.stale ? <span className="mt-0.5 block text-[10px] uppercase tracking-wider text-brand-500">Stale</span> : null}
                    </td>
                    <td className="px-3 py-2 tabular-nums text-brand-400 hidden sm:table-cell">{row.heat}</td>
                    <td className="px-3 py-2 hidden sm:table-cell">
                      <span className={`inline-block rounded border px-2 py-0.5 uppercase tracking-wider ${BUCKET[row.bucket] || BUCKET.no}`}>
                        {row.label}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-brand-200">{money(row.funds_usd)}</td>
                  </tr>
                ))}
                {!board && (
                  <tr>
                    <td colSpan={7} className="px-3 py-6 text-center text-brand-500">
                      Loading scans.
                    </td>
                  </tr>
                )}
                {board && board.leaderboard.length === 0 && (
                  <tr>
                    <td colSpan={7} className="px-3 py-6 text-center text-brand-500">
                      No finished scans yet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>

        <section className="mt-8 rounded-lg border border-brand-800 bg-brand-900/40 p-4" aria-labelledby="live-heading">
          <h2 id="live-heading" className="text-[11px] tracking-[0.2em] uppercase text-gold/80 font-semibold">
            Automatic pipeline
          </h2>
          <p className="mt-2 text-sm text-brand-200">
            {live?.phase || "scheduled"} · {live?.status || "scheduled"}
            {live?.current_address ? ` · ${live.current_address}` : ""}
            {" · "}random {live?.random_scanned_this_run ?? 0}
          </p>
        </section>
        {error && <p className="mt-4 text-sm text-rose-300">{error}</p>}

        <section className="mt-12" aria-labelledby="random-heading">
          <h2 id="random-heading" className="text-[11px] tracking-[0.2em] uppercase text-gold/80 font-semibold mb-3">
            Scanning random contracts
          </h2>
          <div className="rounded-lg border border-brand-800 bg-brand-900/30 p-4">
            <ul className="space-y-1 text-xs">
              {(live?.random_stream || []).map((row) => (
                <li key={`${row.at}-${row.address}`} className="font-mono text-brand-300">
                  {row.address} · {row.bucket} · heat {row.heat}
                </li>
              ))}
              {(live?.random_stream || []).length === 0 && (
                <li className="text-brand-500">No random contracts recorded yet.</li>
              )}
            </ul>
            <button
              type="button"
              disabled={!random?.enabled || !random.etherscan_configured || busy === "random"}
              onClick={() => void runRandom()}
              className="mt-4 rounded-md border border-brand-700 px-4 py-2 text-[11px] uppercase tracking-[0.14em] text-brand-300 disabled:text-brand-600"
            >
              {busy === "random" ? "Sampling" : "Run now"}
            </button>
            {sample && (
              <p className="mt-3 text-xs text-brand-400">
                {sample.contract_name || "Verified contract"} · <span className="font-mono">{sample.address}</span>
              </p>
            )}
          </div>
        </section>

        {receipt && (
          <section className="mt-10" aria-label="Receipt">
            <h2 className="text-[11px] tracking-[0.2em] uppercase text-gold/80 font-semibold mb-3">Receipt</h2>
            <p className="text-sm text-brand-200">
              Bucket <span className="uppercase">{receipt.bucket}</span>
              {" · "}heat {receipt.heat}
              {receipt.heat_breakdown?.gate_reason ? ` · ${receipt.heat_breakdown.gate_reason}` : ""}
            </p>
            {receipt.adaptations && (
              <ul className="mt-3 flex flex-wrap gap-2 text-[11px] text-brand-400">
                {Object.entries(receipt.adaptations).map(([name, block]) => (
                  <li key={name} className="rounded border border-brand-800 px-2 py-1">
                    {name} · {block.version || "pinned"} · heat {block.heat_contribution ?? 0}
                  </li>
                ))}
              </ul>
            )}
            <ul className="mt-3 flex flex-wrap gap-2 text-[11px]">
              {receipt.engines.map((engine) => (
                <li key={engine.engine} className="rounded border border-brand-800 px-2 py-1 text-brand-300">
                  {engine.engine} {engine.version_pin ? `· ${engine.version_pin.slice(0, 18)}` : ""} · {engine.status}
                </li>
              ))}
            </ul>
            <div className="mt-4 overflow-x-auto rounded-lg border border-brand-800/80">
              <table className="w-full text-xs">
                <thead className="bg-brand-900/60 text-brand-400 text-left">
                  <tr>
                    <th className="px-3 py-2">Engine</th>
                    <th className="px-3 py-2">Rule</th>
                    <th className="px-3 py-2">Agreement</th>
                    <th className="px-3 py-2">Label</th>
                  </tr>
                </thead>
                <tbody>
                  {groups.map((row) => (
                    <tr key={`${row.engine}:${row.rule}`} className="border-t border-brand-800/60">
                      <td className="px-3 py-2 text-brand-100">{row.engine}</td>
                      <td className="px-3 py-2 text-brand-300">{row.rule}</td>
                      <td className="px-3 py-2 font-mono">{row.agreement_score.toFixed(2)} · {row.engines_agreeing.join(", ")}</td>
                      <td className="px-3 py-2">{row.label}</td>
                    </tr>
                  ))}
                  {groups.length === 0 && (
                    <tr>
                      <td colSpan={4} className="px-3 py-6 text-center text-brand-500">
                        None
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {pins && (
          <p className="mt-10 text-[11px] text-brand-500">
            Pins {Object.entries(pins).map(([name, row]) => `${name} ${row.version}`).join(" · ")}
          </p>
        )}
      </div>
    </main>
  );
}
