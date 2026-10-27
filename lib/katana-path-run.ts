import {
  isKatanaAction,
  katanaActionNeedsAmount,
  katanaVault,
  readBaseUnits,
  type KatanaAction,
} from "@/lib/katana";
import { isSolAddress } from "@/lib/sol-funded-wallet-public";

export type PathRunInput = {
  sender: string;
  state: string;
  action: KatanaAction;
  amount?: string;
};

export type PathRunOk = {
  ok: true;
  sender: string;
  state: string;
  action: KatanaAction;
  amount?: string;
  summary: string;
};

export type PathRunResult = PathRunOk | { ok: false; message: string };

export function compilePathRun(input: PathRunInput): PathRunResult {
  const sender = input.sender?.trim?.() ?? "";
  if (!isSolAddress(sender)) {
    return { ok: false, message: "The sender is not a Solana address. Nothing was sent." };
  }
  const state = input.state?.trim?.() ?? "";
  const vault = katanaVault(state);
  if (!vault) {
    return { ok: false, message: "This path executes only a listed Katana vault. Nothing was sent." };
  }
  if (!isKatanaAction(input.action)) {
    return { ok: false, message: "The instruction is not a remaining Katana action. Nothing was sent." };
  }
  let amount: string | undefined;
  if (katanaActionNeedsAmount(input.action)) {
    const parsed = readBaseUnits(input.amount);
    if (parsed === null) {
      return { ok: false, message: "The instant withdraw amount is missing. Nothing was sent." };
    }
    amount = parsed.toString();
  } else if (input.amount !== undefined && String(input.amount).trim() !== "") {
    return { ok: false, message: "This instruction does not take an amount. Nothing was sent." };
  }
  return {
    ok: true,
    sender,
    state,
    action: input.action,
    ...(amount ? { amount } : {}),
    summary: amount
      ? `${input.action} ${amount} on ${vault.label} ${vault.strategy}`
      : `${input.action} on ${vault.label} ${vault.strategy}`,
  };
}

export function suggestKatanaAction(input: {
  expired: boolean;
  userAccount: boolean;
  userDeposit: bigint;
  userUnredeemed: bigint;
  userWithdrawShares: bigint;
  userDerivative: bigint;
}): KatanaAction | null {
  if (input.userWithdrawShares > BigInt(0)) return "complete_withdraw";
  if (input.expired && (input.userUnredeemed > BigInt(0) || input.userDerivative > BigInt(0))) {
    return input.userUnredeemed > BigInt(0) ? "exit" : "withdraw_expired";
  }
  if (input.userDeposit > BigInt(0)) return "instant_withdraw";
  if (input.userAccount) return "close_user_account";
  return null;
}

export function pathLookupNote(input: {
  expired: boolean;
  paused: boolean;
  round: string;
  suggested: KatanaAction | null;
  userDeposit: string;
  userUnredeemed: string;
  userWithdrawShares: string;
  userDerivative: string;
  lamports: string;
}): string {
  const suggested = input.suggested ?? "none";
  return `RPC expired=${input.expired} paused=${input.paused} round=${input.round} suggested=${suggested} deposit=${input.userDeposit} unredeemed=${input.userUnredeemed} queued=${input.userWithdrawShares} shares=${input.userDerivative} lamports=${input.lamports}.`;
}

export type KatanaPathDefaultsOk = {
  ok: true;
  owner: string;
  state: string;
  program: string;
  label: string;
  strategy: string;
  expired: boolean;
  paused: boolean;
  round: string;
  total_shares: string;
  pending_deposits: string;
  queued_withdraw_shares: string;
  locked_amount: string;
  vault_balance: string | null;
  user_account: boolean;
  user_deposit: string;
  user_unredeemed: string;
  user_withdraw_shares: string;
  user_derivative: string;
  suggested: KatanaAction | null;
  deposit_enabled: false;
  migrate_enabled: false;
  lamports: string;
};

export type KatanaSendOk = { ok: true; signature: string };
export type KatanaSendFailure = { ok: false; kind: "rejected" | "ambiguous"; message: string };
export type KatanaSendResult = KatanaSendOk | KatanaSendFailure;

const SIGNATURE = /^[1-9A-HJ-NP-Za-km-z]{64,88}$/;

export function readKatanaSendResult(
  payload: unknown,
): KatanaSendOk | { ok: false; text: string } | null {
  if (!payload || typeof payload !== "object") return null;
  const record = payload as Record<string, unknown>;
  if (record.ok === true) {
    if (typeof record.signature !== "string" || !SIGNATURE.test(record.signature)) return null;
    return { ok: true, signature: record.signature };
  }
  if (record.ok !== false) return null;
  if (record.kind !== "rejected" && record.kind !== "ambiguous") return null;
  if (typeof record.message !== "string" || record.message.length === 0) return null;
  return { ok: false, text: record.message };
}

export function readKatanaPathDefaults(
  payload: unknown,
): KatanaPathDefaultsOk | { ok: false; message: string } | null {
  if (!payload || typeof payload !== "object") return null;
  const record = payload as Record<string, unknown>;
  if (record.ok === true) {
    if (typeof record.owner !== "string" || typeof record.state !== "string") return null;
    if (typeof record.expired !== "boolean" || typeof record.paused !== "boolean") return null;
    if (record.suggested !== null && !isKatanaAction(record.suggested)) return null;
    if (typeof record.round !== "string" || typeof record.lamports !== "string") return null;
    if (typeof record.user_deposit !== "string" || typeof record.user_unredeemed !== "string") return null;
    if (typeof record.user_withdraw_shares !== "string" || typeof record.user_derivative !== "string") {
      return null;
    }
    if (typeof record.label !== "string" || typeof record.strategy !== "string") return null;
    if (typeof record.program !== "string") return null;
    if (record.deposit_enabled !== false || record.migrate_enabled !== false) return null;
    if (typeof record.user_account !== "boolean") return null;
    if (typeof record.total_shares !== "string" || typeof record.pending_deposits !== "string") return null;
    if (typeof record.queued_withdraw_shares !== "string" || typeof record.locked_amount !== "string") {
      return null;
    }
    const vaultBalance =
      record.vault_balance === null
        ? null
        : typeof record.vault_balance === "string"
          ? record.vault_balance
          : null;
    if (record.vault_balance !== null && vaultBalance === null) return null;
    return {
      ok: true,
      owner: record.owner,
      state: record.state,
      program: record.program,
      label: record.label,
      strategy: record.strategy,
      expired: record.expired,
      paused: record.paused,
      round: record.round,
      total_shares: record.total_shares,
      pending_deposits: record.pending_deposits,
      queued_withdraw_shares: record.queued_withdraw_shares,
      locked_amount: record.locked_amount,
      vault_balance: vaultBalance,
      user_account: record.user_account,
      user_deposit: record.user_deposit,
      user_unredeemed: record.user_unredeemed,
      user_withdraw_shares: record.user_withdraw_shares,
      user_derivative: record.user_derivative,
      suggested: record.suggested,
      deposit_enabled: false,
      migrate_enabled: false,
      lamports: record.lamports,
    };
  }
  if (record.ok !== false) return null;
  if (typeof record.message !== "string" || record.message.length === 0) return null;
  return { ok: false, message: record.message };
}
