/**
 * RPC helpers for Katana vault state and the desk user's vault account.
 * Safe to import from route handlers. No key material.
 */
import {
  decodeState,
  decodeUserAccount,
  deriveVaultAddresses,
  parseSolPubkey,
  readTokenAmount,
  type KatanaSnapshot,
} from "@/lib/katana-accounts";
import { authorizedLookupFromSnapshot, type KatanaAuthorizedLookupOk } from "@/lib/katana-authorized";
import { katanaProgramId, katanaVault } from "@/lib/katana";
import { pathLookupNote, suggestKatanaAction, type KatanaPathDefaultsOk } from "@/lib/katana-path-run";
import { SOL_FUNDED_WALLET_ADDRESS, isSolAddress } from "@/lib/sol-funded-wallet-public";

export type KatanaQueryDeps = {
  fetchImpl?: typeof fetch;
  rpc?: string;
};

type QueryFailure = { ok: false; status: number; message: string };
export type KatanaPathDefaultsResult = KatanaPathDefaultsOk | QueryFailure;
export type KatanaSnapshotResult = { ok: true; snapshot: KatanaSnapshot } | QueryFailure;
export type KatanaAuthorizedLookupResult = KatanaAuthorizedLookupOk | QueryFailure;
export type KatanaBlockhashResult =
  | { ok: true; blockhash: string; lastValidBlockHeight: number }
  | QueryFailure;

const RPC_DOWN = "The Solana RPC did not answer the Katana vault query.";
const RPC_SHAPE = "The Katana vault account could not be read.";

function configured(name: string): string | undefined {
  const value = process.env[name];
  if (typeof value !== "string") return undefined;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : undefined;
}

export function solanaRpc(): string {
  return configured("SOLANA_RPC") ?? "https://api.mainnet-beta.solana.com";
}

type RpcAccount = { data: [string, string]; lamports: number; owner: string } | null;

async function getMultipleAccounts(
  rpc: string,
  keys: string[],
  fetchImpl: typeof fetch,
): Promise<{ ok: true; accounts: RpcAccount[] } | QueryFailure> {
  let response: Response;
  try {
    response = await fetchImpl(rpc, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        jsonrpc: "2.0",
        id: 1,
        method: "getMultipleAccounts",
        params: [keys, { encoding: "base64", commitment: "confirmed" }],
      }),
      cache: "no-store",
      signal: AbortSignal.timeout(12_000),
    });
  } catch {
    return { ok: false, status: 502, message: RPC_DOWN };
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    return { ok: false, status: 502, message: RPC_SHAPE };
  }
  if (!response.ok || !payload || typeof payload !== "object") {
    return { ok: false, status: 502, message: RPC_DOWN };
  }
  const result = (payload as { result?: { value?: unknown } }).result;
  const value = result && typeof result === "object" ? result.value : null;
  if (!Array.isArray(value) || value.length !== keys.length) {
    return { ok: false, status: 502, message: RPC_SHAPE };
  }
  const accounts: RpcAccount[] = [];
  for (const item of value) {
    if (item === null) {
      accounts.push(null);
      continue;
    }
    if (!item || typeof item !== "object") {
      return { ok: false, status: 502, message: RPC_SHAPE };
    }
    const record = item as { data?: unknown; lamports?: unknown; owner?: unknown };
    if (!Array.isArray(record.data) || typeof record.data[0] !== "string") {
      return { ok: false, status: 502, message: RPC_SHAPE };
    }
    if (typeof record.lamports !== "number" || typeof record.owner !== "string") {
      return { ok: false, status: 502, message: RPC_SHAPE };
    }
    accounts.push({ data: [record.data[0], String(record.data[1] ?? "base64")], lamports: record.lamports, owner: record.owner });
  }
  return { ok: true, accounts };
}

function accountData(account: RpcAccount): Buffer | null {
  if (!account) return null;
  try {
    return Buffer.from(account.data[0], "base64");
  } catch {
    return null;
  }
}

