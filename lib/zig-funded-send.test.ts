import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";
import { BroadcastTxError, TimeoutError } from "@cosmjs/stargate";
import { DirectSecp256k1HdWallet } from "@cosmjs/proto-signing";
import { VALDORA_STAKER } from "./valdora";
import { compilePathRun } from "./valdora-path-run";
import { classifyBroadcastError, sendZigScript } from "./zig-funded-send";
import { ZIG_FUNDED_WALLET_ADDRESS } from "./zig-funded-wallet-public";
import {
  ZigFundedKeyError,
  deskPublicAddress,
  openZigFundedWallet,
  textContainsZigMnemonic,
} from "./zig-funded-wallet";

const desk = "zig1gy5zketezrfdea9g80we02663r2gjz3z0002kx";
const other = "zig1wtwzsnt3u3zwytcgpgq8pj8yr5njjhcxj0nhwx";
const hash = "ab".repeat(32);

function request(sender: string, patch?: (message: Record<string, unknown>) => void) {
  const compiled = compilePathRun({ id: 12, sender });
  assert.equal(compiled.ok, true);
  if (!compiled.ok) throw new Error("compile");
  const body: { messages: Record<string, unknown>[] } = {
    messages: compiled.messages.map((message) => ({
      typeUrl: message.typeUrl,
      value: { ...message.value, msg: { ...message.value.msg } },
    })),
  };
  patch?.(body.messages[0] ?? {});
  return body;
}

describe("zig funded send", () => {
  it("rejects a sender that is not the desk wallet", async () => {
    let executed = 0;
    const result = await sendZigScript(request(other), {
      deskAddress: async () => desk,
      execute: async () => {
        executed += 1;
        return { transactionHash: hash, height: 1 };
      },
    });
    assert.equal(executed, 0);
    assert.deepEqual(result, {
      ok: false,
      kind: "rejected",
      message: "This desk sends only from its own wallet. Nothing was sent.",
    });
  });

  it("broadcasts one execute and returns the hash", async () => {
    const seen: Array<{ contract: string; msg: unknown; funds: readonly unknown[] }> = [];
    const result = await sendZigScript(request(desk), {
      deskAddress: async () => desk,
      execute: async (args) => {
        seen.push({ contract: args.contract, msg: args.msg, funds: args.funds });
        return { transactionHash: hash, height: 13238246 };
      },
    });
    assert.deepEqual(result, { ok: true, txHash: hash, height: 13238246 });
    assert.deepEqual(seen, [
      {
        contract: VALDORA_STAKER,
        msg: { withdraw_unbonded_by_id: { id: 12 } },
        funds: [],
      },
    ]);
  });

  it("rejects a different contract, funds, or msg before it signs", async () => {
    const cases = [
      request(desk, (message) => {
        const value = message.value as { contract: string };
        value.contract = other;
      }),
      request(desk, (message) => {
        const value = message.value as { funds: unknown[] };
        value.funds = [{ denom: "azig", amount: "1" }];
      }),
      request(desk, (message) => {
        const value = message.value as { msg: unknown };
        value.msg = { redeem: { amount: "1" } };
      }),
      { messages: [] },
    ];
    for (const body of cases) {
      const result = await sendZigScript(body, {
        deskAddress: async () => desk,
        execute: async () => {
          throw new Error("should not sign");
        },
      });
      assert.equal(result.ok, false);
      if (!result.ok) assert.equal(result.kind, "rejected");
    }
  });

  it("marks a lost broadcast as ambiguous and an included failure as rejected", () => {
    const timeout = classifyBroadcastError(new TimeoutError("was not yet found on the chain", hash));
    assert.equal(timeout.ok, false);
    if (!timeout.ok) assert.equal(timeout.kind, "ambiguous");

    const included = classifyBroadcastError(
      new Error(`Error when broadcasting tx ${hash} at height 9. Code: 5; Raw log: paused`),
    );
    assert.equal(included.ok, false);
    if (!included.ok) {
      assert.equal(included.kind, "rejected");
      assert.match(included.message, /included and failed/);
    }

    const check = classifyBroadcastError(new BroadcastTxError(11, "sdk", "insufficient funds"));
    assert.equal(check.ok, false);
    if (!check.ok) assert.equal(check.kind, "rejected");
  });
});

describe("zig funded wallet", () => {
  it("derives the published desk address from the built-in phrase", async () => {
    const previous = process.env.ZIG_FUNDED_MNEMONIC;
    delete process.env.ZIG_FUNDED_MNEMONIC;
    try {
      const opened = await openZigFundedWallet();
      assert.equal(opened.address, ZIG_FUNDED_WALLET_ADDRESS);
      assert.equal(opened.address, "zig1wtkwhteg7cyr0hafjr5q20f5uesrj0e8yfx2gm");
      assert.equal(await deskPublicAddress(), ZIG_FUNDED_WALLET_ADDRESS);
    } finally {
      if (previous === undefined) delete process.env.ZIG_FUNDED_MNEMONIC;
      else process.env.ZIG_FUNDED_MNEMONIC = previous;
    }
  });

  it("lets ZIG_FUNDED_MNEMONIC override the built-in phrase and rejects a bad override", async () => {
    const previous = process.env.ZIG_FUNDED_MNEMONIC;
    const generated = await DirectSecp256k1HdWallet.generate(12, { prefix: "zig" });
    process.env.ZIG_FUNDED_MNEMONIC = generated.mnemonic;
    try {
      const first = await openZigFundedWallet();
      const second = await openZigFundedWallet();
      const [account] = await generated.getAccounts();
      assert.equal(first.address, account?.address);
      assert.equal(first.address, second.address);
      assert.notEqual(first.address, ZIG_FUNDED_WALLET_ADDRESS);
      process.env.ZIG_FUNDED_MNEMONIC = "not a desk phrase";
      await assert.rejects(openZigFundedWallet(), ZigFundedKeyError);
      assert.equal(await deskPublicAddress(), ZIG_FUNDED_WALLET_ADDRESS);
    } finally {
      if (previous === undefined) delete process.env.ZIG_FUNDED_MNEMONIC;
      else process.env.ZIG_FUNDED_MNEMONIC = previous;
    }
  });

  it("keeps the phrase out of the client modules", () => {
    for (const path of [
      new URL("./zig-funded-wallet-public.ts", import.meta.url),
      new URL("./valdora.ts", import.meta.url),
      new URL("./valdora-path.ts", import.meta.url),
      new URL("./valdora-path-run.ts", import.meta.url),
      new URL("../components/tons/zig-composer.tsx", import.meta.url),
      new URL("../components/tons/wallet-desk.tsx", import.meta.url),
      new URL("../components/tons/path-run-bar.tsx", import.meta.url),
      new URL("../app/tons/page.tsx", import.meta.url),
      new URL("../app/api/zig/path-defaults/route.ts", import.meta.url),
      new URL("../app/api/zig/send/route.ts", import.meta.url),
    ]) {
      const source = readFileSync(path, "utf8");
      assert.equal(textContainsZigMnemonic(source), false);
      assert.equal(source.includes("ZIG_FUNDED_MNEMONIC"), false);
      assert.equal(source.includes('from "@/lib/zig-funded-wallet"'), false);
      assert.equal(source.includes('from "./zig-funded-wallet"'), false);
    }
  });
});
