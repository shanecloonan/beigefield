import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { Address } from "@ton/core";
import { utonLinks, utonMinter, utonSource } from "./uton";
import { UTON_OP, templatePreviewLabel, utonTemplateById } from "./uton-templates";

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

  it("pins the opcodes the contracts load", () => {
    assert.equal(UTON_OP.burn, "0x595f07bc");
    assert.equal(UTON_OP.burnNotification, "0x7bdd97de");
    assert.equal(UTON_OP.withdraw, "0x4502");
    assert.equal(UTON_OP.stake, "0x1003");
    assert.equal(UTON_OP.transfer, "0x0f8a7ea5");
    const burnProxy = utonTemplateById("uton-burn")?.fields.find((field) => field.id === "proxy_id");
    const notifyProxy = utonTemplateById("burn-notification")?.fields.find((field) => field.id === "proxy_id");
    assert.equal(burnProxy?.label, "Proxy id");
    assert.equal(burnProxy?.value, "3");
    assert.equal(notifyProxy?.value, "3");
    assert.equal(templatePreviewLabel("uton-burn", [{ id: "proxy_id", value: "0" }]), "uTON burn · proxy_id 0");
    assert.equal(templatePreviewLabel("burn-notification", [{ id: "proxy_id", value: "3" }]), "Burn notification · proxy_id 3");
  });
});