export async function loadKatanaSnapshot(
  input: { owner?: string; state?: string },
  deps: KatanaQueryDeps = {},
): Promise<KatanaSnapshotResult> {
  const ownerText = (input.owner?.trim() || SOL_FUNDED_WALLET_ADDRESS).trim();
  if (!isSolAddress(ownerText)) {
    return { ok: false, status: 400, message: "Enter a Solana address." };
  }
  const owner = parseSolPubkey(ownerText);
  if (!owner) {
    return { ok: false, status: 400, message: "Enter a Solana address." };
  }
  const vault = katanaVault(input.state?.trim() || "");
  if (!vault) {
    return { ok: false, status: 400, message: "Choose a listed Katana vault." };
  }

  const programId = katanaProgramId(vault.program);
  const first = await getMultipleAccounts(
    (deps.rpc ?? solanaRpc()).replace(/\/$/, ""),
    [vault.state],
    deps.fetchImpl ?? fetch,
  );
  if (!first.ok) return first;
  const stateAccount = first.accounts[0];
  if (!stateAccount) {
    return { ok: false, status: 502, message: RPC_SHAPE };
  }
  if (stateAccount.owner !== programId) {
    return { ok: false, status: 502, message: RPC_SHAPE };
  }
  const stateData = accountData(stateAccount);
  if (!stateData) return { ok: false, status: 502, message: RPC_SHAPE };
  const decoded = decodeState(stateData, vault.program);
  if (!decoded) return { ok: false, status: 502, message: RPC_SHAPE };

  const derived = deriveVaultAddresses(vault, decoded, owner);

  const rpc = (deps.rpc ?? solanaRpc()).replace(/\/$/, "");
  const rest = await getMultipleAccounts(
    rpc,
    [
      derived.userAccount.toBase58(),
      derived.userUnderlyingAta.toBase58(),
      derived.userDerivativeAta.toBase58(),
      decoded.underlyingTokenVault,
      owner.toBase58(),
    ],
    deps.fetchImpl ?? fetch,
  );
  if (!rest.ok) return rest;
  const [userAccount, , derivativeAta, vaultToken, ownerAccount] = rest.accounts;
  if (userAccount && userAccount.owner !== programId) {
    return { ok: false, status: 502, message: RPC_SHAPE };
  }
  const userData = accountData(userAccount);
  const user = userData ? decodeUserAccount(userData) : null;
  if (userAccount && !user) {
    return { ok: false, status: 502, message: RPC_SHAPE };
  }

  return {
    ok: true,
    snapshot: {
      vault,
      programId,
      state: vault.state,
      decoded,
      userAccount: derived.userAccount.toBase58(),
      userBump: derived.userBump,
      user,
      pricePerSharePage: derived.pricePerSharePage.toBase58(),
      userUnderlyingAta: derived.userUnderlyingAta.toBase58(),
      userDerivativeAta: derived.userDerivativeAta.toBase58(),
      userDerivative: readTokenAmount(accountData(derivativeAta ?? null)),
      vaultBalance: vaultToken ? readTokenAmount(accountData(vaultToken)) : null,
      lamports: BigInt(ownerAccount?.lamports ?? 0),
      nativeUnderlying: derived.nativeUnderlying,
    },
  };
}

export async function loadKatanaPathDefaults(
  input: { owner?: string; state?: string },
  deps: KatanaQueryDeps = {},
): Promise<KatanaPathDefaultsResult> {
  const loaded = await loadKatanaSnapshot(input, deps);
  if (!loaded.ok) return loaded;
  return defaultsFromSnapshot(loaded.snapshot, input.owner?.trim() || SOL_FUNDED_WALLET_ADDRESS);
}

