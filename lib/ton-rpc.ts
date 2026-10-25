import { Address, Cell, beginCell } from "@ton/core";

/** Public Toncenter JSON-RPC. A key raises its rate limit. It is not required. */
export const TONCENTER_ENDPOINT = "https://toncenter.com/api/v2/jsonRPC";

/** Public TonAPI. Used when Toncenter does not answer. */
export const TONAPI_ENDPOINT = "https://tonapi.io";

export const TON_NETWORK_WAIT =
  "The TON network did not answer. Wait a moment and try again.";

const ATTEMPT_MS = 3_500;

export type TonRpcDeps = {
  fetchImpl?: typeof fetch;
  endpoint?: string;
  apiKey?: string;
  tonapi?: string;
  sleep?: (ms: number) => Promise<void>;
};

type CallResult = { ok: true; result: unknown } | { ok: false; network: boolean };

export async function readAccountState(
  address: string,
  deps: TonRpcDeps = {},
): Promise<{ ok: true; state: "active" | "uninitialized" | "frozen" } | { ok: false; network: boolean }> {
  const toncenter = await toncenterCall(
    "getAddressInformation",
    { address },
    deps,
    { retry: true },
  );
  const fromCenter = toncenter.ok ? readState(toncenter.result) : null;
  if (fromCenter) return { ok: true, state: fromCenter };
  const fromApi = await tonapiAccountState(address, deps);
  if (fromApi) return { ok: true, state: fromApi };
  return { ok: false, network: !toncenter.ok && toncenter.network };
}

export async function readSeqno(address: string, deps: TonRpcDeps = {}): Promise<number | null> {
  const toncenter = await toncenterSeqno(address, deps, true);
  if (toncenter !== null) return toncenter;
  return tonapiSeqno(address, deps);
}

/**
 * Highest sequence number Toncenter or TonAPI reports.
 * A cached Toncenter value can lag the block that accepted a broadcast.
 */
export async function readObservedSeqno(address: string, deps: TonRpcDeps = {}): Promise<number | null> {
  const [toncenter, tonapi] = await Promise.all([
    toncenterSeqno(address, deps, false),
    tonapiSeqno(address, deps),
  ]);
  const values = [toncenter, tonapi].filter((value): value is number => value !== null);
  if (values.length === 0) return null;
  return Math.max(...values);
}

export async function readJettonWallet(
  owner: Address,
  minter: Address,
  deps: TonRpcDeps = {},
): Promise<Address | null> {
  const slice = beginCell().storeAddress(owner).endCell().toBoc().toString("base64");
  const toncenter = await toncenterCall(
    "runGetMethod",
    {
      address: minter.toString({ urlSafe: true, bounceable: true, testOnly: false }),
      method: "get_wallet_address",
      stack: [["tvm.Slice", slice]],
    },
    deps,
    { retry: true },
  );
  if (toncenter.ok) {
    const parsed = addressFromGetMethod(toncenter.result);
    if (parsed) return parsed;
  }
  return tonapiJettonWallet(owner, minter, deps);
}

/** One broadcast attempt. A timeout may already have been delivered, so this does not retry. */
export async function toncenterSend(
  bocBase64: string,
  deps: TonRpcDeps = {},
): Promise<CallResult> {
  return toncenterCall("sendBoc", { boc: bocBase64 }, deps, { retry: false });
}

/** One TonAPI broadcast. Call this only after the sequence number is still unchanged. */
export async function tonapiSend(bocBase64: string, deps: TonRpcDeps = {}): Promise<CallResult> {
  const fetchImpl = deps.fetchImpl ?? fetch;
  const base = (deps.tonapi ?? TONAPI_ENDPOINT).replace(/\/$/, "");
  try {
    const response = await fetchImpl(`${base}/v2/blockchain/message`, {
      method: "POST",
      headers: { accept: "application/json", "content-type": "application/json" },
      body: JSON.stringify({ boc: bocBase64 }),
      signal: AbortSignal.timeout(ATTEMPT_MS),
    });
    if (response.ok) return { ok: true, result: null };
    return { ok: false, network: response.status === 429 || response.status >= 500 };
  } catch {
    return { ok: false, network: true };
  }
}

async function toncenterSeqno(
  address: string,
  deps: TonRpcDeps,
  retry: boolean,
): Promise<number | null> {
  const toncenter = await toncenterCall(
    "runGetMethod",
    { address, method: "seqno", stack: [] },
    deps,
    { retry },
  );
  if (!toncenter.ok) return null;
  return parseSeqno(toncenter.result);
}

export async function toncenterCall(
  method: string,
  params: Record<string, unknown>,
  deps: TonRpcDeps = {},
  options?: { retry?: boolean },
): Promise<CallResult> {
  const fetchImpl = deps.fetchImpl ?? fetch;
  const endpoint = deps.endpoint?.trim() || process.env.TONCENTER_ENDPOINT?.trim() || TONCENTER_ENDPOINT;
  const apiKey = deps.apiKey?.trim() || process.env.TONCENTER_API_KEY?.trim() || undefined;
  const attempts = options?.retry ? 2 : 1;
  let network = false;

  for (let attempt = 0; attempt < attempts; attempt += 1) {
    let response: Response;
    try {
      const headers: Record<string, string> = { "content-type": "application/json" };
      if (apiKey) headers["X-API-Key"] = apiKey;
      response = await fetchImpl(endpoint, {
        method: "POST",
        headers,
        body: JSON.stringify({ id: 1, jsonrpc: "2.0", method, params }),
        signal: AbortSignal.timeout(ATTEMPT_MS),
      });
    } catch {
      return { ok: false, network: true };
    }

    let json: unknown;
    try {
      json = await response.json();
    } catch {
      network = true;
      break;
    }

    if (response.ok && isRecord(json) && json.ok === true) {
      return { ok: true, result: "result" in json ? json.result : null };
    }

    const status = response.status;
    const code = isRecord(json) && typeof json.code === "number" ? json.code : status;
    const retryable = status === 429 || status >= 500 || code === 429 || code === 500 || code === 504;
    network = network || retryable || status >= 500;
    if (!retryable || attempt + 1 === attempts) break;
    await (deps.sleep ?? sleep)(500);
  }

  return { ok: false, network };
}

