/**
 * LCD smart-query helpers for the Valdora staker.
 * Safe to import from route handlers. No key material.
 */
import { VALDORA_STAKER, ZIG_LCD, readUnbondingId } from "@/lib/valdora";
import { isZigAddress } from "@/lib/zig-funded-wallet-public";
import type { ZigPathDefaultsOk } from "@/lib/valdora-path-run";

export type ZigQueryDeps = {
  fetchImpl?: typeof fetch;
  lcd?: string;
  /** `undefined` reads VALDORA_DEFAULT_ID. `null` means unset. */
  defaultId?: string | null;
  searchTxs?: boolean;
};

type QueryFailure = { ok: false; status: number; message: string };
export type ZigPathDefaultsResult = ZigPathDefaultsOk | QueryFailure;

const LCD_DOWN = "The LCD did not answer the staker query.";
const LCD_SHAPE = "The staker query could not be read.";

type CompletedRowIds = {
  recordId: number | null;
  requestId: number | null;
  executable: number | null;
};

function completedRowIds(row: unknown): CompletedRowIds {
  if (!row || typeof row !== "object") return { recordId: null, requestId: null, executable: null };
  const record = row as { id?: unknown; withdrawal_id?: unknown };
  const recordId = readUnbondingId(record.id);
  const requestId = readUnbondingId(record.withdrawal_id);
  return { recordId, requestId, executable: requestId ?? recordId };
}

/** The id the execute message must send: `withdrawal_id` when the row has one. */
export function pickCompletedId(rows: unknown): number | null {
  if (!Array.isArray(rows)) return null;
  let best: number | null = null;
  for (const row of rows) {
    const id = completedRowIds(row).executable;
    if (id === null) continue;
    if (best === null || id > best) best = id;
  }
  return best;
}

/**
 * Map a typed id onto the withdrawal request id the staker will accept.
 * A completed-record `id` and a `withdrawal_id` both match; the returned value is `withdrawal_id`.
 */
export function matchWithdrawalRequestId(rows: unknown, entered: number): number | null {
  if (!Array.isArray(rows)) return null;
  const parsed = rows.map(completedRowIds).filter((row) => row.executable !== null);
  const byRequest = parsed.find((row) => row.requestId === entered);
  if (byRequest?.executable !== undefined && byRequest.executable !== null) return byRequest.executable;
  const byRecord = parsed.find((row) => row.recordId === entered);
  return byRecord?.executable ?? null;
}

export type ResolvedWithdrawal = { ok: true; id: number } | { ok: false; message: string };

const LIST_LIMIT = 100;

/** Reads this address's completed unbondings and refuses an id it does not own. */
export async function resolveWithdrawalRequestId(
  owner: string,
  entered: number,
  deps: Pick<ZigQueryDeps, "fetchImpl" | "lcd"> = {},
): Promise<ResolvedWithdrawal> {
  const lcd = (deps.lcd ?? ZIG_LCD).replace(/\/$/, "");
  const listed = await smartQuery(
    lcd,
    { completed_unbondings: { address: owner, limit: LIST_LIMIT } },
    deps.fetchImpl ?? fetch,
  );
  if (!listed.ok) return { ok: false, message: withNothingSent(listed.message) };
  if (!listed.data || typeof listed.data !== "object") {
    return { ok: false, message: withNothingSent(LCD_SHAPE) };
  }
  const rows = (listed.data as { completed_unbondings?: unknown }).completed_unbondings;
  if (!Array.isArray(rows)) return { ok: false, message: withNothingSent(LCD_SHAPE) };
  if (rows.length === 0) {
    return {
      ok: false,
      message: `This desk has no completed unbondings, so ${entered} cannot be withdrawn from it. Nothing was sent.`,
    };
  }
  const resolved = matchWithdrawalRequestId(rows, entered);
  if (resolved === null && rows.length >= LIST_LIMIT) {
    return {
      ok: false,
      message: "The completed-unbonding list for this desk is longer than the lookup. Nothing was sent.",
    };
  }
  if (resolved === null) {
    return {
      ok: false,
      message: `${entered} is not a completed unbonding for this desk. Nothing was sent.`,
    };
  }
  return { ok: true, id: resolved };
}

function withNothingSent(message: string): string {
  if (message.includes("Nothing was sent.")) return message;
  return `${message.trim()} Nothing was sent.`;
}

export function parseDefaultId(value: string | null | undefined): number | null {
  if (value === null || value === undefined) return null;
  return readUnbondingId(value.trim());
}

