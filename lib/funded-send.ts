/**
 * Signs with the desk wallet and broadcasts through Toncenter.
 * Reads retry once on a rate limit, then ask TonAPI. A broadcast is not retried.
 * TONCENTER_ENDPOINT and TONCENTER_API_KEY override the public endpoint when set.
 */
import { Address, Cell } from "@ton/core";
import { FUNDED_WALLET_ADDRESS, FUNDED_WALLET_MAX_MESSAGES } from "./funded-wallet-public";
import { relaxedMessage, signFundedExternal } from "./funded-wallet";
import type { OutgoingMessage } from "./ton-message";
import { readAccountState, readSeqno, TON_NETWORK_WAIT, toncenterSend } from "./ton-rpc";

const TRANSFER_TTL_SECONDS = 600;

export type FundedSendResult =
  | { ok: true }
  | { ok: false; kind: "rejected" | "ambiguous"; message: string };

export type FundedSendDeps = {
  fetchImpl?: typeof fetch;
  nowSeconds?: number;
  endpoint?: string;
  apiKey?: string;
  tonapi?: string;
  sleep?: (ms: number) => Promise<void>;
};

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

  const chain = {
    fetchImpl: deps.fetchImpl,
    endpoint: deps.endpoint,
    apiKey: deps.apiKey,
    tonapi: deps.tonapi,
    sleep: deps.sleep,
  };

  const state = await readAccountState(FUNDED_WALLET_ADDRESS, chain);
  if (!state.ok) {
    return {
      ok: false,
      kind: state.network ? "ambiguous" : "rejected",
      message: state.network
        ? `${TON_NETWORK_WAIT} Nothing was sent. Check the wallet before trying again.`
        : "The network refused the wallet lookup. Nothing was sent.",
    };
  }

  const accountState = state.state;
  if (accountState === "frozen") {
    return {
      ok: false,
      kind: "rejected",
      message: "This wallet is frozen. Nothing was sent.",
    };
  }

  let seqno = 0;
  if (accountState === "active") {
    const read = await readSeqno(FUNDED_WALLET_ADDRESS, chain);
    if (read === null) {
      return {
        ok: false,
        kind: "rejected",
        message: `The sequence number could not be read. ${TON_NETWORK_WAIT} Nothing was sent.`,
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

  const sent = await toncenterSend(boc.toString("base64"), chain);
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

