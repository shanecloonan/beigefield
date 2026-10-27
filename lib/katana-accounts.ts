/**
 * PDAs and account decoders for Katana structured vaults.
 * Layouts follow `@katana-hq/sdk` 0.5.9. Safe to import from server modules
 * and tests. Do not import from a client component.
 */
import { PublicKey } from "@solana/web3.js";
import {
  ASSOCIATED_TOKEN_PROGRAM,
  KATANA_DISCRIMINATORS,
  NATIVE_MINT,
  ROUNDS_PER_PAGE,
  TOKEN_PROGRAM,
  katanaProgramId,
  type KatanaProgramKind,
  type KatanaVault,
} from "@/lib/katana";

const STATE_SEED = Buffer.from("state");
const USER_SEED = Buffer.from("user-account");
const PRICE_SEED = Buffer.from("price-per-share");
const VAULT_SEED = Buffer.from("vault");
const AUTHORITY_SEED = Buffer.from("authority");

export function parseSolPubkey(value: string): PublicKey | null {
  try {
    const key = new PublicKey(value);
    if (key.toBase58() !== value) return null;
    return key;
  } catch {
    return null;
  }
}

export function discriminator(hex: string): Buffer {
  return Buffer.from(hex, "hex");
}

export function pageIndexSeed(pageIndex: number): Buffer {
  const page = Buffer.alloc(16);
  page.writeInt32LE(pageIndex, 0);
  return page;
}

export function identitySeeds(input: {
  kind: KatanaProgramKind;
  underlyingMint: PublicKey;
  quoteMint: PublicKey;
  identifier: PublicKey | null;
}): Buffer[] {
  if (input.kind === "structured") return [input.underlyingMint.toBuffer()];
  if (!input.identifier) throw new Error("Generic vault is missing its identifier.");
  return [input.underlyingMint.toBuffer(), input.quoteMint.toBuffer(), input.identifier.toBuffer()];
}

export function findStateAddress(
  input: {
    kind: KatanaProgramKind;
    underlyingMint: PublicKey;
    quoteMint: PublicKey;
    identifier: PublicKey | null;
  },
  programId: PublicKey,
): [PublicKey, number] {
  return PublicKey.findProgramAddressSync([STATE_SEED, ...identitySeeds(input)], programId);
}

export function findUserAccountAddress(
  owner: PublicKey,
  state: PublicKey,
  programId: PublicKey,
): [PublicKey, number] {
  return PublicKey.findProgramAddressSync([USER_SEED, owner.toBuffer(), state.toBuffer()], programId);
}

export function findPricePerShareAddress(
  input: {
    kind: KatanaProgramKind;
    underlyingMint: PublicKey;
    quoteMint: PublicKey;
    identifier: PublicKey | null;
    pageIndex: number;
  },
  programId: PublicKey,
): [PublicKey, number] {
  return PublicKey.findProgramAddressSync(
    [...[PRICE_SEED, ...identitySeeds(input)], pageIndexSeed(input.pageIndex)],
    programId,
  );
}

export function findVaultAuthorityAddress(
  input: {
    kind: KatanaProgramKind;
    underlyingMint: PublicKey;
    quoteMint: PublicKey;
    identifier: PublicKey | null;
  },
  programId: PublicKey,
): [PublicKey, number] {
  return PublicKey.findProgramAddressSync(
    [VAULT_SEED, ...identitySeeds(input), AUTHORITY_SEED],
    programId,
  );
}

export function findAssociatedTokenAddress(owner: PublicKey, mint: PublicKey): PublicKey {
  return PublicKey.findProgramAddressSync(
    [owner.toBuffer(), new PublicKey(TOKEN_PROGRAM).toBuffer(), mint.toBuffer()],
    new PublicKey(ASSOCIATED_TOKEN_PROGRAM),
  )[0];
}

export type DecodedState = {
  kind: KatanaProgramKind;
  admin: string;
  vaultAuthority: string;
  cap: bigint;
  lockedAmount: bigint;
  totalPendingDeposits: bigint;
  queuedWithdrawShares: bigint;
  totalShares: bigint;
  round: bigint;
  underlyingTokenMint: string;
  quoteTokenMint: string;
  identifier: string | null;
  derivativeTokenMint: string;
  underlyingTokenVault: string;
  derivativeTokenVault: string;
  decimals: number;
  expired: boolean;
  paused: boolean;
};

export type DecodedUser = {
  owner: string;
  depositRound: bigint;
  /** `depositData.amount` is a u64 at account offset 0x38. */
  depositAmount: bigint;
  unredeemedShares: bigint;
  withdrawRound: bigint;
  withdrawShares: bigint;
  bump: number;
};

