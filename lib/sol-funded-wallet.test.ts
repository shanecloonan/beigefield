import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";
import { Keypair } from "@solana/web3.js";
import bs58 from "bs58";
import { DEFAULT_KATANA_VAULT, KATANA_STRUCTURED_PROGRAM, KATANA_VAULTS } from "./katana";
import { compilePathRun } from "./katana-path-run";
import { classifyBroadcastError, sendKatanaScript } from "./sol-funded-send";
import { SOL_FUNDED_WALLET_ADDRESS } from "./sol-funded-wallet-public";
import {
  SolFundedKeyError,
  deskPublicAddress,
  openSolFundedWallet,
  textContainsSolSecret,
} from "./sol-funded-wallet";

const OTHER = "11111111111111111111111111111111";
const SIGNATURE = "5".repeat(88);

function request(sender: string, patch: Record<string, unknown> = {}) {
  const compiled = compilePathRun({
    sender,
    state: DEFAULT_KATANA_VAULT,
    action: "close_user_account",
  });
  assert.equal(compiled.ok, true);
  if (!compiled.ok) throw new Error("compile");
  return { sender: compiled.sender, state: compiled.state, action: compiled.action, ...patch };
}

describe("sol funded wallet", () => {
  it("derives the published desk address from the built-in secret", () => {
    const previous = process.env.SOL_FUNDED_SECRET_KEY;
    delete process.env.SOL_FUNDED_SECRET_KEY;
    try {
      const opened = openSolFundedWallet();
      assert.equal(opened.address, SOL_FUNDED_WALLET_ADDRESS);
      assert.equal(opened.address, "DnhKRJxRm3WGVqounThdefXypHKFCJfsodQKiwJxFPLb");
      assert.equal(deskPublicAddress(), SOL_FUNDED_WALLET_ADDRESS);
    } finally {
      if (previous === undefined) delete process.env.SOL_FUNDED_SECRET_KEY;
      else process.env.SOL_FUNDED_SECRET_KEY = previous;
    }
  });

  it("lets SOL_FUNDED_SECRET_KEY override the built-in key and rejects a bad override", () => {
    const previous = process.env.SOL_FUNDED_SECRET_KEY;
    const generated = Keypair.generate();
    process.env.SOL_FUNDED_SECRET_KEY = bs58.encode(generated.secretKey);
    try {
      const first = openSolFundedWallet();
      const second = openSolFundedWallet();
      assert.equal(first.address, generated.publicKey.toBase58());
      assert.equal(first.address, second.address);
      assert.notEqual(first.address, SOL_FUNDED_WALLET_ADDRESS);
      process.env.SOL_FUNDED_SECRET_KEY = "not-a-secret";
      assert.throws(() => openSolFundedWallet(), SolFundedKeyError);
      assert.equal(deskPublicAddress(), SOL_FUNDED_WALLET_ADDRESS);
    } finally {
      if (previous === undefined) delete process.env.SOL_FUNDED_SECRET_KEY;
      else process.env.SOL_FUNDED_SECRET_KEY = previous;
    }
  });

  it("keeps the secret out of the client modules", () => {
    for (const path of [
      new URL("./sol-funded-wallet-public.ts", import.meta.url),
      new URL("./katana.ts", import.meta.url),
      new URL("./katana-path.ts", import.meta.url),
      new URL("./katana-path-run.ts", import.meta.url),
      new URL("../components/sol/sol-composer.tsx", import.meta.url),
      new URL("../components/sol/wallet-desk.tsx", import.meta.url),
      new URL("../components/sol/path-run-bar.tsx", import.meta.url),
      new URL("../components/sol/katana-notes.tsx", import.meta.url),
      new URL("../app/sol/page.tsx", import.meta.url),
      new URL("../app/api/sol/path-defaults/route.ts", import.meta.url),
      new URL("../app/api/sol/send/route.ts", import.meta.url),
    ]) {
      const source = readFileSync(path, "utf8");
      assert.equal(textContainsSolSecret(source), false);
      assert.equal(source.includes("SOL_FUNDED_SECRET_KEY"), false);
      assert.equal(source.includes('from "@/lib/sol-funded-wallet"'), false);
      assert.equal(source.includes('from "./sol-funded-wallet"'), false);
    }
  });

  it("keeps Katana desk sources free of other protocol desks", () => {
    const banned =
      /UTONIC|uTON|Valdora|ZIGChain|zig1|withdraw_unbonded|jetton|Toncenter|stzig|@\/lib\/(uton|valdora|funded-wallet|zig-funded|ton-)|@\/components\/tons?\//;
    for (const path of [
      new URL("./katana.ts", import.meta.url),
      new URL("./katana-path.ts", import.meta.url),
      new URL("./katana-path-run.ts", import.meta.url),
      new URL("./katana-accounts.ts", import.meta.url),
      new URL("./katana-query.ts", import.meta.url),
      new URL("./katana-ix.ts", import.meta.url),
      new URL("./sol-funded-send.ts", import.meta.url),
      new URL("./sol-funded-wallet.ts", import.meta.url),
      new URL("./sol-funded-wallet-public.ts", import.meta.url),
      new URL("../components/sol/sol-composer.tsx", import.meta.url),
      new URL("../components/sol/wallet-desk.tsx", import.meta.url),
      new URL("../components/sol/path-run-bar.tsx", import.meta.url),
      new URL("../components/sol/katana-notes.tsx", import.meta.url),
      new URL("../app/sol/page.tsx", import.meta.url),
    ]) {
      const source = readFileSync(path, "utf8");
      assert.equal(banned.test(source), false, path.pathname);
    }
  });
});

