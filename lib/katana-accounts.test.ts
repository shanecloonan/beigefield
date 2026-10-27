import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { PublicKey } from "@solana/web3.js";
import {
  decodeState,
  decodeUserAccount,
  discriminator,
  findPricePerShareAddress,
  findUserAccountAddress,
  readTokenAmount,
} from "./katana-accounts";
import { KATANA_DISCRIMINATORS, KATANA_STRUCTURED_PROGRAM } from "./katana";

describe("katana accounts", () => {
  it("derives the live mSOL user account and price-per-share page", () => {
    const program = new PublicKey(KATANA_STRUCTURED_PROGRAM);
    const state = new PublicKey("DkguYGWhRE8qJ9voWNYZ8dJkGYr8ACUR8KXqDAyHpGx2");
    const owner = new PublicKey("CyAH9f9awBcfuZqHzwwEs4uJBLEG33S743jxnQX1KcZ6");
    const [user] = findUserAccountAddress(owner, state, program);
    assert.equal(user.toBase58(), "63z97bkLQfJajaoHCGk1NkRu5F7t8Jy1jwL73b1txMFj");

    const msol = new PublicKey("mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So");
    const usdc = new PublicKey("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v");
    const [page] = findPricePerShareAddress(
      { kind: "structured", underlyingMint: msol, quoteMint: usdc, identifier: null, pageIndex: 0 },
      program,
    );
    assert.equal(page.toBase58(), "GADk1RwoVeUawx72QxMfEbnjng3ZKjLMh4P3X3i7Yxvq");
  });

  it("decodes State and UserVaultAccount layouts", () => {
    const data = Buffer.alloc(741);
    discriminator(KATANA_DISCRIMINATORS.State).copy(data, 0);
    const admin = PublicKey.unique();
    const authority = PublicKey.unique();
    const underlying = new PublicKey("So11111111111111111111111111111111111111112");
    const quote = new PublicKey("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v");
    const derivative = PublicKey.unique();
    const undVault = PublicKey.unique();
    const derVault = PublicKey.unique();
    admin.toBuffer().copy(data, 8);
    authority.toBuffer().copy(data, 72);
    data.writeBigUInt64LE(BigInt(63), 200);
    underlying.toBuffer().copy(data, 216);
    quote.toBuffer().copy(data, 248);
    data[471] = 1;
    derivative.toBuffer().copy(data, 472);
    undVault.toBuffer().copy(data, 536);
    derVault.toBuffer().copy(data, 664);
    data[728] = 9;
    data[739] = 0;
    const state = decodeState(data, "structured");
    assert.ok(state);
    assert.equal(state?.admin, admin.toBase58());
    assert.equal(state?.vaultAuthority, authority.toBase58());
    assert.equal(state?.round, BigInt(63));
    assert.equal(state?.underlyingTokenMint, underlying.toBase58());
    assert.equal(state?.expired, true);
    assert.equal(state?.paused, false);
    assert.equal(state?.decimals, 9);
    assert.equal(state?.derivativeTokenMint, derivative.toBase58());

    const user = Buffer.alloc(121);
    discriminator(KATANA_DISCRIMINATORS.UserVaultAccount).copy(user, 0);
    const owner = PublicKey.unique();
    owner.toBuffer().copy(user, 8);
    user.writeBigUInt64LE(BigInt(12), 56);
    user.writeBigUInt64LE(BigInt(4), 72);
    user.writeBigUInt64LE(BigInt(7), 104);
    user[120] = 254;
    const decoded = decodeUserAccount(user);
    assert.ok(decoded);
    assert.equal(decoded?.owner, owner.toBase58());
    assert.equal(decoded?.depositAmount, BigInt(12));
    assert.equal(decoded?.unredeemedShares, BigInt(4));
    assert.equal(decoded?.withdrawShares, BigInt(7));
    assert.equal(decoded?.bump, 254);
  });

  it("reads an SPL token amount at offset 64", () => {
    const data = Buffer.alloc(165);
    data.writeBigUInt64LE(BigInt(42), 64);
    assert.equal(readTokenAmount(data), BigInt(42));
    assert.equal(readTokenAmount(null), BigInt(0));
  });
});
