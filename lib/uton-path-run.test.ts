import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { Address, Cell } from "@ton/core";
import { FUNDED_WALLET_ADDRESS } from "./funded-wallet-public";
import { TON_MAINNET_CHAIN, type ScriptStep } from "./ton-message";
import { utonMinter } from "./uton";
import { utonTemplateBody, utonTemplateById } from "./uton-templates";
import { applyPathDefaults, compilePathRun, PATH_GAS_TON, PATH_UTON_NANO } from "./uton-path-run";

const owner = new Address(0, Buffer.alloc(32, 4));
const jetton = new Address(0, Buffer.alloc(32, 8));
const edited = new Address(0, Buffer.alloc(32, 6));
const pending = new Address(0, Buffer.alloc(32, 5));

function friendly(address: Address, bounceable = true): string {
  return address.toString({ urlSafe: true, bounceable, testOnly: false });
}

function fieldsOf(step: ScriptStep) {
  assert.equal(step.body.kind, "fields");
  if (step.body.kind !== "fields") throw new Error("fields");
  return step.body.fields;
}

function fieldValue(step: ScriptStep, id: string): string {
  const field = fieldsOf(step).find((item) => item.id === id);
  assert.ok(field);
  return field.value;
}

function drafted(id: string, templateId: string, values: Record<string, string> = {}): ScriptStep {
  const template = utonTemplateById(templateId);
  if (!template) throw new Error(templateId);
  const body = utonTemplateBody(template);
  return {
    id,
    destination: "",
    amount: "",
    unit: "ton",
    bounceable: template.bounceable,
    body: {
      ...body,
      fields: body.fields.map((field) => ({
        ...field,
        value: values[field.id] ?? field.value,
      })),
    },
  };
}

function pathSteps(): ScriptStep[] {
  return [
    drafted("burn", "uton-burn", { response: FUNDED_WALLET_ADDRESS, amount: "" }),
    drafted("notify", "burn-notification", {
      owner: FUNDED_WALLET_ADDRESS,
      response: FUNDED_WALLET_ADDRESS,
      amount: "",
    }),
    drafted("redeem-burn", "uton-burn", {
      response: FUNDED_WALLET_ADDRESS,
      amount: "",
      proxy_id: "",
    }),
    drafted("redeem-notify", "burn-notification", {
      owner: FUNDED_WALLET_ADDRESS,
      response: FUNDED_WALLET_ADDRESS,
      amount: "",
      proxy_id: "",
    }),
    drafted("withdraw", "withdraw", {
      recipient: FUNDED_WALLET_ADDRESS,
      response: FUNDED_WALLET_ADDRESS,
    }),
  ];
}

describe("path defaults", () => {
  it("fills derived addresses, gas, uTON, and the listed proxy without clobbering edits", () => {
    const filled = applyPathDefaults(pathSteps(), {
      owner: friendly(owner, false),
      jettonWallet: friendly(jetton),
      proxyId: "0",
    });
    const burn = filled[0];
    const notify = filled[1];
    const redeem = filled[2];
    const redeemNotify = filled[3];
    const withdraw = filled[4];
    assert.ok(burn && notify && redeem && redeemNotify && withdraw);

    assert.equal(burn.destination, friendly(jetton));
    assert.equal(burn.amount, PATH_GAS_TON.burn);
    assert.equal(fieldValue(burn, "amount"), PATH_UTON_NANO);
    assert.equal(fieldValue(burn, "proxy_id"), "3");
    assert.equal(Address.parse(fieldValue(burn, "response")).equals(owner), true);

    assert.equal(notify.destination, utonMinter);
    assert.equal(notify.amount, PATH_GAS_TON.notify);
    assert.equal(fieldValue(notify, "proxy_id"), "3");
    assert.equal(Address.parse(fieldValue(notify, "owner")).equals(owner), true);

    assert.equal(redeem.destination, friendly(jetton));
    assert.equal(fieldValue(redeem, "proxy_id"), "0");
    assert.equal(fieldValue(redeemNotify, "proxy_id"), "0");
    assert.equal(redeemNotify.destination, utonMinter);
    assert.equal(withdraw.destination, "");
    assert.equal(withdraw.amount, PATH_GAS_TON.withdraw);

    const editedSteps = filled.map((step) => {
      if (step.id !== "burn" || step.body.kind !== "fields") return step;
      return {
        ...step,
        destination: friendly(edited),
        amount: "0.9",
        body: {
          ...step.body,
          fields: step.body.fields.map((field) =>
            field.id === "response" ? { ...field, value: friendly(edited, false) } : field,
          ),
        },
      };
    });
    const kept = applyPathDefaults(editedSteps, {
      owner: friendly(owner, false),
      jettonWallet: friendly(jetton),
      proxyId: "1",
      previousOwner: friendly(owner, false),
      previousJetton: friendly(jetton),
      previousProxy: "0",
    });
    const keptBurn = kept[0];
    const keptRedeem = kept[2];
    assert.ok(keptBurn && keptRedeem);
    assert.equal(keptBurn.destination, friendly(edited));
    assert.equal(keptBurn.amount, "0.9");
    assert.equal(Address.parse(fieldValue(keptBurn, "response")).equals(edited), true);
    assert.equal(fieldValue(keptRedeem, "proxy_id"), "1");

    const typed = kept.map((step) => {
      if (step.id !== "redeem-burn" || step.body.kind !== "fields") return step;
      return {
        ...step,
        body: {
          ...step.body,
          fields: step.body.fields.map((field) =>
            field.id === "proxy_id" ? { ...field, value: "7" } : field,
          ),
        },
      };
    });
    const held = applyPathDefaults(typed, {
      owner: friendly(owner, false),
      jettonWallet: friendly(jetton),
      proxyId: "0",
      previousOwner: friendly(owner, false),
      previousJetton: friendly(jetton),
      previousProxy: "1",
    });
    const heldRedeem = held[2];
    assert.ok(heldRedeem);
    assert.equal(fieldValue(heldRedeem, "proxy_id"), "7");
  });
});

