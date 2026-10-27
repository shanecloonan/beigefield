/**
 * Builds remaining Katana user instructions from a vault snapshot.
 * Do not import this file from a client component.
 */
import {
  PublicKey,
  SystemProgram,
  TransactionInstruction,
  SYSVAR_RENT_PUBKEY,
} from "@solana/web3.js";
import {
  ASSOCIATED_TOKEN_PROGRAM,
  KATANA_DISCRIMINATORS,
  TOKEN_PROGRAM,
  type KatanaAction,
} from "@/lib/katana";
import { discriminator, type KatanaSnapshot } from "@/lib/katana-accounts";

export type BuiltInstructions =
  | { ok: true; instructions: TransactionInstruction[]; summary: string }
  | { ok: false; kind: "rejected"; message: string };

const TOKEN_PROGRAM_KEY = new PublicKey(TOKEN_PROGRAM);
const ASSOCIATED_TOKEN_PROGRAM_KEY = new PublicKey(ASSOCIATED_TOKEN_PROGRAM);

function meta(pubkey: PublicKey, isWritable: boolean, isSigner = false) {
  return { pubkey, isWritable, isSigner };
}

function ix(programId: PublicKey, keys: ReturnType<typeof meta>[], data: Buffer): TransactionInstruction {
  return new TransactionInstruction({ programId, keys, data });
}

export function createAtaIdempotent(payer: PublicKey, owner: PublicKey, mint: PublicKey, ata: PublicKey): TransactionInstruction {
  return ix(
    ASSOCIATED_TOKEN_PROGRAM_KEY,
    [
      meta(payer, true, true),
      meta(ata, true),
      meta(owner, false),
      meta(mint, false),
      meta(SystemProgram.programId, false),
      meta(TOKEN_PROGRAM_KEY, false),
    ],
    Buffer.from([1]),
  );
}

function closeTokenAccount(account: PublicKey, dest: PublicKey, owner: PublicKey): TransactionInstruction {
  return ix(TOKEN_PROGRAM_KEY, [meta(account, true), meta(dest, true), meta(owner, false, true)], Buffer.from([9]));
}

function createUserAccountIx(snapshot: KatanaSnapshot, owner: PublicKey): TransactionInstruction {
  return ix(
    new PublicKey(snapshot.programId),
    [
      meta(new PublicKey(snapshot.userAccount), true),
      meta(new PublicKey(snapshot.state), false),
      meta(owner, false),
      meta(owner, true, true),
      meta(SYSVAR_RENT_PUBKEY, false),
      meta(SystemProgram.programId, false),
    ],
    Buffer.concat([discriminator(KATANA_DISCRIMINATORS.create_user_account), Buffer.from([snapshot.userBump])]),
  );
}

function claimSharesIx(snapshot: KatanaSnapshot, owner: PublicKey): TransactionInstruction {
  return ix(
    new PublicKey(snapshot.programId),
    [
      meta(new PublicKey(snapshot.state), true),
      meta(new PublicKey(snapshot.pricePerSharePage), false),
      meta(new PublicKey(snapshot.userAccount), true),
      meta(new PublicKey(snapshot.decoded.underlyingTokenMint), false),
      meta(new PublicKey(snapshot.decoded.derivativeTokenMint), false),
      meta(new PublicKey(snapshot.decoded.derivativeTokenVault), true),
      meta(new PublicKey(snapshot.userDerivativeAta), true),
      meta(new PublicKey(snapshot.decoded.vaultAuthority), true),
      meta(owner, false, true),
      meta(TOKEN_PROGRAM_KEY, false),
    ],
    discriminator(KATANA_DISCRIMINATORS.claim_shares),
  );
}

function withdrawExpiredIx(snapshot: KatanaSnapshot, owner: PublicKey): TransactionInstruction {
  return ix(
    new PublicKey(snapshot.programId),
    [
      meta(new PublicKey(snapshot.state), true),
      meta(new PublicKey(snapshot.decoded.underlyingTokenMint), false),
      meta(new PublicKey(snapshot.decoded.underlyingTokenVault), true),
      meta(new PublicKey(snapshot.userUnderlyingAta), true),
      meta(new PublicKey(snapshot.decoded.derivativeTokenMint), false),
      meta(new PublicKey(snapshot.decoded.derivativeTokenVault), true),
      meta(new PublicKey(snapshot.userDerivativeAta), true),
      meta(new PublicKey(snapshot.pricePerSharePage), false),
      meta(new PublicKey(snapshot.userAccount), true),
      meta(new PublicKey(snapshot.decoded.vaultAuthority), true),
      meta(owner, false, true),
      meta(TOKEN_PROGRAM_KEY, false),
    ],
    discriminator(KATANA_DISCRIMINATORS.withdraw_expired),
  );
}

