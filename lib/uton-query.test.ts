import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { Address, Cell } from "@ton/core";
import { utonTemplateBody, utonTemplateById } from "./uton-templates";
import { utonMinter } from "./uton";
import { compileMinterQuery, minterQueryFailure, MINTER_QUERY_FEE_NANOTON } from "./uton-query";
import type { ScriptStep } from "./ton-message";

const recipient = new Address(0, Buffer.alloc(32, 7));
const response = new Address(0, Buffer.alloc(32, 9));

function withdraw(patch: Partial<ScriptStep> = {}, values: Record<string, string> = {}): ScriptStep {
  const template = utonTemplateById("withdraw");
  if (!template) throw new Error("withdraw");
  const body = utonTemplateBody(template);
  return {
    id: "withdraw",
    destination: recipient.toString({ urlSafe: true, bounceable: true, testOnly: false }),
    amount: "0.05",
    unit: "ton",
    bounceable: true,
    ...patch,
    body: {
      ...body,
      fields: body.fields.map((field) => ({
        ...field,
        value: values[field.id] ?? field.value,
      })),
    },
  };
}

describe("minter query", () => {
  it("encodes opcode 0x1001 to the minter with the withdraw reference", () => {
    const compiled = compileMinterQuery(
      withdraw(
        {},
        {
          query_id: "9",
          recipient: recipient.toString({ urlSafe: true, bounceable: true, testOnly: false }),
          response: response.toString({ urlSafe: true, bounceable: false, testOnly: false }),
        },
      ),
    );
    assert.equal(compiled.ok, true);
    if (!compiled.ok) return;
    assert.equal(compiled.preview.bodyLabel, "Minter query");
    assert.equal(
      compiled.message.address,
      Address.parse(utonMinter).toString({ urlSafe: true, bounceable: true, testOnly: false }),
    );
    assert.equal(compiled.message.amount, "50000000");
    const slice = Cell.fromBase64(compiled.message.payload ?? "").beginParse();
    assert.equal(slice.loadUint(32), 0x1001);
    assert.equal(slice.loadUint(64), 9);
    const reference = slice.loadRef().beginParse();
    assert.equal(reference.loadAddress().equals(recipient), true);
    assert.equal(reference.loadAddress().equals(response), true);
    assert.equal(reference.remainingBits, 0);
    assert.equal(slice.remainingRefs, 0);
  });

  it("requires more than the minter query fee and a withdraw body", () => {
    assert.equal(MINTER_QUERY_FEE_NANOTON, BigInt(10_000_000));
    const addresses = {
      query_id: "9",
      recipient: recipient.toString({ urlSafe: true, bounceable: true, testOnly: false }),
      response: response.toString({ urlSafe: true, bounceable: false, testOnly: false }),
    };
    const low = compileMinterQuery(withdraw({ amount: "0.01" }, addresses));
    assert.equal(low.ok, false);
    if (low.ok) return;
    assert.match(minterQueryFailure(low.errors), /more than 0\.01 TON/);

    const missing = compileMinterQuery(withdraw({ amount: "" }, addresses));
    assert.equal(missing.ok, false);
    if (missing.ok) return;
    assert.match(minterQueryFailure(missing.errors), /TON attached on the withdraw/);

    const other = withdraw();
    other.body = { kind: "empty" };
    const rejected = compileMinterQuery(other);
    assert.equal(rejected.ok, false);
    if (rejected.ok) return;
    assert.match(minterQueryFailure(rejected.errors), /query id, recipient, and response/);
  });
});