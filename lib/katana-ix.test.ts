import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { PublicKey } from "@solana/web3.js";
import { KATANA_DISCRIMINATORS, KATANA_STRUCTURED_PROGRAM, KATANA_VAULTS } from "./katana";
import { buildKatanaInstructions } from "./katana-ix";
import type { KatanaSnapshot } from "./katana-accounts";
import { SOL_FUNDED_WALLET_ADDRESS } from "./sol-funded-wallet-public";

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
      underlyingTokenMint: "So11111111111111111111111111111111111111112",
      quoteTokenMint: "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
      identifier: null,
      derivativeTokenMint: "J58rNqBQTQQJ7oMftec8bLWKVF6iujcH3Ck81f2a4zCu",
      underlyingTokenVault: "8vyTqVVPmJfqFexRcMBGDAHoSCyZ52RC5sRVhYzbfU4j",
      derivativeTokenVault: "DRLcUXwMcFf8itWJy7NdzKuWrZep1HceLaTgRRDs51SH",
      decimals: 12,
      expired: true,
      paused: false,
    },
    userAccount: "11111111111111111111111111111112",
    userBump: 255,
    user: {
      owner: SOL_FUNDED_WALLET_ADDRESS,
      depositRound: BigInt(0),
      depositAmount: BigInt(0),
      unredeemedShares: BigInt(0),
      withdrawRound: BigInt(0),
      withdrawShares: BigInt(0),
      bump: 255,
      ...userPatch,
    },
    pricePerSharePage: "11111111111111111111111111111113",
    userUnderlyingAta: "11111111111111111111111111111114",
    userDerivativeAta: "11111111111111111111111111111115",
    userDerivative: BigInt(0),
    vaultBalance: BigInt(0),
    lamports: BigInt(1),
    nativeUnderlying: true,
    ...patch,
  };
}

function lastProgramData(built: { ok: true; instructions: { programId: PublicKey; data: Buffer }[] }): string {
  const last = built.instructions.filter((ix) => ix.programId.equals(new PublicKey(KATANA_STRUCTURED_PROGRAM))).at(-1);
  assert.ok(last);
  return last.data.subarray(0, 8).toString("hex");
}

describe("buildKatanaInstructions", () => {
  const owner = new PublicKey(SOL_FUNDED_WALLET_ADDRESS);

  it("refuses withdraw_expired when the vault is not expired", () => {
    const built = buildKatanaInstructions({
      action: "withdraw_expired",
      snapshot: snapshot({ decoded: { ...snapshot().decoded, expired: false }, userDerivative: BigInt(1) }),
      owner,
    });
    assert.equal(built.ok, false);
    if (!built.ok) assert.match(built.message, /not expired/);
  });

  it("builds claim_shares then withdraw_expired for exit", () => {
    const built = buildKatanaInstructions({
      action: "exit",
      snapshot: snapshot({}, { unredeemedShares: BigInt(4) }),
      owner,
    });
    assert.equal(built.ok, true);
    if (!built.ok) return;
    const katana = built.instructions.filter((ix) => ix.programId.equals(new PublicKey(KATANA_STRUCTURED_PROGRAM)));
    assert.equal(katana.length, 2);
    assert.equal(katana[0]?.data.subarray(0, 8).toString("hex"), KATANA_DISCRIMINATORS.claim_shares);
    assert.equal(katana[1]?.data.subarray(0, 8).toString("hex"), KATANA_DISCRIMINATORS.withdraw_expired);
  });

  it("encodes amount_underlying for instant_withdraw", () => {
    const built = buildKatanaInstructions({
      action: "instant_withdraw",
      snapshot: snapshot({}, { depositAmount: BigInt(99) }),
      owner,
      amount: BigInt(99),
    });
    assert.equal(built.ok, true);
    if (!built.ok) return;
    assert.equal(lastProgramData(built), KATANA_DISCRIMINATORS.instant_withdraw);
    const katana = built.instructions.find((ix) => ix.programId.equals(new PublicKey(KATANA_STRUCTURED_PROGRAM)));
    assert.equal(katana?.data.readBigUInt64LE(8), BigInt(99));
  });
});
