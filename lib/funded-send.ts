/**
 * Signs with the desk wallet and broadcasts through Toncenter's public
 * mainnet JSON-RPC. That endpoint does not require an API key.
 * TONCENTER_ENDPOINT and TONCENTER_API_KEY override it when a host does.
 */
import { Address, Cell } from "@ton/core";
import { FUNDED_WALLET_ADDRESS, FUNDED_WALLET_MAX_MESSAGES } from "./funded-wallet-public";
import { relaxedMessage, signFundedExternal } from "./funded-wallet";
import type { OutgoingMessage } from "./ton-message";

const DEFAULT_ENDPOINT = "https://toncenter.com/api/v2/jsonRPC";
const TRANSFER_TTL_SECONDS = 600;

export type FundedSendResult =
  | { ok: true }
  | { ok: false; kind: "rejected" | "ambiguous"; message: string };

export type FundedSendDeps = {
  fetchImpl?: typeof fetch;
  nowSeconds?: number;
  endpoint?: string;
  apiKey?: string;
};

type RpcOk = { ok: true; result: unknown };
type RpcFail = { ok: false; network: boolean };
type Rejected = { ok: false; kind: "rejected"; message: string };
type ParsedRequest =
  | { ok: true; messages: ReturnType<typeof relaxedMessage>[] }
  | Rejected;

export async function sendFundedScript(
  input: unknown,
  deps: FundedSendDeps = {},
): Promise<FundedSendResult> {
  const parsed = parseRequest(input);
  if (!parsed.ok) return parsed;

  const fetchImpl = deps.fetchImpl ?? fetch;
  const endpoint = deps.endpoint?.trim() || DEFAULT_ENDPOINT;
  const apiKey = deps.apiKey?.trim() || undefined;

  const state = await rpc(fetchImpl, endpoint, apiKey, "getAddressInformation", {
    address: FUNDED_WALLET_ADDRESS,
  });
  if (!state.ok) {
    return {
      ok: false,
      kind: state.network ? "ambiguous" : "rejected",
      message: state.network
        ? "The network did not answer. Nothing was sent. Check the wallet before trying again."
        : "The network refused the wallet lookup. Nothing was sent.",
    };
  }

  const accountState = readState(state.result);
  if (accountState === "frozen") {
    return {
      ok: false,
      kind: "rejected",
      message: "This wallet is frozen. Nothing was sent.",
    };
  }
  if (!accountState) {
    return {
      ok: false,
      kind: "ambiguous",
      message: "The wallet state could not be read. Nothing was sent.",
    };
  }

  let seqno = 0;
  if (accountState === "active") {
    const method = await rpc(fetchImpl, endpoint, apiKey, "runGetMethod", {
      address: FUNDED_WALLET_ADDRESS,
      method: "seqno",
      stack: [],
    });
    if (!method.ok) {
      return {
        ok: false,
        kind: "rejected",
        message: "The sequence number could not be read. Nothing was sent.",
      };
    }
    const read = readSeqno(method.result);
    if (read === null) {
      return {
        ok: false,
        kind: "rejected",
        message: "The sequence number could not be read. Nothing was sent.",
      };
    }
    seqno = read;
  }

  let boc: Buffer;
  try {
    boc = await signFundedExternal({
      seqno,
      timeout: (deps.nowSeconds ?? Math.floor(Date.now() / 1000)) + TRANSFER_TTL_SECONDS,
      includeInit: accountState !== "active",
      messages: parsed.messages,
    });
  } catch {
    return {
      ok: false,
      kind: "rejected",
      message: "This message could not be signed. Nothing was sent.",
    };
  }

  const sent = await rpc(fetchImpl, endpoint, apiKey, "sendBoc", {
    boc: boc.toString("base64"),
  });
  if (!sent.ok) {
    if (!sent.network) {
      return {
        ok: false,
        kind: "rejected",
        message: "The network rejected the message. Nothing was sent.",
      };
    }
    return {
      ok: false,
      kind: "ambiguous",
      message:
        "The wallet did not confirm the message. Check the wallet before trying again, so it is not sent twice.",
    };
  }

  return { ok: true };
}