function completeWithdrawIx(snapshot: KatanaSnapshot, owner: PublicKey): TransactionInstruction {
  return ix(
    new PublicKey(snapshot.programId),
    [
      meta(new PublicKey(snapshot.state), true),
      meta(new PublicKey(snapshot.pricePerSharePage), false),
      meta(new PublicKey(snapshot.userAccount), true),
      meta(new PublicKey(snapshot.decoded.underlyingTokenMint), false),
      meta(new PublicKey(snapshot.decoded.derivativeTokenMint), true),
      meta(new PublicKey(snapshot.decoded.underlyingTokenVault), true),
      meta(new PublicKey(snapshot.decoded.derivativeTokenVault), true),
      meta(new PublicKey(snapshot.userUnderlyingAta), true),
      meta(new PublicKey(snapshot.decoded.vaultAuthority), true),
      meta(owner, false, true),
      meta(TOKEN_PROGRAM_KEY, false),
    ],
    discriminator(KATANA_DISCRIMINATORS.complete_withdraw),
  );
}

export type InstantWithdrawAccounts = {
  programId: string;
  state: string;
  userAccount: string;
  decoded: {
    underlyingTokenMint: string;
    underlyingTokenVault: string;
    vaultAuthority: string;
  };
  userUnderlyingAta: string;
};

export function instantWithdrawIx(snapshot: InstantWithdrawAccounts, owner: PublicKey, amount: bigint): TransactionInstruction {
  const amountBuf = Buffer.alloc(8);
  amountBuf.writeBigUInt64LE(amount);
  return ix(
    new PublicKey(snapshot.programId),
    [
      meta(new PublicKey(snapshot.state), true),
      meta(new PublicKey(snapshot.userAccount), true),
      meta(new PublicKey(snapshot.decoded.underlyingTokenMint), false),
      meta(new PublicKey(snapshot.decoded.underlyingTokenVault), true),
      meta(new PublicKey(snapshot.userUnderlyingAta), true),
      meta(new PublicKey(snapshot.decoded.vaultAuthority), true),
      meta(owner, false, true),
      meta(TOKEN_PROGRAM_KEY, false),
    ],
    Buffer.concat([discriminator(KATANA_DISCRIMINATORS.instant_withdraw), amountBuf]),
  );
}

function closeUserAccountIx(snapshot: KatanaSnapshot, owner: PublicKey): TransactionInstruction {
  return ix(
    new PublicKey(snapshot.programId),
    [
      meta(new PublicKey(snapshot.userAccount), true),
      meta(new PublicKey(snapshot.state), false),
      meta(owner, false, true),
    ],
    discriminator(KATANA_DISCRIMINATORS.close_user_account),
  );
}

function needPosition(snapshot: KatanaSnapshot): boolean {
  const deposit = snapshot.user?.depositAmount ?? BigInt(0);
  const unredeemed = snapshot.user?.unredeemedShares ?? BigInt(0);
  const queued = snapshot.user?.withdrawShares ?? BigInt(0);
  return deposit > BigInt(0) || unredeemed > BigInt(0) || queued > BigInt(0) || snapshot.userDerivative > BigInt(0);
}

