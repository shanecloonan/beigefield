/**
 * Authorized instantWithdraw: the connected wallet is only the fee payer.
 * userAuthority (account 6 / PDA seed) and destination (account 4) are
 * chosen separately. userAuthority is not an instruction signer. Safe to
 * import from the /katana client.
 */
import { PublicKey, TransactionInstruction } from "@solana/web3.js";
import {
  findAssociatedTokenAddress,
  parseSolPubkey,
  type KatanaSnapshot,
} from "@/lib/katana-accounts";
import { createAtaIdempotent, instantWithdrawIx, type BuiltInstructions } from "@/lib/katana-ix";
import { readBaseUnits } from "@/lib/katana";
import { isSolAddress } from "@/lib/sol-funded-wallet-public";

export type AuthorizedPendingKind = "ready" | "no_account" | "other_owner" | "stale_round" | "zero";

export type AuthorizedWithdrawSnapshot = {
  vault: { label: string };
  programId: string;
  state: string;
  userAccount: string;
  user: { owner: string; depositRound: bigint | string; depositAmount: bigint | string } | null;
  decoded: {
    round: bigint | string;
    underlyingTokenMint: string;
    underlyingTokenVault: string;
    vaultAuthority: string;
    totalPendingDeposits: bigint | string;
  };
  userUnderlyingAta: string;
};

export type KatanaAuthorizedLookupOk = {
  ok: true;
  owner: string;
  state: string;
  program: string;
  label: string;
  strategy: string;
  vault_round: string;
  deposit_round: string | null;
  deposit_amount: string;
  withdrawable: boolean;
  pending_kind: AuthorizedPendingKind;
  note: string;
  underlying_mint: string;
  underlying_vault: string;
  vault_authority: string;
  destination_ata: string;
  user_account: string;
  user_account_exists: boolean;
  user_owner: string | null;
  decimals: number;
  paused: boolean;
  expired: boolean;
  native_underlying: boolean;
  pending_deposits: string;
};

function asBigInt(value: bigint | string): bigint {
  return typeof value === "bigint" ? value : BigInt(value);
}

export function formatTokenAmount(amount: bigint, decimals: number): string {
  if (decimals <= 0) return amount.toString();
  const places = Math.min(decimals, 18);
  const base = BigInt(10) ** BigInt(places);
  const whole = amount / base;
  const frac = amount % base;
  if (frac === BigInt(0)) return whole.toString();
  return `${whole}.${frac.toString().padStart(places, "0").replace(/0+$/, "")}`;
}

export function authorizedPendingStatus(input: {
  userAuthority: string;
  user: { owner: string; depositRound: bigint; depositAmount: bigint } | null;
  vaultRound: bigint;
}): { kind: AuthorizedPendingKind; amount: bigint } {
  if (!input.user) return { kind: "no_account", amount: BigInt(0) };
  if (input.user.owner !== input.userAuthority) return { kind: "other_owner", amount: BigInt(0) };
  if (input.user.depositAmount <= BigInt(0)) return { kind: "zero", amount: BigInt(0) };
  if (input.user.depositRound !== input.vaultRound) {
    return { kind: "stale_round", amount: input.user.depositAmount };
  }
  return { kind: "ready", amount: input.user.depositAmount };
}

export function authorizedLookupNote(input: {
  kind: AuthorizedPendingKind;
  vaultRound: string;
  depositRound: string | null;
  depositAmount: string;
  humanAmount: string;
  label: string;
  paused: boolean;
}): string {
  let note: string;
  switch (input.kind) {
    case "no_account":
      note = `Vault round ${input.vaultRound}. This user authority has no Katana user account on this vault.`;
      break;
    case "other_owner":
      note = `Vault round ${input.vaultRound}. This user account is not owned by the chosen user authority.`;
      break;
    case "zero":
      note = `Vault round ${input.vaultRound}. There is no pending deposit on this vault for this user authority.`;
      break;
    case "stale_round":
      note = `Vault round ${input.vaultRound}. Your pending amount is ${input.humanAmount} ${input.label} (${input.depositAmount} base units) from round ${input.depositRound ?? "—"}, so instantWithdraw is disabled. Use claim_shares or initiate_withdraw.`;
      break;
    default:
      note = `Vault round ${input.vaultRound}. Your pending amount is ${input.humanAmount} ${input.label} (${input.depositAmount} base units) from this same round and is withdrawable.`;
  }
  if (input.paused) return `${note} The vault is paused.`;
  return note;
}