function parseRequest(input: unknown): ParsedRequest {
  if (!input || typeof input !== "object") {
    return { ok: false, kind: "rejected", message: "The message could not be read. Nothing was sent." };
  }
  const record = input as Record<string, unknown>;
  if (record.network !== undefined && record.network !== "-239") {
    return {
      ok: false,
      kind: "rejected",
      message: "This desk sends on mainnet only. Nothing was sent.",
    };
  }
  if (record.from !== undefined) {
    if (typeof record.from !== "string" || !sameAccount(record.from, FUNDED_WALLET_ADDRESS)) {
      return {
        ok: false,
        kind: "rejected",
        message: "This desk sends only from its own wallet. Nothing was sent.",
      };
    }
  }
  if (!Array.isArray(record.messages) || record.messages.length === 0) {
    return { ok: false, kind: "rejected", message: "Add a message. Nothing was sent." };
  }
  if (record.messages.length > FUNDED_WALLET_MAX_MESSAGES) {
    return {
      ok: false,
      kind: "rejected",
      message: `This wallet accepts ${FUNDED_WALLET_MAX_MESSAGES} messages per confirmation. Nothing was sent.`,
    };
  }

  const messages = [];
  for (const item of record.messages) {
    const built = readOutgoing(item);
    if (!built.ok) return built;
    messages.push(built.message);
  }
  return { ok: true, messages };
}

function readOutgoing(
  item: unknown,
): { ok: true; message: ReturnType<typeof relaxedMessage> } | Rejected {
  if (!item || typeof item !== "object") {
    return { ok: false, kind: "rejected", message: "A message could not be read. Nothing was sent." };
  }
  const message = item as Partial<OutgoingMessage>;
  if (typeof message.address !== "string" || !Address.isFriendly(message.address)) {
    return {
      ok: false,
      kind: "rejected",
      message: "A destination could not be read. Nothing was sent.",
    };
  }
  try {
    const parsed = Address.parseFriendly(message.address.trim());
    if (parsed.isTestOnly) {
      return {
        ok: false,
        kind: "rejected",
        message: "A destination is marked for testnet. Nothing was sent.",
      };
    }
  } catch {
    return {
      ok: false,
      kind: "rejected",
      message: "A destination could not be read. Nothing was sent.",
    };
  }
  if (typeof message.amount !== "string" || !/^\d+$/.test(message.amount)) {
    return {
      ok: false,
      kind: "rejected",
      message: "A value could not be read. Nothing was sent.",
    };
  }

  let body: Cell | undefined;
  if (message.payload !== undefined) {
    if (typeof message.payload !== "string" || message.payload.length > 16_000) {
      return {
        ok: false,
        kind: "rejected",
        message: "A payload could not be read. Nothing was sent.",
      };
    }
    try {
      body = Cell.fromBase64(message.payload);
    } catch {
      return {
        ok: false,
        kind: "rejected",
        message: "A payload could not be read. Nothing was sent.",
      };
    }
  }

  try {
    return {
      ok: true,
      message: relaxedMessage({
        address: message.address.trim(),
        nanotons: BigInt(message.amount),
        body,
      }),
    };
  } catch {
    return {
      ok: false,
      kind: "rejected",
      message: "A message could not be built. Nothing was sent.",
    };
  }
}

function sameAccount(left: string, right: string): boolean {
  try {
    return Address.parse(left).equals(Address.parse(right));
  } catch {
    return false;
  }
}

async function rpc(
  fetchImpl: typeof fetch,
  endpoint: string,
  apiKey: string | undefined,
  method: string,
  params: Record<string, unknown>,
): Promise<RpcOk | RpcFail> {
  const headers: Record<string, string> = { "content-type": "application/json" };
  if (apiKey) headers["X-API-Key"] = apiKey;

  let response: Response;
  try {
    response = await fetchImpl(endpoint, {
      method: "POST",
      headers,
      body: JSON.stringify({ id: 1, jsonrpc: "2.0", method, params }),
      signal: AbortSignal.timeout(20_000),
    });
  } catch {
    return { ok: false, network: true };
  }

  let json: unknown;
  try {
    json = await response.json();
  } catch {
    return { ok: false, network: true };
  }
  if (!response.ok || !json || typeof json !== "object" || !("ok" in json)) {
    return { ok: false, network: response.status >= 500 };
  }
  if (json.ok !== true) return { ok: false, network: false };
  return { ok: true, result: "result" in json ? json.result : null };
}

function readState(result: unknown): "active" | "uninitialized" | "frozen" | null {
  if (!result || typeof result !== "object" || !("state" in result)) return null;
  const state = result.state;
  if (state === "active" || state === "uninitialized" || state === "frozen") return state;
  return null;
}

function readSeqno(result: unknown): number | null {
  if (!result || typeof result !== "object" || !("exit_code" in result)) return null;
  if (result.exit_code !== 0 || !("stack" in result) || !Array.isArray(result.stack)) return null;
  const top = result.stack[0];
  if (!Array.isArray(top)) return null;
  return parseNum(top[1]);
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
  if (value && typeof value === "object" && "number" in value) {
    return parseNum(value.number);
  }
  return null;
}
