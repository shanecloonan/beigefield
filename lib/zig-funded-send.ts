/**
 * Signs one MsgExecuteContract with the desk wallet and broadcasts it on ZIGChain.
 * Do not import this file from a client component.
 */
import { SigningCosmWasmClient } from "@cosmjs/cosmwasm-stargate";
import { BroadcastTxError, GasPrice, TimeoutError } from "@cosmjs/stargate";
import {
  MSG_EXECUTE_TYPE_URL,
  VALDORA_STAKER,
  ZIG_CHAIN_ID,
  ZIG_RPC,
  readUnbondingId,
  withdrawByIdMsg,
  zigGasPrice,
} from "@/lib/valdora";
import type { ZigSendResult } from "@/lib/valdora-path-run";
import { resolveWithdrawalRequestId } from "@/lib/valdora-query";
import { ZigFundedKeyError, openZigFundedWallet } from "@/lib/zig-funded-wallet";

const UNCONFIRMED =
  "The network did not confirm the transaction. Check the account before trying again, so it is not sent twice.";
const REJECTED_READ = "The message could not be read. Nothing was sent.";
const SENDER_MISMATCH = "This desk sends only from its own wallet. Nothing was sent.";

export type ZigExecuteArgs = {
  sender: string;
  contract: string;
  msg: ReturnType<typeof withdrawByIdMsg>;
  funds: readonly [];
  memo?: string;
};

export type ZigExecuteResult = { transactionHash: string; height: number };

export type ZigSendDeps = {
  deskAddress?: () => Promise<string>;
  execute?: (args: ZigExecuteArgs) => Promise<ZigExecuteResult>;
};

export async function sendZigScript(input: unknown, deps: ZigSendDeps = {}): Promise<ZigSendResult> {
  const parsed = parseRequest(input);
  if (!parsed.ok) return parsed;

  let desk: string;
  try {
    desk = deps.deskAddress ? await deps.deskAddress() : (await openZigFundedWallet()).address;
  } catch (error) {
    if (error instanceof ZigFundedKeyError) {
      return { ok: false, kind: "rejected", message: error.message };
    }
    return { ok: false, kind: "rejected", message: "The desk key could not be read. Nothing was sent." };
  }

  if (parsed.sender !== desk) {
    return { ok: false, kind: "rejected", message: SENDER_MISMATCH };
  }

  try {
    const result = await (deps.execute ?? executeWithDesk)({
      sender: parsed.sender,
      contract: parsed.contract,
      msg: parsed.msg,
      funds: [],
      memo: parsed.memo,
    });
    if (!/^[0-9A-Fa-f]{64}$/.test(result.transactionHash)) {
      return { ok: false, kind: "ambiguous", message: UNCONFIRMED };
    }
    if (!Number.isSafeInteger(result.height) || result.height < 0) {
      return { ok: false, kind: "ambiguous", message: UNCONFIRMED };
    }
    return { ok: true, txHash: result.transactionHash, height: result.height };
  } catch (error) {
    return classifyBroadcastError(error);
  }
}

async function executeWithDesk(args: ZigExecuteArgs): Promise<ZigExecuteResult> {
  const entered = messageId(args.msg);
  if (entered === null) {
    throw new Error("The withdrawal request id is missing. Nothing was sent.");
  }
  const resolved = await resolveWithdrawalRequestId(args.sender, entered);
  if (!resolved.ok) throw new Error(resolved.message);

  const { wallet } = await openZigFundedWallet();
  const client = await SigningCosmWasmClient.connectWithSigner(ZIG_RPC, wallet, {
    gasPrice: GasPrice.fromString(zigGasPrice()),
  });
  try {
    const chainId = await client.getChainId();
    if (chainId !== ZIG_CHAIN_ID) {
      throw new Error("This desk sends on zigchain-1 only. Nothing was sent.");
    }
    const result = await client.execute(
      args.sender,
      args.contract,
      withdrawByIdMsg(resolved.id),
      "auto",
      args.memo ?? "",
      [],
    );
    return { transactionHash: result.transactionHash, height: result.height };
  } finally {
    client.disconnect();
  }
}

type Parsed =
  | {
      ok: true;
      sender: string;
      contract: string;
      msg: ReturnType<typeof withdrawByIdMsg>;
      memo?: string;
    }
  | { ok: false; kind: "rejected"; message: string };

