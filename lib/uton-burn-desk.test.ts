import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";
import { createElement as h } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { Address, Cell, Dictionary } from "@ton/core";
import { BurnDesk } from "../components/burn/burn-desk";
import { FUNDED_WALLET_ADDRESS } from "./funded-wallet-public";
import { textContainsFundedMnemonic } from "./funded-wallet";
import { TON_MAINNET_CHAIN } from "./ton-message";
import { utonMinter } from "./uton";
import { UTON_OP } from "./uton-templates";
import {
  DESK_BURN_BATCH_GAP_MS,
  compileDeskBurn,
  deskLookupNote,
  parseUtonAmount,
  readPathDefaultsPayload,
  runDeskBurn,
} from "./uton-burn-desk";

const jetton = new Address(0, Buffer.alloc(32, 8));
const jettonFriendly = jetton.toString({ urlSafe: true, bounceable: true, testOnly: false });

function burnProxy(payload: string | undefined): { amount: bigint; proxy: number } {
  const slice = Cell.fromBase64(payload ?? "").beginParse();
  assert.equal(slice.loadUint(32), 0x595f07bc);
  slice.loadUint(64);
  const amount = slice.loadCoins();
  slice.loadAddress();
  const dict = slice.loadDict(Dictionary.Keys.Uint(32), Dictionary.Values.Cell());
  const inner = dict.get(0)?.beginParse();
  assert.ok(inner);
  return { amount, proxy: inner.loadUint(32) };
}

describe("uTON amount", () => {
  it("converts a decimal uTON amount into nanotons", () => {
    assert.deepEqual(parseUtonAmount("1"), { ok: true, nanotons: "1000000000" });
    assert.deepEqual(parseUtonAmount(" 0.5 "), { ok: true, nanotons: "500000000" });
    assert.deepEqual(parseUtonAmount("1.000000001"), { ok: true, nanotons: "1000000001" });
  });

  it("rejects an empty, zero, or over-precise amount", () => {
    assert.equal(parseUtonAmount("").ok, false);
    assert.equal(parseUtonAmount("0").ok, false);
    assert.equal(parseUtonAmount("0.0").ok, false);
    assert.equal(parseUtonAmount("1.1234567891").ok, false);
    assert.equal(parseUtonAmount("1e9").ok, false);
    const blank = parseUtonAmount(" ");
    assert.equal(blank.ok, false);
    if (!blank.ok) assert.match(blank.message, /Nothing was sent|how many uTON/);
  });
});

