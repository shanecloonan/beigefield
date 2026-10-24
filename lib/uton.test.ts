import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { Address } from "@ton/core";
import { utonLinks, utonMinter, utonSource } from "./uton";

describe("uTON reference", () => {
  it("records a mainnet minter and the pinned source commit", () => {
    const parsed = Address.parseFriendly(utonMinter);
    assert.equal(parsed.isTestOnly, false);
    assert.equal(parsed.address.workChain, 0);
    assert.equal(utonSource.short, utonSource.commit.slice(0, 7));
    assert.match(utonLinks.tree, new RegExp(`${utonSource.commit}$`));
    assert.match(utonLinks.tonviewer, new RegExp(`${utonMinter}$`));
    assert.match(utonLinks.wallet, /contracts\/wallet\.func$/);
  });
});
