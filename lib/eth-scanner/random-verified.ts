/**
 * Pick one Etherscan-verified mainnet contract for a single /test click.
 *
 * Etherscan API v2 has no "list verified contracts" action (`contract/listcontracts`
 * is rejected; the v1 route is deprecated). Listing internal creates by block
 * range (`account/txlistinternal`) is API Pro. Top-level creates (`to` empty)
 * are rare and usually unverified, so a free-tier budget cannot reliably
 * sample them.
 *
 * This sampler draws a recent block and takes unique contracts that emitted
 * ERC-20/ERC-721 `Transfer` in that block, then keeps the first address
 * `contract/getsourcecode` reports as verified. That is uniform among those
 * emitters, not among every verified contract. Busy tokens qualify in more
 * blocks, so they show up more often. One sample per call — no loop, no timer.
 */

import { etherscanApiKeys } from "./capabilities";

const ETHERSCAN_V2 = "https://api.etherscan.io/v2/api";
const CHAIN_ID = "1";
/** keccak256("Transfer(address,address,uint256)") — ERC-20 and ERC-721. */
const TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef";
const ADDRESS_RE = /^0x[0-9a-fA-F]{40}$/;
const RATE_RE =
  /rate limit|rate-limit|max rate|too many requests|max calls per|rate limiter|community free api limit|daily limit reached/i;

export const SAMPLE_STRATEGY = "transfer-log-sample";

export const SAMPLE_NOTE =
  "Uniform among verified contracts that emitted an ERC-20/721 Transfer in one recent Ethereum block, not among all verified contracts. Etherscan v2 has no list-verified-contracts action, and internal-transaction listing is API Pro. High-activity tokens qualify in more blocks, so they appear more often. One click samples once and scans once.";

const DEFAULT_MIN_INTERVAL_MS = 400;
const DEFAULT_MAX_SOURCE_CHECKS = 4;
const DEFAULT_MAX_BLOCKS = 2;
const DEFAULT_LOOKBACK = 7_200;
const DEFAULT_MIN_AGE = 20;
const MAX_BODY_CHARS = 8_000_000;

export type VerifiedSample = {
  address: string;
  contract_name: string | null;
  compiler: string | null;
  block_number: number;
  strategy: typeof SAMPLE_STRATEGY;
  source_checks: number;
  blocks_tried: number;
  note: string;
};

export type SampleErrorKind = "rate_limit" | "unavailable" | "none" | "config";

export class EtherscanSampleError extends Error {
  readonly kind: SampleErrorKind;

  constructor(kind: SampleErrorKind, message: string) {
    super(message);
    this.name = "EtherscanSampleError";
    this.kind = kind;
  }
}

export function sampleErrorStatus(err: EtherscanSampleError): number {
  switch (err.kind) {
    case "rate_limit":
      return 429;
    case "none":
      return 404;
    case "config":
      return 503;
    default:
      return 502;
  }
}

export type SampleDeps = {
  fetch?: typeof fetch;
  keys?: string;
  sleep?: (ms: number) => Promise<void>;
  now?: () => number;
  /** Uniform in [0, 1). */
  rng?: () => number;
  minIntervalMs?: number;
  maxSourceChecks?: number;
  maxBlocks?: number;
  lookbackBlocks?: number;
  minAgeBlocks?: number;
};

type JsonBody = Record<string, unknown>;

function redact(text: string): string {
  return text.replace(/apikey=[^&\s]+/gi, "apikey=[redacted]").replace(/\s+/g, " ").trim();
}

function cleanLabel(raw: unknown, max: number): string | null {
  if (typeof raw !== "string") return null;
  const s = raw.replace(/[\u0000-\u001f]/g, " ").replace(/\s+/g, " ").trim();
  if (!s) return null;
  return s.slice(0, max);
}

function parseKeys(raw: string): string[] {
  const keys = raw.split(",").map((s) => s.trim()).filter(Boolean);
  if (!keys.length) {
    throw new EtherscanSampleError("config", "No Etherscan API key is configured. Nothing was scanned.");
  }
  return keys;
}

