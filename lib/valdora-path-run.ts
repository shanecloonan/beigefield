import {
  MSG_EXECUTE_TYPE_URL,
  VALDORA_STAKER,
  readUnbondingId,
  withdrawByIdMsg,
} from "@/lib/valdora";
import { isZigAddress } from "@/lib/zig-funded-wallet-public";

export type CosmWasmExecuteMsg = {
  typeUrl: typeof MSG_EXECUTE_TYPE_URL;
  value: {
    sender: string;
    contract: string;
    msg: ReturnType<typeof withdrawByIdMsg>;
    funds: [];
  };
};

export type PathRunInput = {
  id: number;
  sender: string;
  memo?: string;
};

export type PathRunOk = {
  ok: true;
  messages: CosmWasmExecuteMsg[];
  summary: string;
  preview: { contract: string; msg: object; sender: string };
  memo?: string;
};

export type PathRunResult = PathRunOk | { ok: false; message: string };

export function compilePathRun(input: PathRunInput): PathRunResult {
  const id = readUnbondingId(input.id);
  if (id === null) {
    return { ok: false, message: "The completed-unbonding id is missing. Nothing was sent." };
  }
  const sender = input.sender?.trim?.() ?? "";
  if (!isZigAddress(sender)) {
    return { ok: false, message: "The sender is not a zig1 address. Nothing was sent." };
  }
  let memo: string | undefined;
  if (input.memo !== undefined) {
    if (typeof input.memo !== "string" || input.memo.length > 256 || /[\u0000-\u001f]/.test(input.memo)) {
      return { ok: false, message: "The memo could not be read. Nothing was sent." };
    }
    if (input.memo.length > 0) memo = input.memo;
  }
  const msg = withdrawByIdMsg(id);
  const message: CosmWasmExecuteMsg = {
    typeUrl: MSG_EXECUTE_TYPE_URL,
    value: {
      sender,
      contract: VALDORA_STAKER,
      msg,
      funds: [],
    },
  };
  return {
    ok: true,
    messages: [message],
    summary: `MsgExecuteContract withdraw_unbonded_by_id id ${id} on ${VALDORA_STAKER}`,
    preview: { contract: VALDORA_STAKER, msg, sender },
    ...(memo ? { memo } : {}),
  };
}

export type ZigPathDefaultsOk = {
  ok: true;
  staker: string;
  paused: boolean;
  total_count: number;
  suggested_id: number | null;
  owner: string;
  token_name?: string;
};

export function pathLookupNote(input: {
  paused: boolean;
  total_count: number;
  suggested_id: number | null;
  token_name?: string;
}): string {
  const id = input.suggested_id === null ? "none" : String(input.suggested_id);
  const token = input.token_name ? ` token=${input.token_name}` : "";
  return `LCD paused=${input.paused} total_count=${input.total_count} suggested_id=${id}${token}.`;
}

export type ZigSendOk = { ok: true; txHash: string; height: number };
export type ZigSendFailure = { ok: false; kind: "rejected" | "ambiguous"; message: string };
export type ZigSendResult = ZigSendOk | ZigSendFailure;

/** Reads a zig send JSON body. Ambiguous and rejected replies both carry the text to show. */
export function readZigSendResult(
  payload: unknown,
): ZigSendOk | { ok: false; text: string } | null {
  if (!payload || typeof payload !== "object") return null;
  const record = payload as Record<string, unknown>;
  if (record.ok === true) {
    if (typeof record.txHash !== "string" || !/^[0-9A-Fa-f]{64}$/.test(record.txHash)) return null;
    if (typeof record.height !== "number" || !Number.isSafeInteger(record.height) || record.height < 0) {
      return null;
    }
    return { ok: true, txHash: record.txHash, height: record.height };
  }
  if (record.ok !== false) return null;
  if (record.kind !== "rejected" && record.kind !== "ambiguous") return null;
  if (typeof record.message !== "string" || record.message.length === 0) return null;
  return { ok: false, text: record.message };
}

export function readZigPathDefaults(
  payload: unknown,
): ZigPathDefaultsOk | { ok: false; message: string } | null {
  if (!payload || typeof payload !== "object") return null;
  const record = payload as Record<string, unknown>;
  if (record.ok === true) {
    if (typeof record.staker !== "string" || record.staker.length === 0) return null;
    if (typeof record.paused !== "boolean") return null;
    if (typeof record.total_count !== "number" || !Number.isSafeInteger(record.total_count)) return null;
    if (record.suggested_id !== null && readUnbondingId(record.suggested_id) === null) return null;
    if (typeof record.owner !== "string") return null;
    const token =
      typeof record.token_name === "string" && record.token_name.length > 0
        ? record.token_name
        : undefined;
    return {
      ok: true,
      staker: record.staker,
      paused: record.paused,
      total_count: record.total_count,
      suggested_id: record.suggested_id === null ? null : readUnbondingId(record.suggested_id),
      owner: record.owner,
      ...(token ? { token_name: token } : {}),
    };
  }
  if (record.ok !== false) return null;
  if (typeof record.message !== "string" || record.message.length === 0) return null;
  return { ok: false, message: record.message };
}