function readState(result: unknown): "active" | "uninitialized" | "frozen" | null {
  if (!isRecord(result) || typeof result.state !== "string") return null;
  if (result.state === "active" || result.state === "uninitialized" || result.state === "frozen") {
    return result.state;
  }
  return null;
}

export function parseSeqno(result: unknown): number | null {
  if (!isRecord(result) || result.exit_code !== 0 || !Array.isArray(result.stack)) return null;
  const top = result.stack[0];
  if (!Array.isArray(top)) return null;
  return parseNum(top[1]);
}

export function addressFromGetMethod(result: unknown): Address | null {
  if (!isRecord(result) || result.exit_code !== 0 || !Array.isArray(result.stack)) return null;
  const top = result.stack[0];
  if (!Array.isArray(top)) return null;
  const cell = cellFromStack(top[1]);
  if (!cell) return null;
  try {
    return cell.beginParse().loadAddress();
  } catch {
    return null;
  }
}

function cellFromStack(value: unknown): Cell | null {
  if (!isRecord(value)) return null;
  const bytes = typeof value.bytes === "string" ? value.bytes : nestedB64(value);
  if (!bytes) return null;
  try {
    return Cell.fromBase64(bytes);
  } catch {
    return null;
  }
}

function nestedB64(value: Record<string, unknown>): string | null {
  const object = value.object;
  if (!isRecord(object) || !isRecord(object.data)) return null;
  return typeof object.data.b64 === "string" ? object.data.b64 : null;
}

async function tonapiAccountState(
  address: string,
  deps: TonRpcDeps,
): Promise<"active" | "uninitialized" | "frozen" | null> {
  const payload = await tonapiGet(`/v2/blockchain/accounts/${encodeURIComponent(address)}`, deps);
  if (!isRecord(payload) || typeof payload.status !== "string") return null;
  if (payload.status === "active" || payload.status === "uninitialized" || payload.status === "frozen") {
    return payload.status;
  }
  if (payload.status === "nonexist") return "uninitialized";
  return null;
}

async function tonapiSeqno(address: string, deps: TonRpcDeps): Promise<number | null> {
  const payload = await tonapiGet(
    `/v2/blockchain/accounts/${encodeURIComponent(address)}/methods/seqno`,
    deps,
  );
  if (!isRecord(payload) || payload.success !== true || payload.exit_code !== 0) return null;
  if (isRecord(payload.decoded) && typeof payload.decoded.state === "number") {
    const state = payload.decoded.state;
    if (Number.isInteger(state) && state >= 0 && state < 2 ** 32) return state;
  }
  if (!Array.isArray(payload.stack)) return null;
  const top = payload.stack[0];
  if (!isRecord(top)) return null;
  return parseNum(top.num);
}

async function tonapiJettonWallet(
  owner: Address,
  minter: Address,
  deps: TonRpcDeps,
): Promise<Address | null> {
  const ownerText = owner.toString({ urlSafe: true, bounceable: false, testOnly: false });
  const minterText = minter.toString({ urlSafe: true, bounceable: true, testOnly: false });
  const payload = await tonapiGet(
    `/v2/accounts/${encodeURIComponent(ownerText)}/jettons/${encodeURIComponent(minterText)}`,
    deps,
  );
  if (!isRecord(payload) || !isRecord(payload.wallet_address)) return null;
  const raw = payload.wallet_address.address;
  if (typeof raw !== "string") return null;
  try {
    return Address.parse(raw);
  } catch {
    return null;
  }
}

async function tonapiGet(path: string, deps: TonRpcDeps): Promise<unknown> {
  const fetchImpl = deps.fetchImpl ?? fetch;
  const base = (deps.tonapi ?? TONAPI_ENDPOINT).replace(/\/$/, "");
  try {
    const response = await fetchImpl(`${base}${path}`, {
      headers: { accept: "application/json" },
      signal: AbortSignal.timeout(ATTEMPT_MS),
    });
    if (!response.ok) return null;
    return await response.json();
  } catch {
    return null;
  }
}

function parseNum(value: unknown): number | null {
  if (typeof value === "number" && Number.isInteger(value) && value >= 0 && value < 2 ** 32) {
    return value;
  }
  if (typeof value === "string" && /^-?(0x)?[0-9a-fA-F]+$/.test(value)) {
    try {
      const parsed = BigInt(value);
      if (parsed >= BigInt(0) && parsed < BigInt(2) ** BigInt(32)) return Number(parsed);
    } catch {
      return null;
    }
  }
  if (isRecord(value) && "number" in value) return parseNum(value.number);
  return null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object";
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
