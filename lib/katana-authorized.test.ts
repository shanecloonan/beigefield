import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { PublicKey } from "@solana/web3.js";
import { DEFAULT_KATANA_VAULT, KATANA_DISCRIMINATORS, KATANA_STRUCTURED_PROGRAM, KATANA_VAULTS, NATIVE_MINT } from "./katana";
import { findAssociatedTokenAddress, type KatanaSnapshot } from "./katana-accounts";
import {
  assertAuthorizedWithdrawAccounts,
  authorizedLookupFromSnapshot,
  authorizedPendingStatus,
  authorizedSendError,
  buildAuthorizedInstantWithdraw,
  formatTokenAmount,
  readAuthorizedBlockhash,
  readAuthorizedLookup,
  snapshotFromAuthorizedLookup,
} from "./katana-authorized";
import { loadKatanaAuthorizedLookup } from "./katana-query";
import { SOL_FUNDED_WALLET_ADDRESS } from "./sol-funded-wallet-public";

const owner = new PublicKey(SOL_FUNDED_WALLET_ADDRESS);
const other = new PublicKey("11111111111111111111111111111112");
const mint = new PublicKey(NATIVE_MINT);
const ownerAta = findAssociatedTokenAddress(owner, mint);

function snapshot(patch: Partial<KatanaSnapshot> = {}, userPatch: Partial<NonNullable<KatanaSnapshot["user"]>> = {}): KatanaSnapshot {
  const vault = KATANA_VAULTS[0];
  if (!vault) throw new Error("vault");
  return {
    vault,
    programId: KATANA_STRUCTURED_PROGRAM,
    state: vault.state,
    decoded: {
      kind: vault.program,
      admin: SOL_FUNDED_WALLET_ADDRESS,
      vaultAuthority: "7wM6TyhDZMJSYojLbZWPcmkMu11xErKu6oeGJoHqtUgV",
      cap: BigInt(0),
      lockedAmount: BigInt(0),
      totalPendingDeposits: BigInt(0),
      queuedWithdrawShares: BigInt(0),
      totalShares: BigInt(1),
      round: BigInt(63),
      underlyingTokenMint: NATIVE_MINT,
      quoteTokenMint: "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
      identifier: null,
      derivativeTokenMint: "J58rNqBQTQQJ7oMftec8bLWKVF6iujcH3Ck81f2a4zCu",
      underlyingTokenVault: "8vyTqVVPmJfqFexRcMBGDAHoSCyZ52RC5sRVhYzbfU4j",
      derivativeTokenVault: "DRLcUXwMcFf8itWJy7NdzKuWrZep1HceLaTgRRDs51SH",
      decimals: 9,
      expired: true,
      paused: false,
    },
    userAccount: "11111111111111111111111111111113",
    userBump: 255,
    user: {
      owner: SOL_FUNDED_WALLET_ADDRESS,
      depositRound: BigInt(63),
      depositAmount: BigInt(99),
      unredeemedShares: BigInt(0),
      withdrawRound: BigInt(0),
      withdrawShares: BigInt(0),
      bump: 255,
      ...userPatch,
    },
    pricePerSharePage: "11111111111111111111111111111114",
    userUnderlyingAta: ownerAta.toBase58(),
    userDerivativeAta: "11111111111111111111111111111115",
    userDerivative: BigInt(0),
    vaultBalance: BigInt(0),
    lamports: BigInt(1),
    nativeUnderlying: true,
    ...patch,
  };
}

function withdrawIx(built: { ok: true; instructions: { programId: PublicKey; keys: { pubkey: PublicKey; isSigner: boolean; isWritable: boolean }[]; data: Buffer }[] }) {
  const katana = built.instructions.filter((ix) => ix.programId.equals(new PublicKey(KATANA_STRUCTURED_PROGRAM)));
  assert.equal(katana.length, 1);
  const ix = katana[0];
  assert.ok(ix);
  return ix;
}

describe("authorized instantWithdraw constraints", () => {
  it("wires userAuthority as the connected owner signer and destination as that wallet's ATA", () => {
    const built = buildAuthorizedInstantWithdraw({
      connectedOwner: owner.toBase58(),
      snapshot: snapshot(),
      amount: "99",
    });
    assert.equal(built.ok, true);
    if (!built.ok) return;
    const ix = withdrawIx(built);
    assert.equal(ix.data.subarray(0, 8).toString("hex"), KATANA_DISCRIMINATORS.instant_withdraw);
    assert.equal(ix.data.readBigUInt64LE(8), BigInt(99));
    assert.equal(ix.keys[4]?.pubkey.toBase58(), ownerAta.toBase58());
    assert.equal(ix.keys[4]?.isSigner, false);
    assert.equal(ix.keys[4]?.isWritable, true);
    assert.equal(ix.keys[6]?.pubkey.toBase58(), owner.toBase58());
    assert.equal(ix.keys[6]?.isSigner, true);
    assert.deepEqual(assertAuthorizedWithdrawAccounts(ix, owner, ownerAta), { ok: true });
    assert.equal(built.instructions[0]?.keys[0]?.pubkey.equals(owner), true);
    assert.equal(built.instructions[0]?.keys[0]?.isSigner, true);
    assert.equal(built.instructions[0]?.keys[2]?.pubkey.equals(owner), true);
  });

  it("refuses a destination that is not the connected wallet's ATA", () => {
    const built = buildAuthorizedInstantWithdraw({
      connectedOwner: owner.toBase58(),
      snapshot: snapshot({ userUnderlyingAta: other.toBase58() }),
      amount: "99",
    });
    assert.equal(built.ok, false);
    if (built.ok) return;
    assert.match(built.message, /destination is not this wallet/);
  });

  it("refuses when the user account owner is not the connected wallet", () => {
    const built = buildAuthorizedInstantWithdraw({
      connectedOwner: owner.toBase58(),
      snapshot: snapshot({}, { owner: other.toBase58() }),
      amount: "99",
    });
    assert.equal(built.ok, false);
    if (built.ok) return;
    assert.match(built.message, /must sign as the depositor/);
  });

  it("refuses a stale-round pending deposit", () => {
    const built = buildAuthorizedInstantWithdraw({
      connectedOwner: owner.toBase58(),
      snapshot: snapshot({}, { depositRound: BigInt(62) }),
      amount: "99",
    });
    assert.equal(built.ok, false);
    if (built.ok) return;
    assert.match(built.message, /earlier vault round/);
  });

  it("refuses an amount above the pending deposit", () => {
    const built = buildAuthorizedInstantWithdraw({
      connectedOwner: owner.toBase58(),
      snapshot: snapshot(),
      amount: "100",
    });
    assert.equal(built.ok, false);
    if (built.ok) return;
    assert.match(built.message, /larger than the pending deposit/);
  });

  it("refuses a missing user account", () => {
    const built = buildAuthorizedInstantWithdraw({
      connectedOwner: owner.toBase58(),
      snapshot: snapshot({ user: null }),
      amount: "99",
    });
    assert.equal(built.ok, false);
    if (built.ok) return;
    assert.match(built.message, /same-round pending deposit/);
  });
});