function isRateLimited(http: number, body: JsonBody | null): boolean {
  if (http === 429) return true;
  if (!body) return false;
  const parts: string[] = [];
  if (typeof body.message === "string") parts.push(body.message);
  if (typeof body.result === "string") parts.push(body.result);
  const err = body.error;
  if (typeof err === "string") parts.push(err);
  else if (err && typeof err === "object" && "message" in err && typeof (err as { message?: unknown }).message === "string") {
    parts.push((err as { message: string }).message);
  }
  return RATE_RE.test(parts.join(" "));
}

function rateDetail(body: JsonBody | null): string {
  if (!body) return "";
  const result = typeof body.result === "string" ? body.result : "";
  const message = typeof body.message === "string" ? body.message : "";
  return redact(result || message).slice(0, 180);
}

function rateLimitError(detail: string): EtherscanSampleError {
  const base =
    "Etherscan rate limit reached. The free-tier key allows about 3 calls per second and 100,000 per day. Wait a few seconds and click again — nothing was scanned.";
  const extra = redact(detail).slice(0, 180);
  return new EtherscanSampleError("rate_limit", extra ? `${base} (${extra})` : base);
}

function unavailable(detail: string): EtherscanSampleError {
  const extra = redact(detail).slice(0, 160);
  const tail = extra ? ` (${extra})` : "";
  return new EtherscanSampleError(
    "unavailable",
    `Etherscan didn't return a usable response${tail}. Click again in a moment — nothing was scanned.`,
  );
}

function asRow(result: unknown): Record<string, unknown> | null {
  if (Array.isArray(result)) {
    const row = result[0];
    return row && typeof row === "object" ? (row as Record<string, unknown>) : null;
  }
  if (result && typeof result === "object") return result as Record<string, unknown>;
  return null;
}

function verifiedMeta(result: unknown): { contract_name: string | null; compiler: string | null } | null {
  const row = asRow(result);
  if (!row) return null;
  const source = typeof row.SourceCode === "string" ? row.SourceCode.trim() : "";
  const abi = typeof row.ABI === "string" ? row.ABI : "";
  if (!source) return null;
  if (/contract source code not verified/i.test(abi)) return null;
  if (source.length < 180 && RATE_RE.test(source)) return null;
  return {
    contract_name: cleanLabel(row.ContractName, 120),
    compiler: cleanLabel(row.CompilerVersion, 80),
  };
}

function logAddresses(body: JsonBody): string[] {
  const result = body.result;
  if (!Array.isArray(result)) return [];
  const seen = new Set<string>();
  const out: string[] = [];
  for (const row of result) {
    if (!row || typeof row !== "object") continue;
    const addr = String((row as { address?: unknown }).address || "").trim().toLowerCase();
    if (!ADDRESS_RE.test(addr) || seen.has(addr)) continue;
    seen.add(addr);
    out.push(addr);
  }
  return out;
}

function noRecords(body: JsonBody): boolean {
  const message = typeof body.message === "string" ? body.message : "";
  if (/no records/i.test(message)) return true;
  return Array.isArray(body.result) && body.result.length === 0;
}

function shuffle<T>(items: T[], rng: () => number): T[] {
  const out = items.slice();
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1));
    const tmp = out[i];
    out[i] = out[j]!;
    out[j] = tmp!;
  }
  return out;
}

