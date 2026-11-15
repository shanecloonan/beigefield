"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { groupByEngineRule } from "@/lib/eth-scanner/desk/blend-groups";
import { SCAN_LISTS, type ScanListId } from "@/lib/eth-scanner/scan-lists";

type ListCard = {
  id: ScanListId;
  name: string;
  kind: string;
  blurb: string;
  min_usd: number | null;
  max_usd: number | null;
  count?: number;
  deep_count?: number;
};

type ContractRow = {
  address: string;
  protocol: string;
  est_usd_held: number;
  tier: number;
  candidate_reason: string;
  deep_lane: boolean;
  bucket: string;
  fixture?: string | null;
  list_id: string;
};

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

export default function BlendApp() {
  const [lists, setLists] = useState<ListCard[] | null>(null);
  const [pins, setPins] = useState<Record<string, { version: string }> | null>(null);
  const [random, setRandom] = useState<{ enabled: boolean; etherscan_configured: boolean; reason: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<ScanListId | null>(null);
  const [contracts, setContracts] = useState<ContractRow[]>([]);
  const [total, setTotal] = useState(0);
  const [busy, setBusy] = useState<string | null>(null);
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const [sample, setSample] = useState<{ address: string; contract_name: string | null } | null>(null);
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
  } | null>(null);

  const loadLive = useCallback(async () => {
    const res = await fetch("/api/blend/status", { cache: "no-store" });
    const body = await res.json();
    if (body.ok) setLive(body);
  }, []);

  const loadCatalog = useCallback(async () => {
    const res = await fetch("/api/blend", { cache: "no-store" });
    const body = await res.json();
    if (!body.ok) {
      setError(body.error || "Blend could not load the lists.");
      return;
    }
    setLists(body.lists);
    setPins(body.pins);
    setRandom(body.random);
    setError(null);
  }, []);

  useEffect(() => {
    void loadCatalog();
    void loadLive();
    const timer = setInterval(() => void loadLive(), 20000);
    return () => clearInterval(timer);
  }, [loadCatalog, loadLive]);

  const openList = useCallback(async (id: ScanListId) => {
    setOpen(id);
    setReceipt(null);
    setBusy("list");
    const res = await fetch(`/api/blend?list=${id}&limit=40`, { cache: "no-store" });
    const body = await res.json();
    setBusy(null);
    if (!body.ok) {
      setError(body.error || "That list could not be opened.");
      return;
    }
    setContracts(body.contracts || []);
    setTotal(body.total || 0);
  }, []);

  const runRow = useCallback(async (row: ContractRow) => {
    setBusy(row.address);
    setReceipt(null);
    const res = await fetch("/api/blend", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        address: row.address,
        list: row.list_id,
        fixture: row.fixture || undefined,
      }),
    });
    const body = await res.json();
    setBusy(null);
    if (!body.ok) {
      setError(body.error || "The gauntlet did not finish.");
      return;
    }
    const next = body.receipt as Receipt;
    setReceipt(next);
    setContracts((prev) => prev.map((item) => (item.address === row.address ? { ...item, bucket: next.bucket } : item)));
  }, []);

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
  const active = SCAN_LISTS.find((row) => row.id === open) || lists?.find((row) => row.id === open);

  return (
    <main className="min-h-screen bg-brand-950 text-brand-100">
      <div className="max-w-[1100px] mx-auto px-5 sm:px-8 pt-10 pb-16">
        <Link href="/" className="inline-block mb-10 text-[11px] tracking-[0.2em] uppercase text-brand-400 hover:text-gold">
          ← Beigefield
        </Link>
        <p className="text-[11px] tracking-[0.2em] uppercase text-gold/80 font-semibold mb-2">
          Beigefield · Ethereum only · Blend
        </p>
        <h1 className="text-3xl sm:text-4xl font-semibold tracking-tight text-brand-50">Blend</h1>
        <p className="mt-3 max-w-2xl text-sm text-brand-400 leading-relaxed">
          One automatic gauntlet: Ityfuzz, Halmos, Medusa, Echidna, then the syzkaller, RESTler,
          Daikon, Lithium, and Jepsen passes. The scheduled jobs walk List 1, then List 2, then
          random contracts, and pick a list up again when its fingerprint changes. This page watches
          that loop. Local forks only. Heat moves only when an unprivileged caller ends with more
          value than they started. The desk stays on <Link href="/test" className="text-gold hover:text-gold/80">/test</Link>.
        </p>
        <section className="mt-8 rounded-lg border border-brand-800 bg-brand-900/40 p-4" aria-labelledby="live-heading">
          <h2 id="live-heading" className="text-[11px] tracking-[0.2em] uppercase text-gold/80 font-semibold">
            Automatic pipeline
          </h2>
          <p className="mt-2 text-sm text-brand-200">
            {live?.phase || "scheduled"} · {live?.status || "scheduled"}
            {live?.current_address ? ` · ${live.current_address}` : ""}
          </p>
          <p className="mt-1 text-sm text-brand-400">{live?.message || "Loading the scheduled run."}</p>
          <p className="mt-2 text-[11px] text-brand-500">{live?.schedule}</p>
          <ul className="mt-3 grid gap-2 sm:grid-cols-2 text-xs text-brand-300">
            {(live?.lists || []).map((list) => (
              <li key={list.id} className="rounded border border-brand-800 px-3 py-2">
                <span className="text-brand-100">{list.name}</span>
                {" "}{list.scanned}/{list.total} scanned
                {" · "}drain {list.buckets.drain} · maybe {list.buckets.maybe} · no {list.buckets.no}
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-brand-400">
            Random contracts this run: {live?.random_scanned_this_run ?? 0}
            {live?.random_enabled === false ? " · random phase off" : ""}
            {live && !live.connected ? " · desk store not connected, so counts stay at zero until it is" : ""}
          </p>
        </section>
        {error && <p className="mt-4 text-sm text-rose-300">{error}</p>}

        <section className="mt-10" aria-labelledby="lists-heading">
          <h2 id="lists-heading" className="text-[11px] tracking-[0.2em] uppercase text-gold/80 font-semibold mb-3">
            Scanning lists
          </h2>
          {!open && (
            <div className="grid gap-3 sm:grid-cols-2">
              {(lists || SCAN_LISTS).map((list) => (
                <button
                  key={list.id}
                  type="button"
                  onClick={() => void openList(list.id)}
                  className="text-left rounded-lg border border-brand-800 bg-brand-900/40 p-4 hover:border-gold/50"
                >
                  <span className="block text-lg text-brand-50">{list.name}</span>
                  <span className="mt-1 block text-sm text-brand-400">{list.blurb}</span>
                  <span className="mt-3 block text-[11px] tracking-[0.12em] uppercase text-brand-500">
                    {"count" in list && list.count != null ? `${list.count} contracts` : "Open"}
                    {"deep_count" in list && list.deep_count != null ? ` · ${list.deep_count} deep-lane` : ""}
                    {list.min_usd != null && list.max_usd != null ? ` · $${list.min_usd}–$${list.max_usd}` : ""}
                  </span>
                </button>
              ))}
            </div>
          )}

          {open && active && (
            <div>
              <button
                type="button"
                onClick={() => { setOpen(null); setReceipt(null); }}
                className="text-[11px] tracking-[0.14em] uppercase text-brand-400 hover:text-gold mb-3"
              >
                ← All lists
              </button>
              <h3 className="text-xl text-brand-50">{active.name}</h3>
              <p className="text-sm text-brand-400 mt-1">{active.blurb} Showing {contracts.length} of {total}.</p>
              <div className="mt-4 overflow-x-auto rounded-lg border border-brand-800/80">
                <table className="w-full text-xs">
                  <thead className="bg-brand-900/60 text-brand-400 text-left">
                    <tr>
                      <th className="px-3 py-2">Contract</th>
                      <th className="px-3 py-2">Held</th>
                      <th className="px-3 py-2">Bucket</th>
                      <th className="px-3 py-2"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {contracts.map((row) => (
                      <tr key={row.address} className="border-t border-brand-800/60 align-top">
                        <td className="px-3 py-2">
                          <span className="block text-brand-100">{row.protocol || "Contract"}</span>
                          <span className="block font-mono text-[10px] text-brand-500">{row.address}</span>
                          {row.deep_lane && <span className="text-[10px] uppercase tracking-wider text-gold/80">Deep lane</span>}
                        </td>
                        <td className="px-3 py-2 text-brand-200">{money(row.est_usd_held)}</td>
                        <td className="px-3 py-2">
                          <span className={`inline-block rounded border px-2 py-0.5 uppercase tracking-wider ${BUCKET[row.bucket] || BUCKET.no}`}>
                            {row.bucket}
                          </span>
                        </td>
                        <td className="px-3 py-2 text-right">
                          <button
                            type="button"
                            disabled={busy === row.address}
                            onClick={() => void runRow(row)}
                            className="text-[11px] uppercase tracking-wider text-gold hover:text-gold/80 disabled:text-brand-600"
                          >
                            {busy === row.address ? "Running" : "Run now"}
                          </button>
                        </td>
                      </tr>
                    ))}
                    {contracts.length === 0 && !busy && (
                      <tr>
                        <td colSpan={4} className="px-3 py-6 text-center text-brand-500">
                          No contracts in this list yet.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </section>

        <section className="mt-12" aria-labelledby="random-heading">
          <h2 id="random-heading" className="text-[11px] tracking-[0.2em] uppercase text-gold/80 font-semibold mb-3">
            Scanning random contracts
          </h2>
          <div className="rounded-lg border border-brand-800 bg-brand-900/30 p-4">
            <p className="text-sm text-brand-300">
              Random contracts are pulled by the scheduled loop after both lists have a finished pass.
              The list below is that stream. Run now is optional and is not how the loop advances.
            </p>
            <ul className="mt-3 space-y-1 text-xs">
              {(live?.random_stream || []).map((row) => (
                <li key={`${row.at}-${row.address}`} className="font-mono text-brand-300">
                  {row.address} · {row.bucket} · heat {row.heat}
                </li>
              ))}
              {(live?.random_stream || []).length === 0 && (
                <li className="text-brand-500">No random contracts recorded yet. The loop adds them after the lists.</li>
              )}
            </ul>
            <button
              type="button"
              disabled={!random?.enabled || !random.etherscan_configured || busy === "random"}
              onClick={() => void runRandom()}
              className="mt-4 rounded-md border border-brand-700 px-4 py-2 text-[11px] uppercase tracking-[0.14em] text-brand-300 disabled:text-brand-600"
            >
              {busy === "random" ? "Sampling" : "Run now (optional)"}
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
                        No property failures. That is not a verdict of safety.
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