export function defaultsFromSnapshot(snapshot: KatanaSnapshot, owner: string): KatanaPathDefaultsOk {
  const suggested = suggestKatanaAction({
    expired: snapshot.decoded.expired,
    userAccount: snapshot.user !== null,
    userDeposit: snapshot.user?.depositAmount ?? BigInt(0),
    userUnredeemed: snapshot.user?.unredeemedShares ?? BigInt(0),
    userWithdrawShares: snapshot.user?.withdrawShares ?? BigInt(0),
    userDerivative: snapshot.userDerivative,
  });
  return {
    ok: true,
    owner,
    state: snapshot.state,
    program: snapshot.programId,
    label: snapshot.vault.label,
    strategy: snapshot.vault.strategy,
    expired: snapshot.decoded.expired,
    paused: snapshot.decoded.paused,
    round: snapshot.decoded.round.toString(),
    total_shares: snapshot.decoded.totalShares.toString(),
    pending_deposits: snapshot.decoded.totalPendingDeposits.toString(),
    queued_withdraw_shares: snapshot.decoded.queuedWithdrawShares.toString(),
    locked_amount: snapshot.decoded.lockedAmount.toString(),
    vault_balance: snapshot.vaultBalance === null ? null : snapshot.vaultBalance.toString(),
    user_account: snapshot.user !== null,
    user_deposit: (snapshot.user?.depositAmount ?? BigInt(0)).toString(),
    user_unredeemed: (snapshot.user?.unredeemedShares ?? BigInt(0)).toString(),
    user_withdraw_shares: (snapshot.user?.withdrawShares ?? BigInt(0)).toString(),
    user_derivative: snapshot.userDerivative.toString(),
    suggested,
    deposit_enabled: false,
    migrate_enabled: false,
    lamports: snapshot.lamports.toString(),
  };
}

export async function loadKatanaAuthorizedLookup(
  input: { owner?: string; state?: string },
  deps: KatanaQueryDeps = {},
): Promise<KatanaAuthorizedLookupResult> {
  const owner = input.owner?.trim() ?? "";
  if (!isSolAddress(owner)) {
    return { ok: false, status: 400, message: "Connect a Solana wallet." };
  }
  if (!katanaVault(input.state?.trim() || "")) {
    return { ok: false, status: 400, message: "Choose a listed Katana vault." };
  }
  const loaded = await loadKatanaSnapshot({ owner, state: input.state }, deps);
  if (!loaded.ok) return loaded;
  return authorizedLookupFromSnapshot(loaded.snapshot, owner);
}

export async function loadLatestBlockhash(deps: KatanaQueryDeps = {}): Promise<KatanaBlockhashResult> {
  const rpc = (deps.rpc ?? solanaRpc()).replace(/\/$/, "");
  const fetchImpl = deps.fetchImpl ?? fetch;
  let response: Response;
  try {
    response = await fetchImpl(rpc, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        jsonrpc: "2.0",
        id: 1,
        method: "getLatestBlockhash",
        params: [{ commitment: "confirmed" }],
      }),
      cache: "no-store",
      signal: AbortSignal.timeout(12_000),
    });
  } catch {
    return { ok: false, status: 502, message: "The Solana RPC did not answer the blockhash query." };
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    return { ok: false, status: 502, message: "The Solana RPC did not return a recent blockhash." };
  }
  if (!response.ok || !payload || typeof payload !== "object") {
    return { ok: false, status: 502, message: "The Solana RPC did not answer the blockhash query." };
  }
  const result = (payload as { result?: { value?: unknown } }).result;
  const value = result && typeof result === "object" ? (result as { value?: unknown }).value : null;
  if (!value || typeof value !== "object") {
    return { ok: false, status: 502, message: "The Solana RPC did not return a recent blockhash." };
  }
  const record = value as { blockhash?: unknown; lastValidBlockHeight?: unknown };
  if (typeof record.blockhash !== "string" || record.blockhash.length === 0) {
    return { ok: false, status: 502, message: "The Solana RPC did not return a recent blockhash." };
  }
  if (typeof record.lastValidBlockHeight !== "number" || !Number.isFinite(record.lastValidBlockHeight)) {
    return { ok: false, status: 502, message: "The Solana RPC did not return a recent blockhash." };
  }
  return { ok: true, blockhash: record.blockhash, lastValidBlockHeight: record.lastValidBlockHeight };
}

export function snapshotLookupNote(snapshot: KatanaSnapshot): string {
  const defaults = defaultsFromSnapshot(snapshot, "");
  return pathLookupNote({
    expired: defaults.expired,
    paused: defaults.paused,
    round: defaults.round,
    suggested: defaults.suggested,
    userDeposit: defaults.user_deposit,
    userUnredeemed: defaults.user_unredeemed,
    userWithdrawShares: defaults.user_withdraw_shares,
    userDerivative: defaults.user_derivative,
    lamports: defaults.lamports,
  });
}
