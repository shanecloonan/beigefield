/**
 * Katana structured-product vaults on Solana mainnet.
 * Program ids and account layouts follow `@katana-hq/sdk` 0.5.9 (Dec 2022),
 * which matches the program binaries deployed at slots 164458800 and 164459070.
 * The IDL accounts on chain were last written in Feb 2022 and are stale.
 * The State keys below are every `State` account both programs own.
 * Safe for the client bundle. No key material and no web3 import.
 */

export const KATANA_STRUCTURED_PROGRAM = "1349iiGjWC7ZTbu6otFmJwztms122jEEnShKgpVnNewy";
export const KATANA_STRUCTURED_GENERIC_PROGRAM = "7h7uYbDBZkiTvWLmMsWNAEs2VVNqfV56uSfP9hbjJMP8";

export const TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA";
export const ASSOCIATED_TOKEN_PROGRAM = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL";
export const SYSTEM_PROGRAM = "11111111111111111111111111111111";
export const RENT_SYSVAR = "SysvarRent111111111111111111111111111111111";
export const NATIVE_MINT = "So11111111111111111111111111111111111111112";

export const ROUNDS_PER_PAGE = 128;

/** SPL token account size. Used when unwrapping native SOL after a withdraw. */
export const TOKEN_ACCOUNT_SIZE = 165;

export type KatanaProgramKind = "structured" | "structuredGeneric";

export type KatanaVault = {
  state: string;
  program: KatanaProgramKind;
  label: string;
  strategy: "Covered call" | "Secured put" | "Unlisted";
};

export const KATANA_VAULTS: readonly KatanaVault[] = [
  { state: "EfN1NMcv3nBRANNP3JJNErwk5B6sDzAephivYpnJJAnD", program: "structured", label: "SOL", strategy: "Covered call" },
  { state: "DkguYGWhRE8qJ9voWNYZ8dJkGYr8ACUR8KXqDAyHpGx2", program: "structured", label: "mSOL", strategy: "Covered call" },
  { state: "CPFuWtS7qNQt3RPnSt5opKph9JbqdW3LjxF1HEw3v1tP", program: "structured", label: "stSOL", strategy: "Covered call" },
  { state: "bWWGqvth3WJQ3vJBcR97Mi3JSb9szr1brVqsiqMtRfv", program: "structured", label: "cSOL", strategy: "Covered call" },
  { state: "2xfzirMwQaC1zbiRzS7PAb5tEeeBNDxxJmbK5GyHWdUw", program: "structured", label: "scnSOL", strategy: "Covered call" },
  { state: "8dENNXaNmuEFNkHRwzAyqMtzqe8TmbnrCMtoJdRAp3oh", program: "structured", label: "soBTC", strategy: "Covered call" },
  { state: "HxqxMsf6SMFCZXZFinZMTdxQxVG3Tgv5ECz9zXYmxMAC", program: "structured", label: "soETH", strategy: "Covered call" },
  { state: "4CVmhfkF7Hcu2ygzsnqj6Sc8xswkneHMXtQ43xuPjmjP", program: "structured", label: "whETH", strategy: "Covered call" },
  { state: "7d3eTAxqfX9USUv7mFpvwoNnMswHVyNC2cYzWAUEZ9cT", program: "structured", label: "wLUNA", strategy: "Covered call" },
  { state: "8BtfxVEHvr2JDjwvQeqGs8tQWd5Hmj4q8RZxugLZ4ofA", program: "structured", label: "MNGO", strategy: "Covered call" },
  { state: "8oNjcwDKYUCrDiaUErpLoqLE54LXDDkMVMRKB3Q4Wx1R", program: "structured", label: "wINJ", strategy: "Covered call" },
  { state: "DVQKUnjyxMmLRCm5FKVLogo7YS94oqay6SNrb3EqxKn4", program: "structured", label: "SRM", strategy: "Covered call" },
  { state: "FLE3gtCSKr8Lx3Gk1Eec4ww1cknJSJuvVSsots6zYMWn", program: "structured", label: "soFTT", strategy: "Covered call" },
  { state: "GtutWPSU1yrepoPi94yVE5LSnx7jaLnwUPattZKygZJE", program: "structured", label: "RAY", strategy: "Covered call" },
  { state: "HfFQMWPGSsMyuWLBhZa2vFY7RDfZVqAFyUUqUdu7Mk3m", program: "structured", label: "SNY", strategy: "Covered call" },
  { state: "24QxCvmPvfXdBsP5dWcu8ubhRqJQcYjWzPvZfGVT56iX", program: "structured", label: "EzfgjvkS…", strategy: "Unlisted" },
  { state: "BNVXto8cewpGLADCw8aC23DZCaZtGBPVGebGo7N6JUb8", program: "structured", label: "WytxcRxm…", strategy: "Unlisted" },
  { state: "EAZkJsvHKet3bDoYfNq5rA8Bi5gsbqBBuGrP4m1xUugb", program: "structured", label: "Dkm4DLrh…", strategy: "Unlisted" },
  { state: "FrQqy3qZcbpe379nEnK5bfXx6r26JwEa9sBj89oziiQU", program: "structuredGeneric", label: "SOL", strategy: "Secured put" },
  { state: "56rxYfs2q3VSRhtwa13QjXUTv8d6S2xq3WaaTVAfYkwp", program: "structuredGeneric", label: "soBTC", strategy: "Secured put" },
  { state: "FA17pr8A2HyYsUdGTTaPwAbGbCx8xyaDtjt1CY5AvSgS", program: "structuredGeneric", label: "soETH", strategy: "Secured put" },
  { state: "nqhyYsXxoVQcDnkqjCct6xtSDL7grcQ6pGTn9TibaDy", program: "structuredGeneric", label: "SOL (round 1)", strategy: "Unlisted" },
  { state: "DM8Ak3e4F3qkjQ7LVYVQTdDXrYojMsAUUbvzuP7wjxRX", program: "structuredGeneric", label: "SOL (round 1)", strategy: "Unlisted" },
];