describe("desk burn path", () => {
  const fromRaw = Address.parse(FUNDED_WALLET_ADDRESS).toRawString();

  it("builds the bounce burn, the listed redeem, and the minter query from the desk wallet", () => {
    const compiled = compileDeskBurn({
      nanotons: "2500000000",
      jettonWallet: jettonFriendly,
      proxyId: "0",
      fromRaw,
      nowSeconds: 1_700_000_000,
    });
    assert.equal(compiled.ok, true);
    if (!compiled.ok) return;
    assert.equal(compiled.batches.length, 2);
    assert.equal(compiled.batches[0]?.messages.length, 4);
    assert.equal(compiled.batches[1]?.messages.length, 1);
    assert.equal(compiled.batches[0]?.network, TON_MAINNET_CHAIN);
    assert.equal(compiled.batches[0]?.from, fromRaw);
    assert.equal(compiled.batches[0]?.messages[0]?.address, jettonFriendly);
    assert.equal(compiled.batches[0]?.messages[0]?.amount, "200000000");
    assert.equal(compiled.batches[0]?.messages[1]?.address, utonMinter);
    assert.equal(compiled.batches[0]?.messages[1]?.amount, "150000000");
    assert.equal(compiled.batches[0]?.messages[2]?.address, jettonFriendly);
    assert.equal(compiled.batches[0]?.messages[3]?.address, utonMinter);
    assert.equal(compiled.batches[1]?.messages[0]?.address, utonMinter);
    assert.equal(compiled.batches[1]?.messages[0]?.amount, "500000000");

    const first = burnProxy(compiled.batches[0]?.messages[0]?.payload);
    const redeem = burnProxy(compiled.batches[0]?.messages[2]?.payload);
    assert.equal(first.amount, BigInt("2500000000"));
    assert.equal(first.proxy, 3);
    assert.equal(redeem.amount, BigInt("2500000000"));
    assert.equal(redeem.proxy, 0);

    const notify = Cell.fromBase64(compiled.batches[0]?.messages[1]?.payload ?? "").beginParse();
    assert.equal(notify.loadUint(32), 0x7bdd97de);
    notify.loadUint(64);
    assert.equal(notify.loadAddress().equals(Address.parse(FUNDED_WALLET_ADDRESS)), true);
    notify.loadUint(64);
    assert.equal(notify.loadCoins(), BigInt("2500000000"));
    assert.equal(notify.loadUint(32), 3);

    const query = Cell.fromBase64(compiled.batches[1]?.messages[0]?.payload ?? "").beginParse();
    assert.equal(query.loadUint(32), Number(UTON_OP.query));
    assert.match(compiled.summary, /redeem burn/);
    assert.match(compiled.skipped.join(" "), /pending withdraw/);
  });

  it("sends nothing when the listed proxy or the jetton wallet is missing", () => {
    const missingProxy = compileDeskBurn({
      nanotons: "1000000000",
      jettonWallet: jettonFriendly,
      fromRaw,
    });
    assert.equal(missingProxy.ok, false);
    if (!missingProxy.ok) assert.match(missingProxy.message, /Nothing was sent/);

    const missingJetton = compileDeskBurn({
      nanotons: "1000000000",
      proxyId: "0",
      fromRaw,
    });
    assert.equal(missingJetton.ok, false);
    if (!missingJetton.ok) assert.match(missingJetton.message, /jetton wallet/);
  });

  it("sends each batch once and stops when a later batch does not land", async () => {
    const sent: string[] = [];
    const gaps: number[] = [];
    const failed = await runDeskBurn({
      amountLabel: "1",
      nanotons: "1000000000",
      jettonWallet: jettonFriendly,
      proxyId: "0",
      fromRaw,
      nowSeconds: 1_700_000_000,
      sleep: async (ms) => {
        gaps.push(ms);
      },
      send: async (request) => {
        sent.push(request.messages[0]?.address ?? "");
        if (sent.length === 1) return { ok: true };
        return { ok: false, text: "The wallet did not confirm the message." };
      },
    });
    assert.equal(failed.ok, false);
    if (!failed.ok) assert.match(failed.text, /first part of the path was sent/);
    assert.deepEqual(gaps, [DESK_BURN_BATCH_GAP_MS]);
    assert.equal(sent.length, 2);

    const once: number[] = [];
    const slept: number[] = [];
    const done = await runDeskBurn({
      amountLabel: "1.5",
      nanotons: "1500000000",
      jettonWallet: jettonFriendly,
      proxyId: "0",
      fromRaw,
      sleep: async (ms) => {
        slept.push(ms);
      },
      send: async () => {
        once.push(1);
        return { ok: true };
      },
    });
    assert.equal(done.ok, true);
    if (!done.ok) return;
    assert.equal(once.length, 2);
    assert.deepEqual(slept, [DESK_BURN_BATCH_GAP_MS]);
    assert.match(done.text, /Burned 1\.5 uTON/);
    assert.match(done.href, /^https:\/\/tonviewer\.com\//);
  });
});

describe("path defaults note", () => {
  it("reads the lookup payload and explains a missing proxy", () => {
    assert.deepEqual(readPathDefaultsPayload({ ok: true, jettonWallet: jettonFriendly, proxyId: "0" }), {
      ok: true,
      jettonWallet: jettonFriendly,
      proxyId: "0",
    });
    assert.equal(readPathDefaultsPayload({ ok: false, message: "Wait." })?.ok, false);
    assert.equal(readPathDefaultsPayload(null), null);
    assert.match(deskLookupNote(null), /did not answer/);
    assert.match(
      deskLookupNote({ ok: true, jettonWallet: jettonFriendly }),
      /would not redeem/,
    );
    assert.match(deskLookupNote({ ok: true, jettonWallet: jettonFriendly, proxyId: "0" }), /Listed proxy 0/);
  });
});

describe("burn page wallet", () => {
  it("shows the desk wallet and no other connect path", () => {
    const html = renderToStaticMarkup(h(BurnDesk));
    assert.match(html, new RegExp(FUNDED_WALLET_ADDRESS));
    assert.match(html, /Burn to redeem/);
    assert.match(html, /uTON to burn/);
    assert.match(html, /sends from the desk wallet/);
    assert.equal(/Connect wallet|TonConnect|tonconnect/i.test(html), false);
    assert.equal(html.includes("disabled"), false);
  });

  it("keeps the recovery phrase out of the burn page sources", () => {
    for (const path of [
      new URL("./uton-burn-desk.ts", import.meta.url),
      new URL("../components/burn/burn-desk.tsx", import.meta.url),
      new URL("../app/burn/page.tsx", import.meta.url),
    ]) {
      const source = readFileSync(path, "utf8");
      assert.equal(textContainsFundedMnemonic(source), false);
      assert.equal(source.includes('from "./funded-wallet"'), false);
      assert.equal(source.includes('from "@/lib/funded-wallet"'), false);
    }
  });
});
