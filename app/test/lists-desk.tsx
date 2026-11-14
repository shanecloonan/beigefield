"use client";

import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";

type Outcome = "drain" | "maybe" | "no";

type ContractRow = {
  address: string;
  protocol: string;
  est_usd_held: number;
  candidate_reason: string;
  tier: number;
  source: string;
  manual: boolean;
  evidence_note: string;
  scanned: boolean;
  outcome: Outcome | null;
  heat: number | null;
  funds_usd: number | string | null;
  status: string | null;
};

type ListSummary = {
  id: string;
  name: string;
  strategy: string;
  summary: string;
  min_funds_usd: number;
  max_funds_usd: number;
  source: string;
  total: number;
  total_usd: number;
  manual_count: number;
  scanned: number;
  unscanned: number;
  buckets: Record<Outcome, number>;
  contracts?: ContractRow[];
};

type RandomScan = {
  enabled: boolean;
  gap_ms: number;
  history_cap: number;
  session_cap: number;
};

type ListsResponse = {
  ok: boolean;
  error?: string;
  random_scan?: RandomScan;
  lists?: ListSummary[];
  selected?: ListSummary | null;
};

const BUCKETS: { id: Outcome; label: string; hint: string; cls: string }[] = [
  {
    id: "drain",
    label: "Drain found",
    hint: "A real reproducible drain: funds_in_heat is above zero, or a fork proof shows caller_profit_delta above zero.",
    cls: "border-rose-900/70 bg-rose-950/30 text-rose-100",
  },
  {
    id: "maybe",
    label: "Maybe",
    hint: "Heat is above zero from centralization or invariant signals. No confirmed drain.",
    cls: "border-amber-900/70 bg-amber-950/25 text-amber-100",
  },
  {
    id: "no",
    label: "No",
    hint: "Scanned and cold. Heat is zero.",
    cls: "border-brand-700 bg-brand-900/40 text-brand-200",
  },
];

const inputCls =
  "rounded-md bg-brand-900 border border-brand-800 px-3 py-2 text-sm text-brand-100 placeholder:text-brand-600 focus:outline-none focus:border-gold/50";
const btnPrimary =
  "px-4 py-2 text-[11px] tracking-[0.15em] uppercase font-semibold rounded-md text-brand-950 bg-gold hover:bg-gold/90 disabled:opacity-50";
const btnSecondary =
  "px-3 py-1.5 text-[11px] tracking-[0.12em] uppercase font-semibold rounded-md border border-brand-700 text-brand-200 hover:bg-brand-900 disabled:opacity-50";

function money(value: number): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(value || 0);
}

function sourceLabel(source: string): string {
  if (source === "list2_candidates") return "Loaded from list2_candidates.";
  if (source === "excluded_fallback") return "Seeded from excluded.csv rows that fell under the old floor, then filtered to the sketchy tail.";
  if (source === "master_candidates") return "Curated master feed, including the hand-ranked overlay.";
  return source;
}