export const DEFAULT_KATANA_VAULT = KATANA_VAULTS[0].state;

export function katanaVault(state: string): KatanaVault | undefined {
  return KATANA_VAULTS.find((vault) => vault.state === state);
}

export function katanaVaultLabel(vault: KatanaVault): string {
  return `${vault.label} · ${vault.strategy}`;
}

export function katanaProgramId(kind: KatanaProgramKind): string {
  return kind === "structured" ? KATANA_STRUCTURED_PROGRAM : KATANA_STRUCTURED_GENERIC_PROGRAM;
}

/**
 * User instructions the deployed programs still accept for an expired vault.
 * `deposit` is not here: an expired vault rejects it with `Expired` (6028).
 * Migration is not here: it deposited into PsyFi, which shut down on 1 May 2025.
 */
export const KATANA_ACTIONS = [
  "exit",
  "claim_shares",
  "withdraw_expired",
  "complete_withdraw",
  "instant_withdraw",
  "close_user_account",
] as const;

export type KatanaAction = (typeof KATANA_ACTIONS)[number];

export function isKatanaAction(value: unknown): value is KatanaAction {
  return typeof value === "string" && (KATANA_ACTIONS as readonly string[]).includes(value);
}

export function katanaActionNeedsAmount(action: KatanaAction): boolean {
  return action === "instant_withdraw";
}

export const KATANA_ACTION_LABELS: Record<KatanaAction, string> = {
  exit: "Claim and withdraw",
  claim_shares: "claim_shares",
  withdraw_expired: "withdraw_expired",
  complete_withdraw: "complete_withdraw",
  instant_withdraw: "instant_withdraw",
  close_user_account: "close_user_account",
};

/** Anchor discriminators: the first 8 bytes of sha256("global:<name>") or sha256("account:<Name>"). */
export const KATANA_DISCRIMINATORS = {
  claim_shares: "82831ded86146ef5",
  withdraw_expired: "3a28cea3503b1f01",
  complete_withdraw: "ac818d115ffdfb62",
  instant_withdraw: "ab3191b0306570a2",
  create_user_account: "924464453f2eb6c7",
  close_user_account: "ecb50347c21297bf",
  State: "d8926b5e684bb6b1",
  UserVaultAccount: "dacbeeef8c3bbac6",
} as const;

export function solExplorerTxUrl(signature: string): string {
  return `https://solscan.io/tx/${encodeURIComponent(signature)}`;
}

export function solExplorerAccountUrl(address: string): string {
  return `https://solscan.io/account/${encodeURIComponent(address)}`;
}

/** Base-unit integer string for an amount field. */
export function readBaseUnits(value: unknown): bigint | null {
  if (typeof value !== "string" || !/^\d{1,20}$/.test(value.trim())) return null;
  const parsed = BigInt(value.trim());
  if (parsed <= BigInt(0) || parsed > BigInt("18446744073709551615")) return null;
  return parsed;
}
