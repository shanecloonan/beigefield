import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { Address } from "@ton/core";
import { POST as postFundedSend } from "../app/api/ton/send/route";
import { sendFundedScript } from "./funded-send";
import { FUNDED_WALLET_ADDRESS } from "./funded-wallet-public";
import { addressFromGetMethod, parseSeqno, readJettonWallet, readObservedSeqno, readSeqno } from "./ton-rpc";
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

  it("treats a lost broadcast as success when the sequence number advanced", async () => {
    const calls: string[] = [];
    const result = await sendFundedScript(
      { messages: [{ address: utonMinter, amount: "1" }] },
      { fetchImpl: scriptFetch(calls, { afterSeqno: 2, send: "timeout" }) },
    );
    assert.equal(result.ok, true);
    assert.equal(calls.filter((call) => call === "sendBoc").length, 1);
    assert.equal(calls.filter((call) => call === "tonapi-send").length, 0);
  });

  it("says nothing was sent when the sequence number stays put", async () => {
    const calls: string[] = [];
    const result = await sendFundedScript(
      { messages: [{ address: utonMinter, amount: "1" }] },
      { fetchImpl: scriptFetch(calls, { afterSeqno: 1, send: "timeout", tonapiSend: "down" }) },
    );
    assert.equal(result.ok, false);
    if (!result.ok) {
      assert.equal(result.kind, "rejected");
      assert.equal(result.message, "Nothing was sent. Safe to try again.");
    }
    assert.equal(calls.filter((call) => call === "sendBoc").length, 1);
    assert.equal(calls.filter((call) => call === "tonapi-send").length, 1);
  });

  it("sends the same message through TonAPI only after the sequence number stays put", async () => {
    const calls: string[] = [];
    const result = await sendFundedScript(
      { messages: [{ address: utonMinter, amount: "1" }] },
      { fetchImpl: scriptFetch(calls, { afterSeqno: 1, send: "429", tonapiSend: "ok" }) },
    );
    assert.equal(result.ok, true);
    assert.deepEqual(
      calls.filter((call) => call === "sendBoc" || call === "tonapi-send"),
      ["sendBoc", "tonapi-send"],
    );
  });

  it("returns the safe retry text from the send route when the sequence number stays put", async () => {
    const previous = globalThis.fetch;
    globalThis.fetch = scriptFetch([], { afterSeqno: 1, send: "timeout", tonapiSend: "down" });
    try {
      const response = await postFundedSend(
        new Request("https://beigefield.vercel.app/api/ton/send", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ messages: [{ address: utonMinter, amount: "1" }] }),
        }),
      );
      assert.equal(response.status, 400);
      const body = (await response.json()) as { ok: boolean; kind: string; message: string };
      assert.equal(body.ok, false);
      assert.equal(body.kind, "rejected");
      assert.equal(body.message, "Nothing was sent. Safe to try again.");
    } finally {
      globalThis.fetch = previous;
    }
  });

  it("keeps the double-send warning when the sequence number cannot be read again", async () => {
    const calls: string[] = [];
    const result = await sendFundedScript(
      { messages: [{ address: utonMinter, amount: "1" }] },
      { fetchImpl: scriptFetch(calls, { afterSeqno: null, send: "timeout" }) },
    );
    assert.equal(result.ok, false);
    if (!result.ok) {
      assert.equal(result.kind, "ambiguous");
      assert.match(result.message, /not sent twice/);
    }
    assert.equal(calls.includes("tonapi-send"), false);
  });

  it("trusts the higher sequence number when Toncenter is stale", async () => {
    const seqno = await readObservedSeqno(FUNDED_WALLET_ADDRESS, {
      fetchImpl: async (url, init) => {
        const href = String(url);
        if (href.includes("/methods/seqno")) {
          return Response.json({ success: true, exit_code: 0, decoded: { state: 5 }, stack: [] });
        }
        const body = JSON.parse(String(init?.body)) as { method: string };
        assert.equal(body.method, "runGetMethod");
        return Response.json({ ok: true, result: { exit_code: 0, stack: [["num", "0x1"]] } });
      },
    });
    assert.equal(seqno, 5);
  });
});

function scriptFetch(
  calls: string[],
  script: {
    afterSeqno: number | null;
    send: "timeout" | "429";
    tonapiSend?: "ok" | "down";
  },
): typeof fetch {
  return async (url, init) => {
    const href = String(url);
    if (href.includes("/v2/blockchain/message")) {
      calls.push("tonapi-send");
      if (script.tonapiSend === "ok") return Response.json({ ok: true });
      return Response.json({ error: "down" }, { status: 502 });
    }
    if (href.includes("/methods/seqno")) {
      calls.push("tonapi-seqno");
      const sent = calls.includes("sendBoc");
      if (sent && script.afterSeqno === null) return Response.json({ success: false }, { status: 502 });
      const seqno = sent ? (script.afterSeqno ?? 1) : 1;
      return Response.json({
        success: true,
        exit_code: 0,
        decoded: { state: seqno },
        stack: [],
      });
    }
    const body = JSON.parse(String(init?.body)) as { method: string };
    calls.push(body.method);
    const sent = calls.filter((call) => call === "sendBoc").length > 0;
    if (body.method === "getAddressInformation") {
      return Response.json({ ok: true, result: { state: "active" } });
    }
    if (body.method === "runGetMethod") {
      if (sent && script.afterSeqno === null) {
        return Response.json({ ok: true, result: { exit_code: -13, stack: [] } });
      }
      const seqno = sent ? (script.afterSeqno ?? 1) : 1;
      return Response.json({
        ok: true,
        result: { exit_code: 0, stack: [["num", `0x${seqno.toString(16)}`]] },
      });
    }
    if (body.method === "sendBoc") {
      if (script.send === "timeout") throw new Error("timeout");
      return Response.json({ ok: false, code: 429 }, { status: 429 });
    }
    return Response.json({ ok: false }, { status: 400 });
  };
}