export default function ListsDesk({
  onRandomScan,
}: {
  onRandomScan?: (config: RandomScan) => void;
}) {
  const [lists, setLists] = useState<ListSummary[]>([]);
  const [selectedId, setSelectedId] = useState("list-1");
  const [selected, setSelected] = useState<ListSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [openBucket, setOpenBucket] = useState<Outcome | null>(null);
  const [address, setAddress] = useState("");
  const [addMessage, setAddMessage] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [visible, setVisible] = useState(40);
  const [filter, setFilter] = useState<"all" | "unscanned" | Outcome>("all");

  const load = useCallback(async (listId: string) => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/test/lists?list=${encodeURIComponent(listId)}`, { cache: "no-store" });
      const body = (await res.json()) as ListsResponse;
      if (!res.ok || !body.ok) {
        setError(body.error || `HTTP ${res.status}`);
        return;
      }
      setLists(body.lists ?? []);
      setSelected(body.selected ?? null);
      if (body.random_scan) onRandomScan?.(body.random_scan);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load lists.");
    } finally {
      setLoading(false);
    }
  }, [onRandomScan]);

  useEffect(() => {
    void load(selectedId);
  }, [load, selectedId]);

  const contracts = selected?.contracts ?? [];
  const shown = useMemo(() => {
    const rows = contracts.filter((row) => {
      if (filter === "all") return true;
      if (filter === "unscanned") return !row.scanned;
      return row.outcome === filter;
    });
    return rows;
  }, [contracts, filter]);

  async function addAddress(event: FormEvent) {
    event.preventDefault();
    if (!selected) return;
    setAdding(true);
    setAddMessage(null);
    try {
      const res = await fetch("/api/test/lists", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ list_id: selected.id, address }),
      });
      const body = (await res.json()) as { ok?: boolean; error?: string; address?: string };
      if (!res.ok || !body.ok) {
        setAddMessage(body.error || "Could not add that address.");
        return;
      }
      setAddress("");
      setAddMessage(`Added ${body.address} to ${selected.name}.`);
      await load(selected.id);
    } catch (err) {
      setAddMessage(err instanceof Error ? err.message : "Could not add that address.");
    } finally {
      setAdding(false);
    }
  }

  return (
    <section className="mt-8" aria-labelledby="master-lists-heading">
      <div className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <p className="text-[11px] tracking-[0.2em] uppercase text-gold/80 font-semibold">Named master lists</p>
          <h2 id="master-lists-heading" className="mt-1 text-2xl font-semibold tracking-tight text-brand-50">
            Pick a list
          </h2>
        </div>
        <button type="button" onClick={() => void load(selectedId)} className={btnSecondary} disabled={loading}>
          {loading ? "Loading…" : "Refresh"}
        </button>
      </div>
      <p className="mt-2 max-w-3xl text-sm text-brand-400 leading-relaxed">
        List 1 is the funded, credible-but-less-audited curated feed. List 2 is the junk-drawer:
        sketchy small-dollar contracts, ranked for abandoned, unaudited, odd-pattern, or previously-hacked lineage.
        Dollar bounds belong to each list.
      </p>

      <div className="mt-4 grid gap-3 sm:grid-cols-2" role="tablist" aria-label="Master lists">
        {lists.map((list) => {
          const active = list.id === selectedId;
          return (
            <button
              key={list.id}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => {
                setSelectedId(list.id);
                setOpenBucket(null);
                setFilter("all");
                setVisible(40);
              }}
              className={`text-left rounded-lg border p-4 transition-colors ${
                active ? "border-gold/60 bg-gold/10" : "border-brand-800 bg-brand-900/30 hover:border-brand-600"
              }`}
            >
              <span className="block text-[11px] tracking-[0.16em] uppercase text-gold/80">{list.name}</span>
              <span className="mt-1 block text-sm text-brand-100">{list.summary}</span>
              <span className="mt-3 block text-[12px] text-brand-400">
                {list.total.toLocaleString()} contracts · {money(list.min_funds_usd)}–{money(list.max_funds_usd)}
                {" · "}
                {list.scanned.toLocaleString()} scanned · {list.unscanned.toLocaleString()} not scanned
              </span>
            </button>
          );
        })}
      </div>

      {error && (
        <p className="mt-4 text-sm text-rose-300 border border-rose-900/60 rounded-lg px-3 py-2">{error}</p>
      )}

      {selected && (
        <div className="mt-6 rounded-lg border border-brand-800 bg-brand-900/20 p-4 sm:p-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h3 className="text-xl font-semibold text-brand-50">{selected.name}</h3>
              <p className="mt-1 max-w-2xl text-sm text-brand-300 leading-relaxed">{selected.summary}</p>
              <p className="mt-2 text-[12px] text-brand-500">{sourceLabel(selected.source)}</p>
            </div>
            <dl className="grid grid-cols-3 gap-3 text-center">
              <div>
                <dt className="text-[10px] tracking-[0.14em] uppercase text-brand-500">Contracts</dt>
                <dd className="text-lg text-brand-50 tabular-nums">{selected.total.toLocaleString()}</dd>
              </div>
              <div>
                <dt className="text-[10px] tracking-[0.14em] uppercase text-brand-500">Scanned</dt>
                <dd className="text-lg text-brand-50 tabular-nums">{selected.scanned.toLocaleString()}</dd>
              </div>
              <div>
                <dt className="text-[10px] tracking-[0.14em] uppercase text-brand-500">Not scanned</dt>
                <dd className="text-lg text-brand-50 tabular-nums">{selected.unscanned.toLocaleString()}</dd>
              </div>
            </dl>
          </div>
          <p className="mt-3 text-[12px] text-brand-400">
            Funds on the feed {money(selected.total_usd)} · live range {money(selected.min_funds_usd)} to {money(selected.max_funds_usd)}
          </p>

          <div className="mt-5 grid gap-3 md:grid-cols-3">
            {BUCKETS.map((bucket) => {
              const open = openBucket === bucket.id;
              const rows = contracts.filter((row) => row.outcome === bucket.id);
              return (
                <div key={bucket.id} className={`rounded-lg border p-3 ${bucket.cls}`}>
                  <button
                    type="button"
                    className="w-full text-left"
                    aria-expanded={open}
                    onClick={() => setOpenBucket(open ? null : bucket.id)}
                  >
                    <span className="block text-[11px] tracking-[0.16em] uppercase">{bucket.label}</span>
                    <span className="mt-1 block text-2xl font-semibold tabular-nums">{selected.buckets[bucket.id] ?? 0}</span>
                    <span className="mt-1 block text-[12px] leading-relaxed opacity-80">{bucket.hint}</span>
                    <span className="mt-2 block text-[11px] tracking-[0.12em] uppercase opacity-70">
                      {open ? "Hide contracts" : "Show contracts"}
                    </span>
                  </button>
                  {open && (
                    <ul className="mt-3 max-h-64 overflow-auto space-y-2 text-[12px]">
                      {rows.length === 0 && <li className="opacity-70">No contracts in this bucket.</li>}
                      {rows.slice(0, 80).map((row) => (
                        <li key={row.address} className="border-t border-white/10 pt-2">
                          <span className="font-mono text-[11px] break-all">{row.address}</span>
                          <span className="block text-brand-100">{row.protocol || "—"} · heat {row.heat ?? 0}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              );
            })}
          </div>

          <form className="mt-6 flex flex-col sm:flex-row gap-3 sm:items-end" onSubmit={(event) => void addAddress(event)}>
            <label className="flex-1 min-w-0">
              <span className="block text-[10px] tracking-[0.14em] uppercase text-brand-500 mb-1.5">
                Add an address to {selected.name}
              </span>
              <input
                value={address}
                onChange={(event) => setAddress(event.target.value)}
                placeholder="0x… 40 hex characters"
                spellCheck={false}
                autoComplete="off"
                className={`w-full font-mono text-[13px] ${inputCls}`}
              />
            </label>
            <button type="submit" className={btnPrimary} disabled={adding || !address.trim()}>
              {adding ? "Adding…" : "Add"}
            </button>
          </form>
          <p className="mt-2 text-[11px] text-brand-500 leading-relaxed">
            The form checks the address, skips duplicates, and appends it to eth-scanner/data/lists/manual.json.
            You can also edit that file directly. The next scan of this list uses {selected.name}&apos;s bounds.
          </p>
          {addMessage && <p className="mt-2 text-sm text-brand-200">{addMessage}</p>}

          <div className="mt-6 flex flex-wrap gap-2" role="group" aria-label="Contract filter">
            {([
              ["all", "All"],
              ["unscanned", "Not scanned"],
              ["drain", "Drain found"],
              ["maybe", "Maybe"],
              ["no", "No"],
            ] as const).map(([id, label]) => (
              <button
                key={id}
                type="button"
                onClick={() => {
                  setFilter(id);
                  setVisible(40);
                }}
                className={filter === id ? btnPrimary : btnSecondary}
              >
                {label}
              </button>
            ))}
          </div>
          <ul className="mt-3 divide-y divide-brand-800/80">
            {shown.slice(0, visible).map((row) => (
              <li key={row.address} className="py-2.5 flex flex-col sm:flex-row sm:items-baseline gap-1 sm:gap-4">
                <span className="font-mono text-[12px] text-brand-100 break-all sm:w-[420px] shrink-0">{row.address}</span>
                <span className="text-[13px] text-brand-200 flex-1">
                  {row.protocol || "Unknown"}
                  {row.manual ? " · manual" : ""}
                  {" · "}
                  {row.scanned ? (row.outcome === "drain" ? "Drain found" : row.outcome === "maybe" ? "Maybe" : "No") : "Not scanned"}
                  {row.heat != null && row.scanned ? ` · heat ${row.heat}` : ""}
                </span>
                <span className="text-[12px] text-brand-500 tabular-nums">{row.est_usd_held ? money(row.est_usd_held) : "—"}</span>
              </li>
            ))}
          </ul>
          {shown.length > visible && (
            <button type="button" className={`${btnSecondary} mt-3`} onClick={() => setVisible((n) => n + 40)}>
              Show more ({shown.length - visible} left)
            </button>
          )}
          {shown.length === 0 && !loading && (
            <p className="mt-3 text-sm text-brand-500">No contracts in this view.</p>
          )}
        </div>
      )}
    </section>
  );
}