/** Ids recorded while unbonded amounts were collected. Already-withdrawn execute ids are skipped. */
export function pickCompletedIdFromTxs(payload: unknown): number | null {
  if (!payload || typeof payload !== "object") return null;
  const responses = (payload as { tx_responses?: unknown }).tx_responses;
  if (!Array.isArray(responses)) return null;
  let best: number | null = null;
  for (const tx of responses) {
    if (!tx || typeof tx !== "object") continue;
    const events = (tx as { events?: unknown }).events;
    if (!Array.isArray(events)) continue;
    for (const event of events) {
      if (!event || typeof event !== "object") continue;
      const type = (event as { type?: unknown }).type;
      if (typeof type !== "string" || !type.startsWith("wasm")) continue;
      const attributes = (event as { attributes?: unknown }).attributes;
      if (!Array.isArray(attributes)) continue;
      const pairs = new Map<string, string>();
      for (const attribute of attributes) {
        if (!attribute || typeof attribute !== "object") continue;
        const key = (attribute as { key?: unknown }).key;
        const value = (attribute as { value?: unknown }).value;
        if (typeof key === "string" && typeof value === "string") pairs.set(key, value);
      }
      const method = pairs.get("method") ?? "";
      const collecting = method === "collect_unbonded_amounts" || type === "wasm-collect_unbonded_amounts";
      const explicit = pairs.get("completed_unbonding_id");
      const fromMethod = collecting ? pairs.get("id") : undefined;
      const id = readUnbondingId(explicit ?? fromMethod);
      if (id === null) continue;
      if (best === null || id > best) best = id;
    }
  }
  return best;
}

export async function loadZigPathDefaults(
  input: { owner?: string },
  deps: ZigQueryDeps = {},
): Promise<ZigPathDefaultsResult> {
  const owner = input.owner?.trim() ?? "";
  if (owner && !isZigAddress(owner)) {
    return { ok: false, status: 400, message: "Enter a zig1 address." };
  }

  const lcd = (deps.lcd ?? ZIG_LCD).replace(/\/$/, "");
  const fetchImpl = deps.fetchImpl ?? fetch;

  const [totals, paused, protocol] = await Promise.all([
    smartQuery(lcd, { total_completed_unbondings: {} }, fetchImpl),
    smartQuery(lcd, { paused: {} }, fetchImpl),
    smartQuery(lcd, { protocol_info: {} }, fetchImpl),
  ]);
  if (!totals.ok) return totals;
  if (!paused.ok) return paused;

  const totalCount = readCount(totals.data);
  const pausedFlag = readPaused(paused.data);
  if (totalCount === null || pausedFlag === null) {
    return { ok: false, status: 502, message: LCD_SHAPE };
  }

  const tokenName = readTokenName(protocol.ok ? protocol.data : null);
  const suggested = await suggestId(lcd, owner, fetchImpl, deps);
  return {
    ok: true,
    staker: VALDORA_STAKER,
    paused: pausedFlag,
    total_count: totalCount,
    suggested_id: suggested,
    owner,
    ...(tokenName ? { token_name: tokenName } : {}),
  };
}

async function suggestId(
  lcd: string,
  owner: string,
  fetchImpl: typeof fetch,
  deps: ZigQueryDeps,
): Promise<number | null> {
  if (owner) {
    const listed = await smartQuery(
      lcd,
      { completed_unbondings: { address: owner, limit: 100 } },
      fetchImpl,
    );
    if (listed.ok) {
      const rows = (listed.data as { completed_unbondings?: unknown } | null)?.completed_unbondings;
      const id = pickCompletedId(rows);
      if (id !== null) return id;
    }
  }

  const configured =
    deps.defaultId === undefined ? process.env.VALDORA_DEFAULT_ID : deps.defaultId;
  const fromEnv = parseDefaultId(configured);
  if (fromEnv !== null) return fromEnv;

  if (deps.searchTxs === false) return null;
  const query = `wasm._contract_address='${VALDORA_STAKER}'`;
  const url = `${lcd}/cosmos/tx/v1beta1/txs?query=${encodeURIComponent(query)}&order_by=ORDER_BY_DESC&limit=20`;
  try {
    const response = await fetchImpl(url, { cache: "no-store", signal: AbortSignal.timeout(12_000) });
    if (!response.ok) return null;
    const payload: unknown = await response.json();
    return pickCompletedIdFromTxs(payload);
  } catch {
    return null;
  }
}

type SmartResult = { ok: true; data: unknown } | QueryFailure;

async function smartQuery(
  lcd: string,
  query: object,
  fetchImpl: typeof fetch,
): Promise<SmartResult> {
  const encoded = Buffer.from(JSON.stringify(query)).toString("base64");
  const url = `${lcd}/cosmwasm/wasm/v1/contract/${VALDORA_STAKER}/smart/${encodeURIComponent(encoded)}`;
  let response: Response;
  try {
    response = await fetchImpl(url, { cache: "no-store", signal: AbortSignal.timeout(12_000) });
  } catch {
    return { ok: false, status: 502, message: LCD_DOWN };
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    return { ok: false, status: 502, message: LCD_SHAPE };
  }
  if (!response.ok) {
    return { ok: false, status: 502, message: LCD_DOWN };
  }
  if (!payload || typeof payload !== "object" || !("data" in payload)) {
    return { ok: false, status: 502, message: LCD_SHAPE };
  }
  return { ok: true, data: (payload as { data: unknown }).data };
}

function readCount(data: unknown): number | null {
  if (!data || typeof data !== "object") return null;
  const value = (data as { total_count?: unknown }).total_count;
  return readUnbondingId(value);
}

function readPaused(data: unknown): boolean | null {
  if (!data || typeof data !== "object") return null;
  const value = (data as { paused?: unknown }).paused;
  return typeof value === "boolean" ? value : null;
}

function readTokenName(data: unknown): string | undefined {
  if (!data || typeof data !== "object") return undefined;
  const value = (data as { token_name?: unknown }).token_name;
  if (typeof value !== "string") return undefined;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : undefined;
}