export async function sampleVerifiedContract(deps: SampleDeps = {}): Promise<VerifiedSample> {
  const doFetch = deps.fetch ?? fetch;
  const sleep = deps.sleep ?? ((ms: number) => new Promise((resolve) => setTimeout(resolve, ms)));
  const now = deps.now ?? Date.now;
  const rng = deps.rng ?? Math.random;
  const minIntervalMs = deps.minIntervalMs ?? DEFAULT_MIN_INTERVAL_MS;
  const maxSourceChecks = deps.maxSourceChecks ?? DEFAULT_MAX_SOURCE_CHECKS;
  const maxBlocks = deps.maxBlocks ?? DEFAULT_MAX_BLOCKS;
  const lookback = deps.lookbackBlocks ?? DEFAULT_LOOKBACK;
  const minAge = deps.minAgeBlocks ?? DEFAULT_MIN_AGE;
  const keys = parseKeys(deps.keys ?? etherscanApiKeys());

  let keyIndex = 0;
  let lastCall = 0;

  async function rawGet(params: Record<string, string>): Promise<{ http: number; body: JsonBody }> {
    const wait = minIntervalMs - (now() - lastCall);
    if (wait > 0) await sleep(wait);
    lastCall = now();
    const key = keys[keyIndex % keys.length]!;
    keyIndex += 1;
    const url = new URL(ETHERSCAN_V2);
    url.searchParams.set("chainid", CHAIN_ID);
    for (const [k, v] of Object.entries(params)) url.searchParams.set(k, v);
    url.searchParams.set("apikey", key);
    let res: Response;
    try {
      res = await doFetch(url, {
        cache: "no-store",
        redirect: "manual",
        headers: { Accept: "application/json", "User-Agent": "beigefield-test/0.1 (defensive; read-only)" },
        signal: AbortSignal.timeout(25_000),
      });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "fetch failed";
      throw unavailable(msg);
    }
    if (res.status >= 300 && res.status < 400) throw unavailable(`HTTP ${res.status}`);
    const text = await res.text();
    if (text.length > MAX_BODY_CHARS) throw unavailable("response too large");
    let body: JsonBody;
    try {
      const parsed = JSON.parse(text) as unknown;
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw unavailable("response was not an object");
      body = parsed as JsonBody;
    } catch (err) {
      if (err instanceof EtherscanSampleError) throw err;
      throw unavailable(`HTTP ${res.status}`);
    }
    return { http: res.status, body };
  }

  async function get(params: Record<string, string>): Promise<JsonBody> {
    const first = await rawGet(params);
    const retry = isRateLimited(first.http, first.body) || first.http >= 500;
    if (!retry) {
      if (first.http >= 400) throw unavailable(`HTTP ${first.http}`);
      return first.body;
    }
    if (isRateLimited(first.http, first.body)) await sleep(1_500);
    const second = await rawGet(params);
    if (isRateLimited(second.http, second.body)) throw rateLimitError(rateDetail(second.body) || rateDetail(first.body));
    if (second.http >= 400) throw unavailable(`HTTP ${second.http}`);
    return second.body;
  }

  const head = await get({ module: "proxy", action: "eth_blockNumber" });
  const hex = typeof head.result === "string" ? head.result : "";
  if (!/^0x[0-9a-fA-F]+$/.test(hex)) throw unavailable("missing block number");
  const latest = Number.parseInt(hex, 16);
  if (!Number.isFinite(latest) || latest < minAge + 1) throw unavailable("block number was not usable");

  const newest = latest - minAge;
  const oldest = Math.max(0, latest - lookback);
  const span = Math.max(0, newest - oldest);
  const tried = new Set<number>();
  let sourceChecks = 0;

  const pickBlock = (): number | null => {
    for (let i = 0; i < 8; i++) {
      const block = oldest + Math.floor(rng() * (span + 1));
      if (!tried.has(block)) return block;
    }
    for (let block = newest; block >= oldest; block--) {
      if (!tried.has(block)) return block;
    }
    return null;
  };

  while (tried.size < maxBlocks && sourceChecks < maxSourceChecks) {
    const block = pickBlock();
    if (block == null) break;
    tried.add(block);

    const logs = await get({
      module: "logs",
      action: "getLogs",
      fromBlock: String(block),
      toBlock: String(block),
      topic0: TRANSFER_TOPIC,
      page: "1",
      offset: "1000",
    });
    if (isRateLimited(200, logs)) throw rateLimitError(rateDetail(logs));
    if (noRecords(logs)) continue;
    if (typeof logs.result === "string") {
      if (RATE_RE.test(logs.result)) throw rateLimitError(logs.result);
      if (/timeout|server too busy/i.test(logs.result)) throw unavailable(logs.result);
      continue;
    }

    for (const address of shuffle(logAddresses(logs), rng)) {
      if (sourceChecks >= maxSourceChecks) break;
      sourceChecks += 1;
      const src = await get({ module: "contract", action: "getsourcecode", address });
      if (isRateLimited(200, src)) throw rateLimitError(rateDetail(src));
      const meta = verifiedMeta(src.result);
      if (!meta) continue;
      return {
        address,
        contract_name: meta.contract_name,
        compiler: meta.compiler,
        block_number: block,
        strategy: SAMPLE_STRATEGY,
        source_checks: sourceChecks,
        blocks_tried: tried.size,
        note: SAMPLE_NOTE,
      };
    }
  }

  throw new EtherscanSampleError(
    "none",
    "No verified contract turned up in the sampled blocks. Click again to try different blocks — nothing was scanned.",
  );
}