describe("authorized pending status and lookup", () => {
  it("treats same-round positive pending as withdrawable", () => {
    assert.deepEqual(
      authorizedPendingStatus({
        connectedOwner: owner.toBase58(),
        user: { owner: owner.toBase58(), depositRound: BigInt(63), depositAmount: BigInt(5) },
        vaultRound: BigInt(63),
      }),
      { kind: "ready", amount: BigInt(5) },
    );
    assert.equal(authorizedPendingStatus({
      connectedOwner: owner.toBase58(),
      user: null,
      vaultRound: BigInt(63),
    }).kind, "no_account");
    assert.equal(authorizedPendingStatus({
      connectedOwner: owner.toBase58(),
      user: { owner: other.toBase58(), depositRound: BigInt(63), depositAmount: BigInt(5) },
      vaultRound: BigInt(63),
    }).kind, "other_owner");
    assert.equal(authorizedPendingStatus({
      connectedOwner: owner.toBase58(),
      user: { owner: owner.toBase58(), depositRound: BigInt(61), depositAmount: BigInt(5) },
      vaultRound: BigInt(63),
    }).kind, "stale_round");
  });

  it("formats base units and names the lookup fields", () => {
    assert.equal(formatTokenAmount(BigInt(1_500_000_000), 9), "1.5");
    assert.equal(formatTokenAmount(BigInt(2), 0), "2");
    const lookup = authorizedLookupFromSnapshot(snapshot(), owner.toBase58());
    assert.equal(lookup.withdrawable, true);
    assert.equal(lookup.destination_ata, ownerAta.toBase58());
    assert.equal(lookup.pending_kind, "ready");
    assert.match(lookup.note, /same round and is withdrawable/);
    const rebuilt = snapshotFromAuthorizedLookup(lookup);
    assert.equal(rebuilt.userUnderlyingAta, ownerAta.toBase58());
    assert.equal(rebuilt.user?.owner, owner.toBase58());
    const stale = authorizedLookupFromSnapshot(snapshot({}, { depositRound: BigInt(60) }), owner.toBase58());
    assert.equal(stale.withdrawable, false);
    assert.equal(stale.pending_kind, "stale_round");
    assert.match(stale.note, /not withdrawable here/);
  });

  it("reads lookup and blockhash replies", () => {
    const lookup = authorizedLookupFromSnapshot(snapshot(), owner.toBase58());
    assert.deepEqual(readAuthorizedLookup(lookup), lookup);
    assert.equal(readAuthorizedLookup(null), null);
    assert.equal(readAuthorizedLookup({ ok: false, message: "Connect a Solana wallet." })?.ok, false);
    assert.deepEqual(readAuthorizedBlockhash({ ok: true, blockhash: "abc", lastValidBlockHeight: 12 }), {
      ok: true,
      blockhash: "abc",
      lastValidBlockHeight: 12,
    });
    assert.equal(readAuthorizedBlockhash({ ok: true, blockhash: "", lastValidBlockHeight: 1 }), null);
  });

  it("surfaces wallet rejection without a desk-signer phrase", () => {
    const text = authorizedSendError(new Error("User rejected the request"));
    assert.match(text, /did not sign/);
    assert.equal(text.includes("desk"), false);
  });
});

describe("authorized lookup route inputs", () => {
  it("requires the connected owner and a listed vault without using the desk default", async () => {
    const missing = await loadKatanaAuthorizedLookup({ owner: "", state: DEFAULT_KATANA_VAULT });
    assert.equal(missing.ok, false);
    if (!missing.ok) assert.match(missing.message, /Connect a Solana wallet/);

    const unlisted = await loadKatanaAuthorizedLookup({
      owner: SOL_FUNDED_WALLET_ADDRESS,
      state: "11111111111111111111111111111111",
    });
    assert.equal(unlisted.ok, false);
    if (!unlisted.ok) assert.match(unlisted.message, /listed Katana vault/);
  });
});