function readU128(data: Buffer, offset: number): bigint {
  return data.readBigUInt64LE(offset) + (data.readBigUInt64LE(offset + 8) << BigInt(64));
}

function readPubkey(data: Buffer, offset: number): string {
  return new PublicKey(data.subarray(offset, offset + 32)).toBase58();
}

function hasDisc(data: Buffer, hex: string): boolean {
  return data.length >= 8 && data.subarray(0, 8).equals(discriminator(hex));
}

export function decodeState(data: Buffer, kind: KatanaProgramKind): DecodedState | null {
  if (!hasDisc(data, KATANA_DISCRIMINATORS.State)) return null;
  const shift = kind === "structuredGeneric" ? 32 : 0;
  const o = 8 + shift;
  if (data.length < o + 733) return null;
  return {
    kind,
    admin: readPubkey(data, o),
    vaultAuthority: readPubkey(data, o + 64),
    cap: readU128(data, o + 96),
    lockedAmount: readU128(data, o + 112),
    totalPendingDeposits: readU128(data, o + 144),
    queuedWithdrawShares: readU128(data, o + 160),
    totalShares: readU128(data, o + 176),
    round: readU128(data, o + 192),
    underlyingTokenMint: readPubkey(data, o + 208),
    quoteTokenMint: readPubkey(data, o + 240),
    identifier: kind === "structuredGeneric" ? readPubkey(data, 8) : null,
    derivativeTokenMint: readPubkey(data, o + 464),
    underlyingTokenVault: readPubkey(data, o + 528),
    derivativeTokenVault: readPubkey(data, o + 656),
    decimals: data[o + 720] ?? 0,
    expired: data[o + 463] === 1,
    paused: data[o + 731] === 1,
  };
}

export function decodeUserAccount(data: Buffer): DecodedUser | null {
  if (!hasDisc(data, KATANA_DISCRIMINATORS.UserVaultAccount)) return null;
  if (data.length < 121) return null;
  return {
    owner: readPubkey(data, 8),
    depositRound: readU128(data, 40),
    depositAmount: data.readBigUInt64LE(56),
    unredeemedShares: readU128(data, 72),
    withdrawRound: readU128(data, 88),
    withdrawShares: readU128(data, 104),
    bump: data[120] ?? 0,
  };
}

/** SPL token amount at offset 64. Missing or short accounts are zero. */
export function readTokenAmount(data: Buffer | null): bigint {
  if (!data || data.length < 72) return BigInt(0);
  return data.readBigUInt64LE(64);
}

export function pricePageIndex(round: bigint): number {
  const value = Number(round);
  if (!Number.isSafeInteger(value) || value < 0) return 0;
  return Math.floor(value / ROUNDS_PER_PAGE);
}

export type KatanaSnapshot = {
  vault: KatanaVault;
  programId: string;
  state: string;
  decoded: DecodedState;
  userAccount: string;
  userBump: number;
  user: DecodedUser | null;
  pricePerSharePage: string;
  userUnderlyingAta: string;
  userDerivativeAta: string;
  userDerivative: bigint;
  vaultBalance: bigint | null;
  lamports: bigint;
  nativeUnderlying: boolean;
};

export function deriveVaultAddresses(vault: KatanaVault, decoded: DecodedState, owner: PublicKey): {
  programId: PublicKey;
  state: PublicKey;
  userAccount: PublicKey;
  userBump: number;
  pricePerSharePage: PublicKey;
  userUnderlyingAta: PublicKey;
  userDerivativeAta: PublicKey;
  nativeUnderlying: boolean;
} {
  const programId = new PublicKey(katanaProgramId(vault.program));
  const state = new PublicKey(vault.state);
  const underlying = new PublicKey(decoded.underlyingTokenMint);
  const quote = new PublicKey(decoded.quoteTokenMint);
  const identifier = decoded.identifier ? new PublicKey(decoded.identifier) : null;
  const identity = { kind: vault.program, underlyingMint: underlying, quoteMint: quote, identifier };
  const [userAccount, userBump] = findUserAccountAddress(owner, state, programId);
  const [pricePerSharePage] = findPricePerShareAddress(
    { ...identity, pageIndex: pricePageIndex(decoded.round) },
    programId,
  );
  return {
    programId,
    state,
    userAccount,
    userBump,
    pricePerSharePage,
    userUnderlyingAta: findAssociatedTokenAddress(owner, underlying),
    userDerivativeAta: findAssociatedTokenAddress(owner, new PublicKey(decoded.derivativeTokenMint)),
    nativeUnderlying: decoded.underlyingTokenMint === NATIVE_MINT,
  };
}