export function authorizedLookupFromSnapshot(snapshot: KatanaSnapshot, owner: string): KatanaAuthorizedLookupOk {
  const user = snapshot.user
    ? {
        owner: snapshot.user.owner,
        depositRound: snapshot.user.depositRound,
        depositAmount: snapshot.user.depositAmount,
      }
    : null;
  const pending = authorizedPendingStatus({
    userAuthority: owner,
    user,
    vaultRound: snapshot.decoded.round,
  });
  const depositAmount = (snapshot.user?.depositAmount ?? BigInt(0)).toString();
  const depositRound = snapshot.user ? snapshot.user.depositRound.toString() : null;
  const vaultRound = snapshot.decoded.round.toString();
  return {
    ok: true,
    owner,
    state: snapshot.state,
    program: snapshot.programId,
    label: snapshot.vault.label,
    strategy: snapshot.vault.strategy,
    vault_round: vaultRound,
    deposit_round: depositRound,
    deposit_amount: depositAmount,
    withdrawable: pending.kind === "ready",
    pending_kind: pending.kind,
    note: authorizedLookupNote({
      kind: pending.kind,
      vaultRound,
      depositRound,
      depositAmount,
      humanAmount: formatTokenAmount(pending.amount, snapshot.decoded.decimals),
      label: snapshot.vault.label,
      paused: snapshot.decoded.paused,
    }),
    underlying_mint: snapshot.decoded.underlyingTokenMint,
    underlying_vault: snapshot.decoded.underlyingTokenVault,
    vault_authority: snapshot.decoded.vaultAuthority,
    destination_ata: snapshot.userUnderlyingAta,
    user_account: snapshot.userAccount,
    user_account_exists: snapshot.user !== null,
    user_owner: snapshot.user?.owner ?? null,
    decimals: snapshot.decoded.decimals,
    paused: snapshot.decoded.paused,
    expired: snapshot.decoded.expired,
    native_underlying: snapshot.nativeUnderlying,
    pending_deposits: snapshot.decoded.totalPendingDeposits.toString(),
  };
}

export function snapshotFromAuthorizedLookup(lookup: KatanaAuthorizedLookupOk): AuthorizedWithdrawSnapshot {
  return {
    vault: { label: lookup.label },
    programId: lookup.program,
    state: lookup.state,
    userAccount: lookup.user_account,
    user:
      lookup.user_account_exists && lookup.user_owner && lookup.deposit_round !== null
        ? {
            owner: lookup.user_owner,
            depositRound: lookup.deposit_round,
            depositAmount: lookup.deposit_amount,
          }
        : null,
    decoded: {
      round: lookup.vault_round,
      underlyingTokenMint: lookup.underlying_mint,
      underlyingTokenVault: lookup.underlying_vault,
      vaultAuthority: lookup.vault_authority,
      totalPendingDeposits: lookup.pending_deposits,
    },
    userUnderlyingAta: lookup.destination_ata,
  };
}

export function readAuthorizedLookup(
  payload: unknown,
): KatanaAuthorizedLookupOk | { ok: false; message: string } | null {
  if (!payload || typeof payload !== "object") return null;
  const record = payload as Record<string, unknown>;
  if (record.ok === true) {
    const kinds: readonly AuthorizedPendingKind[] = [
      "ready",
      "no_account",
      "other_owner",
      "stale_round",
      "zero",
    ];
    if (typeof record.owner !== "string" || typeof record.state !== "string") return null;
    if (typeof record.program !== "string" || typeof record.label !== "string") return null;
    if (typeof record.strategy !== "string" || typeof record.vault_round !== "string") return null;
    if (record.deposit_round !== null && typeof record.deposit_round !== "string") return null;
    if (typeof record.deposit_amount !== "string" || typeof record.withdrawable !== "boolean") return null;
    if (typeof record.pending_kind !== "string" || !kinds.includes(record.pending_kind as AuthorizedPendingKind)) {
      return null;
    }
    if (typeof record.note !== "string" || typeof record.underlying_mint !== "string") return null;
    if (typeof record.underlying_vault !== "string" || typeof record.vault_authority !== "string") return null;
    if (typeof record.destination_ata !== "string" || typeof record.user_account !== "string") return null;
    if (typeof record.user_account_exists !== "boolean") return null;
    if (record.user_owner !== null && typeof record.user_owner !== "string") return null;
    if (typeof record.decimals !== "number" || typeof record.paused !== "boolean") return null;
    if (typeof record.expired !== "boolean" || typeof record.native_underlying !== "boolean") return null;
    if (typeof record.pending_deposits !== "string") return null;
    return {
      ok: true,
      owner: record.owner,
      state: record.state,
      program: record.program,
      label: record.label,
      strategy: record.strategy,
      vault_round: record.vault_round,
      deposit_round: record.deposit_round,
      deposit_amount: record.deposit_amount,
      withdrawable: record.withdrawable,
      pending_kind: record.pending_kind as AuthorizedPendingKind,
      note: record.note,
      underlying_mint: record.underlying_mint,
      underlying_vault: record.underlying_vault,
      vault_authority: record.vault_authority,
      destination_ata: record.destination_ata,
      user_account: record.user_account,
      user_account_exists: record.user_account_exists,
      user_owner: record.user_owner,
      decimals: record.decimals,
      paused: record.paused,
      expired: record.expired,
      native_underlying: record.native_underlying,
      pending_deposits: record.pending_deposits,
    };
  }
  if (record.ok !== false) return null;
  if (typeof record.message !== "string" || record.message.length === 0) return null;
  return { ok: false, message: record.message };
}