describe("sol funded send", () => {
  it("rejects a sender that is not the desk wallet", async () => {
    let executed = 0;
    const result = await sendKatanaScript(request(OTHER), {
      deskAddress: async () => SOL_FUNDED_WALLET_ADDRESS,
      execute: async () => {
        executed += 1;
        return { signature: SIGNATURE };
      },
    });
    assert.equal(executed, 0);
    assert.deepEqual(result, {
      ok: false,
      kind: "rejected",
      message: "This desk sends only from its own wallet. Nothing was sent.",
    });
  });

  it("rejects deposit, migrate, and an unknown vault before it signs", async () => {
    const cases = [
      { sender: SOL_FUNDED_WALLET_ADDRESS, state: DEFAULT_KATANA_VAULT, action: "deposit" },
      { sender: SOL_FUNDED_WALLET_ADDRESS, state: DEFAULT_KATANA_VAULT, action: "migrate" },
      { sender: SOL_FUNDED_WALLET_ADDRESS, state: OTHER, action: "exit" },
      { messages: [] },
    ];
    for (const body of cases) {
      const result = await sendKatanaScript(body, {
        deskAddress: async () => SOL_FUNDED_WALLET_ADDRESS,
        execute: async () => {
          throw new Error("should not sign");
        },
      });
      assert.equal(result.ok, false);
      if (!result.ok) assert.equal(result.kind, "rejected");
    }
  });

  it("broadcasts close_user_account when the snapshot has an empty user account", async () => {
    const seen: string[] = [];
    const result = await sendKatanaScript(request(SOL_FUNDED_WALLET_ADDRESS), {
      deskAddress: async () => SOL_FUNDED_WALLET_ADDRESS,
      load: async () => ({
        ok: true,
        snapshot: emptyUserSnapshot(SOL_FUNDED_WALLET_ADDRESS),
      }),
      execute: async (args) => {
        seen.push(args.feePayer);
        assert.equal(args.instructions.length, 1);
        return { signature: SIGNATURE };
      },
    });
    assert.deepEqual(result, { ok: true, signature: SIGNATURE });
    assert.deepEqual(seen, [SOL_FUNDED_WALLET_ADDRESS]);
  });

  it("marks a lost broadcast as ambiguous and a simulation failure as rejected", () => {
    const timeout = classifyBroadcastError(new Error("Transaction was not confirmed in 30.00 seconds"));
    assert.equal(timeout.ok, false);
    if (!timeout.ok) assert.equal(timeout.kind, "ambiguous");

    const simulation = classifyBroadcastError(new Error("Transaction simulation failed: Error processing Instruction 0: custom program error: 0x1784"));
    assert.equal(simulation.ok, false);
    if (!simulation.ok) {
      assert.equal(simulation.kind, "rejected");
      assert.match(simulation.message, /Nothing was sent/);
    }
  });

  it("lists every State account both Katana programs own", () => {
    assert.equal(KATANA_VAULTS.length, 23);
    assert.equal(KATANA_VAULTS[0]?.state, DEFAULT_KATANA_VAULT);
    assert.equal(KATANA_STRUCTURED_PROGRAM, "1349iiGjWC7ZTbu6otFmJwztms122jEEnShKgpVnNewy");
  });
});

function emptyUserSnapshot(owner: string) {
  const vault = KATANA_VAULTS[0];
  if (!vault) throw new Error("vault");
  return {
    vault,
    programId: KATANA_STRUCTURED_PROGRAM,
    state: vault.state,
    decoded: {
      kind: vault.program,
      admin: owner,
      vaultAuthority: "7wM6TyhDZMJSYojLbZWPcmkMu11xErKu6oeGJoHqtUgV",
      cap: BigInt(0),
      lockedAmount: BigInt(0),
      totalPendingDeposits: BigInt(0),
      queuedWithdrawShares: BigInt(0),
      totalShares: BigInt(0),
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
      owner,
      depositRound: BigInt(0),
      depositAmount: BigInt(0),
      unredeemedShares: BigInt(0),
      withdrawRound: BigInt(0),
      withdrawShares: BigInt(0),
      bump: 255,
    },
    pricePerSharePage: "11111111111111111111111111111113",
    userUnderlyingAta: "11111111111111111111111111111114",
    userDerivativeAta: "11111111111111111111111111111115",
    userDerivative: BigInt(0),
    vaultBalance: BigInt(0),
    lamports: BigInt(0),
    nativeUnderlying: true,
  };
}
