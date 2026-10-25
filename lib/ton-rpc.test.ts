import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { Address } from "@ton/core";
import { sendFundedScript } from "./funded-send";
import { FUNDED_WALLET_ADDRESS } from "./funded-wallet-public";
import { addressFromGetMethod, parseSeqno, readJettonWallet, readSeqno } from "./ton-rpc";
import { utonMinter } from "./uton";

const jettonBoc =
  "te6cckEBAQEAJAAAQ4AaP/UmuOHMUml0xxYBU0n8R8TAgJkw9s9jHEXUpK7i/XA/mSlx";

describe("ton rpc parsing", () => {
  it("reads a jetton wallet cell and a sequence number", () => {
    const wallet = addressFromGetMethod({
      exit_code: 0,
      stack: [["cell", { bytes: jettonBoc }]],
    });
    assert.ok(wallet);
    assert.equal(
      wallet.toString({ urlSafe: true, bounceable: true, testOnly: false }),
      "EQDR_6k1xw5ik0umOLAKmk_iPiYEBMmHtnsY4i6lJXcX6z-v",
    );
    assert.equal(parseSeqno({ exit_code: 0, stack: [["num", "0x1"]] }), 1);
    assert.equal(parseSeqno({ exit_code: -13, stack: [["num", "0x14c97"]] }), null);
  });
});

describe("ton rpc failover", () => {
  it("retries a rate limit and then reads the sequence number", async () => {
    let attempts = 0;
    const seqno = await readSeqno(FUNDED_WALLET_ADDRESS, {
      sleep: async () => undefined,
      fetchImpl: async (url) => {
        if (String(url).includes("tonapi.io")) throw new Error("tonapi");
        attempts += 1;
        if (attempts === 1) return Response.json({ ok: false, code: 429 }, { status: 429 });
        return Response.json({
          ok: true,
          result: { exit_code: 0, stack: [["num", "0x7"]] },
        });
      },
    });
    assert.equal(seqno, 7);
    assert.equal(attempts, 2);
  });

  it("asks TonAPI when Toncenter keeps refusing the sequence number and the jetton wallet", async () => {
    const calls: string[] = [];
    const fetchImpl: typeof fetch = async (url) => {
      const href = String(url);
      calls.push(href);
      if (href.includes("/methods/seqno")) {
        return Response.json({ success: true, exit_code: 0, decoded: { state: 4 }, stack: [] });
      }
      if (href.includes("/jettons/")) {
        return Response.json({
          wallet_address: {
            address: "0:d1ffa935c70e62934ba638b00a9a4fe23e260404c987b67b18e22ea5257717eb",
          },
        });
      }
      return Response.json({ ok: false, error: "Ratelimit exceed", code: 429 }, { status: 429 });
    };
    const sleep = async () => undefined;
    const seqno = await readSeqno(FUNDED_WALLET_ADDRESS, { fetchImpl, sleep });
    assert.equal(seqno, 4);

    const wallet = await readJettonWallet(Address.parse(FUNDED_WALLET_ADDRESS), Address.parse(utonMinter), {
      fetchImpl,
      sleep,
    });
    assert.ok(wallet);
    assert.equal(
      wallet.toString({ urlSafe: true, bounceable: true, testOnly: false }),
      "EQDR_6k1xw5ik0umOLAKmk_iPiYEBMmHtnsY4i6lJXcX6z-v",
    );
    assert.equal(calls.filter((href) => href.includes("tonapi.io")).length, 2);
  });

  it("signs one broadcast after TonAPI supplies the sequence number", async () => {
    const methods: string[] = [];
    const result = await sendFundedScript(
      { messages: [{ address: utonMinter, amount: "1" }] },
      {
        sleep: async () => undefined,
        fetchImpl: async (url, init) => {
          const href = String(url);
          if (href.includes("/methods/seqno")) {
            methods.push("tonapi-seqno");
            return Response.json({ success: true, exit_code: 0, decoded: { state: 3 }, stack: [] });
          }
          const body = JSON.parse(String(init?.body)) as { method: string };
          methods.push(body.method);
          if (body.method === "getAddressInformation") {
            return Response.json({ ok: true, result: { state: "active" } });
          }
          if (body.method === "runGetMethod") {
            return Response.json({ ok: false, code: 429 }, { status: 429 });
          }
          if (body.method === "sendBoc") return Response.json({ ok: true, result: {} });
          return Response.json({ ok: false }, { status: 400 });
        },
      },
    );
    assert.equal(result.ok, true);
    assert.deepEqual(methods, ["getAddressInformation", "runGetMethod", "runGetMethod", "tonapi-seqno", "sendBoc"]);
  });
});