export function readAuthorizedBlockhash(
  payload: unknown,
): { ok: true; blockhash: string; lastValidBlockHeight: number } | { ok: false; message: string } | null {
  if (!payload || typeof payload !== "object") return null;
  const record = payload as Record<string, unknown>;
  if (record.ok === true) {
    if (typeof record.blockhash !== "string" || record.blockhash.length === 0) return null;
    if (typeof record.lastValidBlockHeight !== "number" || !Number.isFinite(record.lastValidBlockHeight)) {
      return null;
    }
    return { ok: true, blockhash: record.blockhash, lastValidBlockHeight: record.lastValidBlockHeight };
  }
  if (record.ok !== false) return null;
  if (typeof record.message !== "string" || record.message.length === 0) return null;
  return { ok: false, message: record.message };
}

const DEST_MISMATCH = "The instruction destination does not match the chosen token account. Nothing was sent.";
const AUTHORITY_MISMATCH = "The instruction userAuthority does not match the chosen authority. Nothing was sent.";
const ACCOUNT_OWNER_MISMATCH = "This user account is not owned by the chosen user authority. Nothing was sent.";
const STALE_ROUND = "This pending deposit is from an earlier vault round. Use claim_shares or initiate_withdraw. Nothing was sent.";
const NO_PENDING = "No same-round pending deposit on this vault. Nothing was sent.";
const BAD_AMOUNT = "The withdraw amount is missing or larger than the pending deposit. Nothing was sent.";
const BAD_FEE_PAYER = "Connect a Solana wallet. Nothing was sent.";
const BAD_AUTHORITY = "Enter a user authority. Nothing was sent.";
const BAD_DESTINATION = "Enter a destination token account. Nothing was sent.";
const BAD_MINT = "The vault underlying mint could not be read. Nothing was sent.";
const VAULT_PENDING = "The withdraw amount is above the vault's pending deposits. Nothing was sent.";

export function assertAuthorizedWithdrawAccounts(
  ix: TransactionInstruction,
  userAuthority: PublicKey,
  destination: PublicKey,
): { ok: true } | { ok: false; message: string } {
  const dest = ix.keys[4];
  const authority = ix.keys[6];
  if (!dest || !authority) {
    return { ok: false, message: AUTHORITY_MISMATCH };
  }
  if (!dest.pubkey.equals(destination) || dest.isSigner || !dest.isWritable) {
    return { ok: false, message: DEST_MISMATCH };
  }
  if (!authority.pubkey.equals(userAuthority) || authority.isSigner || authority.isWritable) {
    return { ok: false, message: AUTHORITY_MISMATCH };
  }
  return { ok: true };
}

function ataCreateIfKnown(
  feePayer: PublicKey,
  userAuthority: PublicKey,
  mint: PublicKey,
  destination: PublicKey,
): TransactionInstruction | null {
  const authorityAta = findAssociatedTokenAddress(userAuthority, mint);
  if (destination.equals(authorityAta)) {
    return createAtaIdempotent(feePayer, userAuthority, mint, destination);
  }
  const payerAta = findAssociatedTokenAddress(feePayer, mint);
  if (destination.equals(payerAta)) {
    return createAtaIdempotent(feePayer, feePayer, mint, destination);
  }
  return null;
}