describe("path run", () => {
  it("batches the broadcasts and leaves the pending withdraw out until its address is filled", () => {
    const steps = applyPathDefaults(pathSteps(), {
      owner: friendly(owner, false),
      jettonWallet: friendly(jetton),
      proxyId: "0",
    });
    const byId = Object.fromEntries(steps.map((step) => [step.id, step]));
    const compiled = compilePathRun(
      {
        burn: byId.burn!,
        notify: byId.notify!,
        redeemBurn: byId["redeem-burn"]!,
        redeemNotify: byId["redeem-notify"]!,
        withdraw: byId.withdraw!,
      },
      { fromRaw: owner.toRawString(), nowSeconds: 1_700_000_000, maxMessages: 4 },
    );
    assert.equal(compiled.ok, true);
    if (!compiled.ok) return;
    assert.equal(compiled.batches.length, 2);
    assert.equal(compiled.batches[0]?.messages.length, 4);
    assert.equal(compiled.batches[1]?.messages.length, 1);
    assert.equal(compiled.batches[0]?.network, TON_MAINNET_CHAIN);
    assert.equal(compiled.batches[0]?.from, owner.toRawString());
    assert.equal(compiled.batches[0]?.validUntil, 1_700_000_000 + 600);
    assert.match(compiled.summary, /Burn, burn notification, redeem burn, redeem notification, and minter query/);
    assert.match(compiled.skipped.join(" "), /pending withdraw contract/);
    assert.doesNotMatch(compiled.summary, /Withdraw/);

    const burnSlice = Cell.fromBase64(compiled.batches[0]?.messages[0]?.payload ?? "").beginParse();
    assert.equal(burnSlice.loadUint(32), 0x595f07bc);
    const querySlice = Cell.fromBase64(compiled.batches[1]?.messages[0]?.payload ?? "").beginParse();
    assert.equal(querySlice.loadUint(32), 0x1001);
    assert.equal(compiled.batches[1]?.messages[0]?.address, utonMinter);

    const withWithdraw = compilePathRun(
      {
        burn: byId.burn!,
        notify: byId.notify!,
        redeemBurn: byId["redeem-burn"]!,
        redeemNotify: byId["redeem-notify"]!,
        withdraw: { ...byId.withdraw!, destination: friendly(pending) },
      },
      { nowSeconds: 1_700_000_000, maxMessages: 4 },
    );
    assert.equal(withWithdraw.ok, true);
    if (!withWithdraw.ok) return;
    assert.match(withWithdraw.summary, /withdraw/);
    assert.equal(withWithdraw.batches[1]?.messages.length, 2);
  });

  it("explains a missing jetton wallet and skips a redeem that has no listed proxy", () => {
    const steps = pathSteps();
    const burn = steps[0];
    const notify = steps[1];
    assert.ok(burn && notify);
    const missing = compilePathRun({
      burn: { ...burn, amount: "0.2" },
      notify: { ...notify, destination: utonMinter, amount: "0.15" },
      redeemBurn: burn,
      redeemNotify: notify,
      withdraw: steps[4]!,
    });
    assert.equal(missing.ok, false);
    if (missing.ok) return;
    assert.match(missing.message, /uTON jetton wallet/);

    const ready = applyPathDefaults(pathSteps(), {
      owner: friendly(owner, false),
      jettonWallet: friendly(jetton),
    });
    const byId = Object.fromEntries(ready.map((step) => [step.id, step]));
    const skipped = compilePathRun({
      burn: byId.burn!,
      notify: byId.notify!,
      redeemBurn: byId["redeem-burn"]!,
      redeemNotify: byId["redeem-notify"]!,
      withdraw: byId.withdraw!,
    });
    assert.equal(skipped.ok, true);
    if (!skipped.ok) return;
    assert.match(skipped.skipped.join(" "), /proxy id the minter lists/);
    assert.equal(skipped.batches[0]?.messages.length, 3);
  });
});
