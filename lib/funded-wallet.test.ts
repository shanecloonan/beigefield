import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";
import { Address, Cell, loadMessage } from "@ton/core";
import { sendFundedScript } from "./funded-send";
import { openFundedWallet, textContainsFundedMnemonic } from "./funded-wallet";
import {
  FUNDED_WALLET_ADDRESS,
  FUNDED_WALLET_BOUNCEABLE,
  FUNDED_WALLET_MAX_MESSAGES,
} from "./funded-wallet-public";
import { utonMinter } from "./uton";

describe("funded wallet", () => {
  it("derives the published v5R1 address", async () => {
    const { keys, wallet } = await openFundedWallet();
    assert.equal(wallet.address.workChain, 0);
    assert.equal(
      wallet.address.toString({ urlSafe: true, bounceable: false, testOnly: false }),
      FUNDED_WALLET_ADDRESS,
    );
    assert.equal(
      wallet.address.toString({ urlSafe: true, bounceable: false, testOnly: false }),
      "UQDXQTZUmyd5KRoP3cvjXfXOtx6FIZYOAtwXHEu2TY7WTorY",
    );
    assert.equal(
      wallet.address.toString({ urlSafe: true, bounceable: true, testOnly: false }),
      FUNDED_WALLET_BOUNCEABLE,
    );
    assert.equal(
      keys.publicKey.toString("hex"),
      "05c59b79ccfccba83d76f550547442c24e2b3656dd2f425af7d78149dae660c6",
    );
  });

  it("keeps the phrase out of the client modules", () => {
    for (const path of [
      new URL("./funded-wallet-public.ts", import.meta.url),
      new URL("../components/ton/ton-composer.tsx", import.meta.url),
      new URL("../app/ton/page.tsx", import.meta.url),
      new URL("../components/tons/zig-composer.tsx", import.meta.url),
      new URL("../components/tons/wallet-desk.tsx", import.meta.url),
      new URL("../app/tons/page.tsx", import.meta.url),
      new URL("../components/burn/burn-desk.tsx", import.meta.url),
      new URL("../app/burn/page.tsx", import.meta.url),
    ]) {
      assert.equal(textContainsFundedMnemonic(readFileSync(path, "utf8")), false);
    }
  });
});