export function buildAuthorizedInstantWithdraw(input: {
  feePayer: string;
  userAuthority: string;
  destination: string;
  snapshot: AuthorizedWithdrawSnapshot;
  amount: string;
}): BuiltInstructions {
  if (!isSolAddress(input.feePayer)) {
    return { ok: false, kind: "rejected", message: BAD_FEE_PAYER };
  }
  if (!isSolAddress(input.userAuthority)) {
    return { ok: false, kind: "rejected", message: BAD_AUTHORITY };
  }
  if (!isSolAddress(input.destination)) {
    return { ok: false, kind: "rejected", message: BAD_DESTINATION };
  }
  const feePayer = parseSolPubkey(input.feePayer);
  const userAuthority = parseSolPubkey(input.userAuthority);
  const destination = parseSolPubkey(input.destination);
  if (!feePayer) {
    return { ok: false, kind: "rejected", message: BAD_FEE_PAYER };
  }
  if (!userAuthority) {
    return { ok: false, kind: "rejected", message: BAD_AUTHORITY };
  }
  if (!destination) {
    return { ok: false, kind: "rejected", message: BAD_DESTINATION };
  }

  const mint = parseSolPubkey(input.snapshot.decoded.underlyingTokenMint);
  if (!mint) {
    return { ok: false, kind: "rejected", message: BAD_MINT };
  }

  const user = input.snapshot.user
    ? {
        owner: input.snapshot.user.owner,
        depositRound: asBigInt(input.snapshot.user.depositRound),
        depositAmount: asBigInt(input.snapshot.user.depositAmount),
      }
    : null;
  const pending = authorizedPendingStatus({
    userAuthority: userAuthority.toBase58(),
    user,
    vaultRound: asBigInt(input.snapshot.decoded.round),
  });
  if (pending.kind === "other_owner") {
    return { ok: false, kind: "rejected", message: ACCOUNT_OWNER_MISMATCH };
  }
  if (pending.kind === "stale_round") {
    return { ok: false, kind: "rejected", message: STALE_ROUND };
  }
  if (pending.kind !== "ready") {
    return { ok: false, kind: "rejected", message: NO_PENDING };
  }

  const amount = readBaseUnits(input.amount);
  if (amount === null || amount > pending.amount) {
    return { ok: false, kind: "rejected", message: BAD_AMOUNT };
  }
  const vaultPending = asBigInt(input.snapshot.decoded.totalPendingDeposits);
  if (amount > vaultPending) {
    return { ok: false, kind: "rejected", message: VAULT_PENDING };
  }

  const resolvedDestination = destination.equals(feePayer)
    ? findAssociatedTokenAddress(feePayer, mint)
    : destination;

  const withdraw = instantWithdrawIx(
    { ...input.snapshot, userUnderlyingAta: resolvedDestination.toBase58() },
    userAuthority,
    amount,
  );
  const checked = assertAuthorizedWithdrawAccounts(withdraw, userAuthority, resolvedDestination);
  if (!checked.ok) return { ok: false, kind: "rejected", message: checked.message };

  const createAta = ataCreateIfKnown(feePayer, userAuthority, mint, resolvedDestination);
  return {
    ok: true,
    instructions: createAta ? [createAta, withdraw] : [withdraw],
    summary: `instant_withdraw ${amount} on ${input.snapshot.vault.label}`,
  };
}

export function authorizedSendError(error: unknown): string {
  const message = error instanceof Error ? error.message : "";
  if (/user rejected|rejected the request|cancelled|canceled|denied/i.test(message)) {
    return "The wallet did not sign. Nothing was sent.";
  }
  if (/blockhash|not confirmed|timed out|timeout|ECONNRESET|socket hang up|fetch failed/i.test(message)) {
    return "The network did not confirm the transaction. Check the account before trying again, so it is not sent twice.";
  }
  if (/simulation failed|insufficient|custom program error|Expired|Paused|0x1774|0x1784/i.test(message)) {
    const trimmed = message.length > 280 ? `${message.slice(0, 280)}…` : message;
    return `The transaction was not accepted. Nothing was sent. ${trimmed}`;
  }
  if (message.length > 0 && message.length < 280) {
    return `The send did not finish. ${message}`;
  }
  return "The send did not finish. Check the account before trying again, so it is not sent twice.";
}
