import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { Address, beginCell, Dictionary } from "@ton/core";
import {
  listedProxyId,
  loadPathDefaults,
  proxyWhitelistValue,
  readListedProxies,
} from "./uton-path-defaults";

const native = new Address(0, Buffer.alloc(32, 1));
const other = new Address(0, Buffer.alloc(32, 2));
const owner = new Address(0, Buffer.alloc(32, 3));
const jetton = new Address(0, Buffer.alloc(32, 9));

function whitelist(entries: Array<{ id: number; address: Address; type: number }>) {
  const dict = Dictionary.empty(Dictionary.Keys.Uint(32), proxyWhitelistValue);
  for (const entry of entries) {
    dict.set(entry.id, { address: entry.address, type: entry.type });
  }
  return beginCell().storeDictDirect(dict).endCell();
}

describe("listed proxies", () => {
  it("reads the whitelist and prefers the native type 0 proxy", () => {
    const entries = readListedProxies(
      whitelist([
        { id: 3, address: other, type: 1 },
        { id: 4, address: other, type: 2 },
        { id: 0, address: native, type: 0 },
      ]),
    );
    assert.deepEqual(
      entries.map((entry) => entry.id).sort((left, right) => left - right),
      [0, 3, 4],
    );
    assert.equal(listedProxyId(entries), "0");
    assert.equal(
      listedProxyId([
        { id: 3, type: 1 },
        { id: 12, type: 2 },
        { id: 4, type: 2 },
      ]),
      "4",
    );
    assert.equal(listedProxyId([{ id: 3, type: 1 }]), undefined);
  });
});

describe("path default lookup", () => {
  it("returns the bounceable jetton wallet and keeps going when the whitelist read fails", async () => {
    const ok = await loadPathDefaults(owner.toString(), {
      jettonWallet: async (parsed) => {
        assert.equal(parsed.equals(owner), true);
        return jetton;
      },
      proxies: async () => [{ id: 0, type: 0 }],
    });
    assert.equal(ok.ok, true);
    if (!ok.ok) return;
    assert.equal(ok.jettonWallet, jetton.toString({ urlSafe: true, bounceable: true, testOnly: false }));
    assert.equal(ok.proxyId, "0");

    const noProxy = await loadPathDefaults(owner.toString(), {
      jettonWallet: async () => jetton,
      proxies: async () => {
        throw new Error("minter");
      },
    });
    assert.equal(noProxy.ok, true);
    if (!noProxy.ok) return;
    assert.equal(noProxy.proxyId, undefined);
  });

  it("rejects a bad owner and reports a minter that does not answer", async () => {
    const bad = await loadPathDefaults("not-an-address", {
      jettonWallet: async () => jetton,
      proxies: async () => [],
    });
    assert.deepEqual(bad, { ok: false, status: 400, message: "Enter a mainnet wallet address." });

    const testnet = new Address(-1, Buffer.alloc(32, 1));
    const wrongChain = await loadPathDefaults(testnet.toString({ testOnly: true }), {
      jettonWallet: async () => jetton,
      proxies: async () => [],
    });
    assert.equal(wrongChain.ok, false);
    if (wrongChain.ok) return;
    assert.equal(wrongChain.status, 400);

    const down = await loadPathDefaults(owner.toString(), {
      jettonWallet: async () => {
        throw new Error("timeout");
      },
      proxies: async () => [],
    });
    assert.equal(down.ok, false);
    if (down.ok) return;
    assert.equal(down.status, 502);
    assert.match(down.message, /uTON jetton wallet was not filled/);
    assert.match(down.message, /Wait a moment and try again/);
  });
});