function parseRequest(input: unknown): Parsed {
  if (!input || typeof input !== "object") {
    return { ok: false, kind: "rejected", message: REJECTED_READ };
  }
  const record = input as Record<string, unknown>;
  if (!Array.isArray(record.messages) || record.messages.length !== 1) {
    return {
      ok: false,
      kind: "rejected",
      message: "This path sends one MsgExecuteContract. Nothing was sent.",
    };
  }
  const message = record.messages[0];
  if (!message || typeof message !== "object") {
    return { ok: false, kind: "rejected", message: REJECTED_READ };
  }
  const typed = message as Record<string, unknown>;
  if (typed.typeUrl !== MSG_EXECUTE_TYPE_URL) {
    return {
      ok: false,
      kind: "rejected",
      message: "The message type is not MsgExecuteContract. Nothing was sent.",
    };
  }
  const value = typed.value;
  if (!value || typeof value !== "object") {
    return { ok: false, kind: "rejected", message: REJECTED_READ };
  }
  const body = value as Record<string, unknown>;
  if (typeof body.sender !== "string" || typeof body.contract !== "string") {
    return { ok: false, kind: "rejected", message: REJECTED_READ };
  }
  if (body.contract !== VALDORA_STAKER) {
    return {
      ok: false,
      kind: "rejected",
      message: "This path executes only the Valdora staker. Nothing was sent.",
    };
  }
  if (!Array.isArray(body.funds) || body.funds.length !== 0) {
    return {
      ok: false,
      kind: "rejected",
      message: "The execute message carries no funds. Nothing was sent.",
    };
  }
  const id = messageId(body.msg);
  if (id === null) {
    return {
      ok: false,
      kind: "rejected",
      message: "The withdrawal request id is missing. Nothing was sent.",
    };
  }
  const expected = withdrawByIdMsg(id);
  const msg = body.msg;
  if (!msg || typeof msg !== "object") {
    return { ok: false, kind: "rejected", message: REJECTED_READ };
  }
  const keys = Object.keys(msg as object);
  if (keys.length !== 1 || keys[0] !== "withdraw_unbonded_by_id") {
    return {
      ok: false,
      kind: "rejected",
      message: "The msg is not withdraw_unbonded_by_id. Nothing was sent.",
    };
  }
  let memo: string | undefined;
  if (record.memo !== undefined) {
    if (typeof record.memo !== "string" || record.memo.length > 256 || /[\u0000-\u001f]/.test(record.memo)) {
      return { ok: false, kind: "rejected", message: "The memo could not be read. Nothing was sent." };
    }
    if (record.memo.length > 0) memo = record.memo;
  }
  return {
    ok: true,
    sender: body.sender,
    contract: body.contract,
    msg: expected,
    memo,
  };
}

function messageId(msg: unknown): number | null {
  if (!msg || typeof msg !== "object") return null;
  const inner = (msg as { withdraw_unbonded_by_id?: unknown }).withdraw_unbonded_by_id;
  if (!inner || typeof inner !== "object") return null;
  const keys = Object.keys(inner as object);
  if (keys.length !== 1 || keys[0] !== "withdrawal_request_id") return null;
  return readUnbondingId((inner as { withdrawal_request_id?: unknown }).withdrawal_request_id);
}

export function classifyBroadcastError(error: unknown): ZigSendResult {
  if (error instanceof TimeoutError) {
    return { ok: false, kind: "ambiguous", message: UNCONFIRMED };
  }
  const message = error instanceof Error ? error.message : "";
  if (/was not yet found on the chain|timed out|timeout|ECONNRESET|socket hang up/i.test(message)) {
    return { ok: false, kind: "ambiguous", message: UNCONFIRMED };
  }
  if (/^Error when broadcasting tx ([0-9A-Fa-f]+) at height (\d+)/.test(message)) {
    return {
      ok: false,
      kind: "rejected",
      message: `The transaction was included and failed. Nothing further was sent. ${trimChain(message)}`,
    };
  }
  if (error instanceof BroadcastTxError || /Nothing was sent\./.test(message)) {
    const text = message.length > 0 && message.length < 400 ? message : "The network rejected the transaction. Nothing was sent.";
    return { ok: false, kind: "rejected", message: text };
  }
  if (
    /insufficient|paused|account|signature|decoding|codespace|Query failed|failed to execute message|missing field|No completed unbondings|Completed unbonding not found|Unauthorized/i.test(
      message,
    )
  ) {
    return {
      ok: false,
      kind: "rejected",
      message: `The transaction was not accepted. Nothing was sent. ${trimChain(message)}`,
    };
  }
  return { ok: false, kind: "ambiguous", message: UNCONFIRMED };
}

function trimChain(message: string): string {
  return message.length > 280 ? `${message.slice(0, 280)}…` : message;
}