describe("funded send", () => {
  it("signs an external message with state init while the wallet is undeployed", async () => {
    const calls: Array<{ method: string; boc?: string }> = [];
    const result = await sendFundedScript(
      {
        network: "-239",
        from: Address.parse(FUNDED_WALLET_ADDRESS).toRawString(),
        messages: [{ address: utonMinter, amount: "1000000" }],
      },
      {
        nowSeconds: 1_700_000_000,
        fetchImpl: mockFetch(calls, { state: "uninitialized" }),
      },
    );

    assert.equal(result.ok, true);
    assert.deepEqual(
      calls.map((call) => call.method),
      ["getAddressInformation", "sendBoc"],
    );
    const boc = calls[1]?.boc;
    assert.ok(boc);
    const message = loadMessage(Cell.fromBase64(boc).beginParse());
    assert.equal(message.info.type, "external-in");
    if (message.info.type !== "external-in") return;
    assert.equal(
      message.info.dest?.toString({ urlSafe: true, bounceable: false, testOnly: false }),
      FUNDED_WALLET_ADDRESS,
    );
    assert.ok(message.init);
  });

  it("omits state init once the wallet is active and uses the sequence number", async () => {
    const calls: Array<{ method: string; boc?: string }> = [];
    const result = await sendFundedScript(
      { messages: [{ address: utonMinter, amount: "1" }] },
      { fetchImpl: mockFetch(calls, { state: "active", seqno: 7 }) },
    );
    assert.equal(result.ok, true);
    assert.deepEqual(
      calls.map((call) => call.method),
      ["getAddressInformation", "runGetMethod", "sendBoc"],
    );
    const boc = calls[2]?.boc;
    assert.ok(boc);
    const message = loadMessage(Cell.fromBase64(boc).beginParse());
    assert.equal(message.init, null);

    const again: Array<{ method: string; boc?: string }> = [];
    const other = await sendFundedScript(
      { messages: [{ address: utonMinter, amount: "1" }] },
      { fetchImpl: mockFetch(again, { state: "active", seqno: 8 }) },
    );
    assert.equal(other.ok, true);
    assert.notEqual(again[2]?.boc, boc);
  });

  it("does not broadcast an empty script, a testnet destination, or a failed sequence read", async () => {
    const calls: Array<{ method: string }> = [];
    const fetchImpl = mockFetch(calls, { state: "active", seqno: null });

    const empty = await sendFundedScript({ messages: [] }, { fetchImpl });
    assert.equal(empty.ok, false);
    if (!empty.ok) assert.equal(empty.kind, "rejected");

    const testnet = await sendFundedScript(
      {
        messages: [
          {
            address: Address.parse(utonMinter).toString({
              urlSafe: true,
              bounceable: true,
              testOnly: true,
            }),
            amount: "1",
          },
        ],
      },
      { fetchImpl },
    );
    assert.equal(testnet.ok, false);

    const tooMany = await sendFundedScript(
      {
        messages: Array.from({ length: FUNDED_WALLET_MAX_MESSAGES + 1 }, () => ({
          address: utonMinter,
          amount: "1",
        })),
      },
      { fetchImpl },
    );
    assert.equal(tooMany.ok, false);
    if (!tooMany.ok) assert.match(tooMany.message, /Nothing was sent/);

    const seqno = await sendFundedScript(
      { messages: [{ address: utonMinter, amount: "1" }] },
      { fetchImpl },
    );
    assert.equal(seqno.ok, false);
    if (!seqno.ok) assert.equal(seqno.kind, "rejected");
    assert.equal(
      calls.some((call) => call.method === "sendBoc"),
      false,
    );
  });

  it("treats a dropped broadcast as unsent when the account is still uninitialized", async () => {
    const dropped = await sendFundedScript(
      { messages: [{ address: utonMinter, amount: "1" }] },
      {
        fetchImpl: async (_url, init) => {
          const body = JSON.parse(String(init?.body)) as { method?: string };
          if (body.method === "getAddressInformation") {
            return Response.json({ ok: true, result: { state: "uninitialized" } });
          }
          throw new Error("socket hang up");
        },
      },
    );
    assert.equal(dropped.ok, false);
    if (!dropped.ok) {
      assert.equal(dropped.kind, "rejected");
      assert.match(dropped.message, /Nothing was sent\. Safe to try again/);
    }

    const refused = await sendFundedScript(
      { messages: [{ address: utonMinter, amount: "1" }] },
      {
        fetchImpl: async (_url, init) => {
          const body = JSON.parse(String(init?.body)) as { method: string };
          if (body.method === "getAddressInformation") {
            return Response.json({ ok: true, result: { state: "uninitialized" } });
          }
          return Response.json({ ok: false, error: "duplicate" });
        },
      },
    );
    assert.equal(refused.ok, false);
    if (!refused.ok) {
      assert.equal(refused.kind, "rejected");
      assert.match(refused.message, /Nothing was sent/);
    }
  });
});

function mockFetch(
  calls: Array<{ method: string; boc?: string }>,
  account: { state: "active" | "uninitialized"; seqno?: number | null },
): typeof fetch {
  return async (_url, init) => {
    const body = JSON.parse(String(init?.body)) as {
      method: string;
      params?: { boc?: string };
    };
    calls.push({ method: body.method, boc: body.params?.boc });
    if (body.method === "getAddressInformation") {
      return Response.json({ ok: true, result: { state: account.state } });
    }
    if (body.method === "runGetMethod") {
      if (account.seqno === null || account.seqno === undefined) {
        return Response.json({ ok: true, result: { exit_code: -13, stack: [] } });
      }
      return Response.json({
        ok: true,
        result: { exit_code: 0, stack: [["num", `0x${account.seqno.toString(16)}`]] },
      });
    }
    if (body.method === "sendBoc") {
      return Response.json({ ok: true, result: { "@type": "ok" } });
    }
    return Response.json({ ok: false, error: "unexpected" }, { status: 400 });
  };
}