export function buildKatanaInstructions(input: {
  action: KatanaAction;
  snapshot: KatanaSnapshot;
  owner: PublicKey;
  amount?: bigint;
}): BuiltInstructions {
  const { action, snapshot, owner } = input;
  const unredeemed = snapshot.user?.unredeemedShares ?? BigInt(0);
  const queued = snapshot.user?.withdrawShares ?? BigInt(0);
  const deposit = snapshot.user?.depositAmount ?? BigInt(0);
  const instructions: TransactionInstruction[] = [];

  if (action === "close_user_account") {
    if (!snapshot.user) {
      return { ok: false, kind: "rejected", message: "No Katana user account on this vault. Nothing was sent." };
    }
    return {
      ok: true,
      instructions: [closeUserAccountIx(snapshot, owner)],
      summary: `close_user_account on ${snapshot.vault.label}`,
    };
  }

  if (action === "claim_shares") {
    if (unredeemed <= BigInt(0)) {
      return { ok: false, kind: "rejected", message: "No unredeemed Katana shares on this vault. Nothing was sent." };
    }
    instructions.push(
      createAtaIdempotent(
        owner,
        owner,
        new PublicKey(snapshot.decoded.derivativeTokenMint),
        new PublicKey(snapshot.userDerivativeAta),
      ),
      claimSharesIx(snapshot, owner),
    );
    return { ok: true, instructions, summary: `claim_shares on ${snapshot.vault.label}` };
  }

  if (action === "instant_withdraw") {
    const amount = input.amount;
    if (amount === undefined || amount <= BigInt(0)) {
      return { ok: false, kind: "rejected", message: "The instant withdraw amount is missing. Nothing was sent." };
    }
    if (!snapshot.user || deposit <= BigInt(0)) {
      return { ok: false, kind: "rejected", message: "No pending Katana deposit on this vault. Nothing was sent." };
    }
    instructions.push(
      createAtaIdempotent(
        owner,
        owner,
        new PublicKey(snapshot.decoded.underlyingTokenMint),
        new PublicKey(snapshot.userUnderlyingAta),
      ),
      instantWithdrawIx(snapshot, owner, amount),
    );
    if (snapshot.nativeUnderlying) {
      instructions.push(
        closeTokenAccount(new PublicKey(snapshot.userUnderlyingAta), owner, owner),
      );
    }
    return { ok: true, instructions, summary: `instant_withdraw ${amount} on ${snapshot.vault.label}` };
  }

  if (action === "complete_withdraw") {
    if (!snapshot.user || queued <= BigInt(0)) {
      return {
        ok: false,
        kind: "rejected",
        message: "No queued Katana withdrawal on this vault. Nothing was sent.",
      };
    }
    instructions.push(
      createAtaIdempotent(
        owner,
        owner,
        new PublicKey(snapshot.decoded.underlyingTokenMint),
        new PublicKey(snapshot.userUnderlyingAta),
      ),
      completeWithdrawIx(snapshot, owner),
    );
    if (snapshot.nativeUnderlying) {
      instructions.push(
        closeTokenAccount(new PublicKey(snapshot.userUnderlyingAta), owner, owner),
      );
    }
    return { ok: true, instructions, summary: `complete_withdraw on ${snapshot.vault.label}` };
  }

  if (action === "withdraw_expired" || action === "exit") {
    if (!snapshot.decoded.expired) {
      return {
        ok: false,
        kind: "rejected",
        message: "This vault is not expired. withdraw_expired was not sent.",
      };
    }
    const willClaim = action === "exit" && unredeemed > BigInt(0);
    if (!willClaim && snapshot.userDerivative <= BigInt(0)) {
      return {
        ok: false,
        kind: "rejected",
        message: "No Katana shares to withdraw on this vault. Nothing was sent.",
      };
    }
    if (!snapshot.user && snapshot.userDerivative <= BigInt(0) && !willClaim) {
      return { ok: false, kind: "rejected", message: "No Katana position on this vault. Nothing was sent." };
    }
    if (!snapshot.user) {
      instructions.push(createUserAccountIx(snapshot, owner));
    }
    instructions.push(
      createAtaIdempotent(
        owner,
        owner,
        new PublicKey(snapshot.decoded.derivativeTokenMint),
        new PublicKey(snapshot.userDerivativeAta),
      ),
      createAtaIdempotent(
        owner,
        owner,
        new PublicKey(snapshot.decoded.underlyingTokenMint),
        new PublicKey(snapshot.userUnderlyingAta),
      ),
    );
    if (willClaim) instructions.push(claimSharesIx(snapshot, owner));
    instructions.push(withdrawExpiredIx(snapshot, owner));
    if (snapshot.nativeUnderlying) {
      instructions.push(
        closeTokenAccount(new PublicKey(snapshot.userUnderlyingAta), owner, owner),
      );
    }
    const name = willClaim ? "claim_shares + withdraw_expired" : "withdraw_expired";
    return { ok: true, instructions, summary: `${name} on ${snapshot.vault.label}` };
  }

  if (!needPosition(snapshot)) {
    return { ok: false, kind: "rejected", message: "No Katana position on this vault. Nothing was sent." };
  }
  return { ok: false, kind: "rejected", message: "The instruction is not a remaining Katana action. Nothing was sent." };
}
