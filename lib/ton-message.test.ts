import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { Address, beginCell, Cell, Dictionary } from "@ton/core";
import {
  TON_MAINNET_CHAIN,
  chainLabel,
  classifySendError,
  addNanotons,
  compileScript,
  compileStep,
  outgoingRequest,
  connectFailureMessage,
  decodeTextComment,
  draftStepForTemplate,
  emptyStep,
  formatNanotons,
  insertTemplateDraft,
  isMainnetChain,
  normalizeMainnetAddress,
  readMaxMessages,
  scriptValueSummary,
  readFundedSendResult,
  sendFailureMessage,
  type ScriptStep,
} from "./ton-message";
import { utonTemplateBody, utonTemplateById, utonTemplates } from "./uton-templates";

const sample = new Address(0, Buffer.alloc(32, 7));
const other = new Address(0, Buffer.alloc(32, 9));

function step(patch: Partial<ScriptStep> = {}): ScriptStep {
  return {
    ...emptyStep("step"),
    destination: sample.toString({
      urlSafe: true,
      bounceable: true,
      testOnly: false,
    }),
    amount: "1",
    ...patch,
  };
}

describe("mainnet chain", () => {
  it("accepts only the mainnet global id", () => {
    assert.equal(isMainnetChain("-239"), true);
    assert.equal(isMainnetChain("-3"), false);
    assert.equal(isMainnetChain(undefined), false);
    assert.equal(chainLabel("-3"), "testnet");
    assert.equal(chainLabel("-239"), "mainnet");
  });

  it("reads the wallet message limit", () => {
    assert.equal(readMaxMessages(undefined), null);
    assert.deepEqual(readMaxMessages([]), { maxMessages: 1, advertised: false });
    assert.deepEqual(readMaxMessages(["SendTransaction"]), {
      maxMessages: 4,
      advertised: false,
    });
    assert.deepEqual(
      readMaxMessages([{ name: "SendTransaction", maxMessages: 4 }]),
      { maxMessages: 4, advertised: true },
    );
  });
});

describe("destination addresses", () => {
  it("keeps the bounce flag when the caller does not set one", () => {
    const bounceable = sample.toString({
      urlSafe: true,
      bounceable: true,
      testOnly: false,
    });
    const nonBounceable = sample.toString({
      urlSafe: true,
      bounceable: false,
      testOnly: false,
    });

    assert.equal(normalizeMainnetAddress(`  ${bounceable}  `), bounceable);
    assert.equal(normalizeMainnetAddress(nonBounceable), nonBounceable);
  });

  it("uses the requested bounce flag", () => {
    const bounceable = sample.toString({
      urlSafe: true,
      bounceable: true,
      testOnly: false,
    });
    const nonBounceable = sample.toString({
      urlSafe: true,
      bounceable: false,
      testOnly: false,
    });
    assert.equal(normalizeMainnetAddress(bounceable, false), nonBounceable);
  });

  it("rejects a testnet-only friendly address", () => {
    const testOnly = sample.toString({
      urlSafe: true,
      bounceable: true,
      testOnly: true,
    });
    assert.throws(() => normalizeMainnetAddress(testOnly), /marked for testnet/);
  });

  it("converts a raw address to a non-bounceable mainnet address by default", () => {
    const friendly = normalizeMainnetAddress(sample.toRawString());
    const parsed = Address.parseFriendly(friendly);
    assert.equal(parsed.isTestOnly, false);
    assert.equal(parsed.isBounceable, false);
    assert.equal(parsed.address.equals(sample), true);
  });
});

describe("compileStep", () => {
  it("builds an empty message and a text comment", () => {
    const empty = compileStep(step({ amount: "0", body: { kind: "empty" } }));
    assert.equal(empty.ok, true);
    if (!empty.ok) return;
    assert.equal(empty.message.amount, "0");
    assert.equal("payload" in empty.message, false);
    assert.equal(empty.preview.bodyLabel, "Empty body");

    const comment = compileStep(
      step({
        amount: "1.25",
        unit: "ton",
        body: { kind: "comment", text: "  Rent  " },
      }),
    );
    assert.equal(comment.ok, true);
    if (!comment.ok) return;
    assert.equal(comment.message.amount, "1250000000");
    assert.equal(decodeTextComment(comment.message.payload ?? ""), "Rent");
    assert.match(comment.preview.bodyLabel, /Rent/);
  });

  it("builds an opcode and fields in one cell", () => {
    const compiled = compileStep(
      step({
        unit: "nanoton",
        amount: "42",
        body: {
          kind: "fields",
          opcode: "0x7",
          opcodeBits: "32",
          fields: [{ id: "n", kind: "uint", bits: "8", value: "3" }],
        },
      }),
    );
    assert.equal(compiled.ok, true);
    if (!compiled.ok) return;
    assert.equal(compiled.message.amount, "42");
    const slice = Cell.fromBase64(compiled.message.payload ?? "").beginParse();
    assert.equal(slice.loadUint(32), 7);
    assert.equal(slice.loadUint(8), 3);
    assert.match(compiled.preview.bodyLabel, /Opcode 0x7/);
  });

  it("accepts a hex BoC and rejects a text tail that is not last", () => {
    const cell = beginCell().storeUint(9, 16).endCell();
    const boc = compileStep(
      step({ body: { kind: "boc", hex: cell.toBoc().toString("hex") } }),
    );
    assert.equal(boc.ok, true);
    if (!boc.ok) return;
    assert.equal(
      Cell.fromBase64(boc.message.payload ?? "").beginParse().loadUint(16),
      9,
    );

    const tail = compileStep(
      step({
        body: {
          kind: "fields",
          opcode: "",
          opcodeBits: "32",
          fields: [
            { id: "text", kind: "text", value: "hi" },
            { id: "n", kind: "uint", bits: "8", value: "1" },
          ],
        },
      }),
    );
    assert.equal(tail.ok, false);
    if (tail.ok) return;
    assert.match(tail.errors.fields?.text ?? "", /last field/);
  });

  it("reports an invalid destination, value, and testnet address", () => {
    const invalid = compileStep(
      step({
        destination: "not-an-address",
        amount: "1.1234567891",
        body: { kind: "comment", text: "" },
      }),
    );
    assert.equal(invalid.ok, false);
    if (invalid.ok) return;
    assert.match(invalid.errors.destination ?? "", /could not be read/);
    assert.match(invalid.errors.amount ?? "", /9 decimal places/);
    assert.match(invalid.errors.body ?? "", /Enter a comment/);

    const testOnly = sample.toString({
      urlSafe: true,
      bounceable: false,
      testOnly: true,
    });
    const rejected = compileStep(step({ destination: testOnly }));
    assert.equal(rejected.ok, false);
    if (rejected.ok) return;
    assert.match(rejected.errors.destination ?? "", /testnet/);
  });
});

describe("compileScript", () => {
  it("batches messages on mainnet and stops at the wallet limit", () => {
    const first = step({ id: "a", amount: "0.5" });
    const second = step({
      id: "b",
      destination: other.toRawString(),
      bounceable: false,
      amount: "2",
      body: { kind: "comment", text: "next" },
    });
    const result = compileScript([first, second], {
      fromRaw: sample.toRawString(),
      nowSeconds: 1_700_000_000,
      maxMessages: 4,
    });

    assert.equal(result.ok, true);
    if (!result.ok) return;
    assert.equal(result.request.network, TON_MAINNET_CHAIN);
    assert.equal(result.request.validUntil, 1_700_000_600);
    assert.equal(result.request.from, sample.toRawString());
    assert.equal(result.request.messages.length, 2);
    assert.deepEqual(
      outgoingRequest(result.request.messages, {
        fromRaw: sample.toRawString(),
        nowSeconds: 1_700_000_000,
      }),
      result.request,
    );
    assert.equal(result.request.messages[0]?.amount, "500000000");
    assert.equal(decodeTextComment(result.request.messages[1]?.payload ?? ""), "next");
    assert.equal(result.previews[1]?.bounceable, false);

    const limited = compileScript([first, second], { maxMessages: 1 });
    assert.equal(limited.ok, false);
    if (limited.ok) return;
    assert.match(limited.message ?? "", /accepts 1 message/);
  });
});

describe("script value", () => {
  it("sums compiled steps and leaves an unfinished script unlabeled as zero", () => {
    assert.equal(formatNanotons("0"), "0 TON");
    assert.equal(formatNanotons("1250000000"), "1.25 TON");
    assert.equal(formatNanotons("42"), "0.000000042 TON");
    assert.equal(addNanotons(["500000000", "1250000000"]), "1750000000");

    const ready = compileStep(step({ amount: "1.5" }));
    const draft = compileStep(step({ destination: "", amount: "" }));
    assert.equal(scriptValueSummary([]), "No messages in this script.");
    assert.equal(scriptValueSummary([draft]), "1 message. Complete it to see a total.");
    assert.equal(
      scriptValueSummary([ready]),
      "1 message · 1.5 TON in this script.",
    );
    assert.equal(
      scriptValueSummary([ready, draft]),
      "1 of 2 steps compile · 1.5 TON so far.",
    );
  });
});

describe("template drafts", () => {
  it("inserts one editable step per known template and keeps the whitelisted proxy id", () => {
    let steps: ScriptStep[] = [emptyStep("step-1")];
    for (const template of utonTemplates) {
      const draft = draftStepForTemplate(`draft-${template.id}`, template.id);
      assert.ok(draft);
      assert.equal(draft.destination, "");
      assert.equal(draft.amount, "");
      assert.equal(draft.unit, "ton");
      assert.equal(draft.bounceable, template.bounceable);
      assert.equal(draft.body.kind, "fields");
      if (draft.body.kind !== "fields") continue;
      assert.equal(draft.body.templateId, template.id);
      assert.equal(draft.body.opcode, template.opcode);
      const proxy = draft.body.fields.find((field) => field.id === "proxy_id");
      if (template.id === "uton-burn" || template.id === "burn-notification") {
        assert.equal(proxy?.value, "3");
      }
      steps = insertTemplateDraft(steps, template.id, draft.id);
    }

    assert.deepEqual(
      steps.map((step) => step.id),
      utonTemplates.map((template) => `draft-${template.id}`),
    );
    const filled = steps[0];
    assert.ok(filled);
    const kept = insertTemplateDraft(
      [{ ...filled, destination: "EQ..." }],
      "withdraw",
      "added",
    );
    assert.equal(kept.length, 2);
    assert.equal(kept[0]?.id, filled.id);
    assert.equal(kept[1]?.body.kind, "fields");
    assert.equal(insertTemplateDraft(steps, "missing-template", "nope").length, steps.length);
  });
});

describe("uTON templates", () => {
  function drafted(
    templateId: string,
    values: Record<string, string>,
    patch: Partial<ScriptStep> = {},
  ): ScriptStep {
    const template = utonTemplateById(templateId);
    if (!template) throw new Error(templateId);
    const body = utonTemplateBody(template);
    return {
      ...emptyStep("template"),
      destination: sample.toString({ urlSafe: true, bounceable: true, testOnly: false }),
      amount: "0.05",
      bounceable: true,
      ...patch,
      body: {
        ...body,
        ...((patch.body ?? {}) as object),
        fields: body.fields.map((field) => ({
          ...field,
          value: values[field.id] ?? field.value,
        })),
      },
    };
  }

  it("encodes a burn as opcode, coins, response, and a dictionary at key 0", () => {
    const response = other.toString({ urlSafe: true, bounceable: false, testOnly: false });
    const compiled = compileStep(
      drafted("uton-burn", {
        query_id: "7",
        amount: "1000",
        response,
        proxy_id: "0",
        fwd_value: "10000000",
      }),
    );
    assert.equal(compiled.ok, true);
    if (!compiled.ok) return;
    assert.equal(compiled.preview.bodyLabel, "uTON burn · proxy_id 0");

    const slice = Cell.fromBase64(compiled.message.payload ?? "").beginParse();
    assert.equal(slice.loadUint(32), 0x595f07bc);
    assert.equal(slice.loadUint(64), 7);
    assert.equal(slice.loadCoins(), 1000n);
    assert.equal(slice.loadAddress().equals(other), true);
    const dict = slice.loadDict(Dictionary.Keys.Uint(32), Dictionary.Values.Cell());
    assert.equal(slice.remainingBits, 0);
    const payload = dict.get(0);
    assert.ok(payload);
    const inner = payload.beginParse();
    assert.equal(inner.loadUint(32), 0);
    assert.equal(inner.loadCoins(), 10000000n);
    assert.equal(inner.loadRef().beginParse().remainingBits, 0);
    assert.equal(inner.remainingRefs, 0);
  });

  it("stores the burn notification owner before the amount and keeps an empty forward ref", () => {
    const owner = sample.toString({ urlSafe: true, bounceable: true, testOnly: false });
    const response = other.toString({ urlSafe: true, bounceable: true, testOnly: false });
    const compiled = compileStep(
      drafted("burn-notification", {
        query_id: "1",
        owner,
        withdraw_id: "4",
        amount: "50",
        proxy_id: "2",
        response,
        fwd_value: "3",
      }),
    );
    assert.equal(compiled.ok, true);
    if (!compiled.ok) return;
    assert.match(compiled.preview.bodyLabel, /Burn notification · proxy_id 2/);
    const slice = Cell.fromBase64(compiled.message.payload ?? "").beginParse();
    assert.equal(slice.loadUint(32), 0x7bdd97de);
    assert.equal(slice.loadUint(64), 1);
    assert.equal(slice.loadAddress().equals(sample), true);
    assert.equal(slice.loadUint(64), 4);
    assert.equal(slice.loadCoins(), 50n);
    assert.equal(slice.loadUint(32), 2);
    assert.equal(slice.loadAddress().equals(other), true);
    assert.equal(slice.loadCoins(), 3n);
    assert.equal(slice.loadRef().beginParse().remainingBits, 0);
  });

  it("encodes withdraw, native stake, and a jetton transfer", () => {
    const recipient = sample.toString({ urlSafe: true, bounceable: true, testOnly: false });
    const response = other.toString({ urlSafe: true, bounceable: false, testOnly: false });

    const withdraw = compileStep(
      drafted("withdraw", { query_id: "9", recipient, response }),
    );
    assert.equal(withdraw.ok, true);
    if (!withdraw.ok) return;
    assert.equal(withdraw.preview.bodyLabel, "Withdraw");
    const withdrawSlice = Cell.fromBase64(withdraw.message.payload ?? "").beginParse();
    assert.equal(withdrawSlice.loadUint(32), 0x4502);
    assert.equal(withdrawSlice.loadUint(64), 9);
    assert.equal(withdrawSlice.loadAddress().equals(sample), true);
    assert.equal(withdrawSlice.loadAddress().equals(other), true);
    assert.equal(withdrawSlice.remainingBits, 0);

    const stake = compileStep(
      drafted("stake-ton", { query_id: "0", user: recipient, response }),
    );
    assert.equal(stake.ok, true);
    if (!stake.ok) return;
    const stakeSlice = Cell.fromBase64(stake.message.payload ?? "").beginParse();
    assert.equal(stakeSlice.loadUint(32), 0x1003);
    assert.equal(stakeSlice.loadUint(64), 0);
    assert.equal(stakeSlice.loadAddress().equals(sample), true);

    const transfer = compileStep(
      drafted("jetton-transfer", {
        query_id: "0",
        amount: "8",
        destination: recipient,
        response,
        forward_ton: "0",
        forward_text: "",
      }),
    );
    assert.equal(transfer.ok, true);
    if (!transfer.ok) return;
    assert.equal(transfer.preview.bodyLabel, "uTON transfer");
    const transferSlice = Cell.fromBase64(transfer.message.payload ?? "").beginParse();
    assert.equal(transferSlice.loadUint(32), 0x0f8a7ea5);
    assert.equal(transferSlice.loadUint(64), 0);
    assert.equal(transferSlice.loadCoins(), 8n);
    assert.equal(transferSlice.loadAddress().equals(sample), true);
    assert.equal(transferSlice.loadAddress().equals(other), true);
    assert.equal(transferSlice.loadBit(), false);
    assert.equal(transferSlice.loadCoins(), 0n);
    assert.equal(transferSlice.loadBit(), false);

    const withText = compileStep(
      drafted("jetton-transfer", {
        query_id: "0",
        amount: "8",
        destination: recipient,
        response,
        forward_ton: "5",
        forward_text: "hi",
      }),
    );
    assert.equal(withText.ok, true);
    if (!withText.ok) return;
    const textSlice = Cell.fromBase64(withText.message.payload ?? "").beginParse();
    textSlice.loadUint(32);
    textSlice.loadUint(64);
    textSlice.loadCoins();
    textSlice.loadAddress();
    textSlice.loadAddress();
    assert.equal(textSlice.loadBit(), false);
    assert.equal(textSlice.loadCoins(), 5n);
    assert.equal(textSlice.loadBit(), true);
    assert.equal(textSlice.loadRef().beginParse().loadStringTail(), "hi");
  });

  it("uses an edited opcode and reports a missing burn amount", () => {
    const edited = drafted("withdraw", {
      query_id: "1",
      recipient: sample.toString({ urlSafe: true, bounceable: true, testOnly: false }),
      response: other.toString({ urlSafe: true, bounceable: true, testOnly: false }),
    });
    if (edited.body.kind !== "fields") return;
    edited.body.opcode = "0x1";
    const compiled = compileStep(edited);
    assert.equal(compiled.ok, true);
    if (!compiled.ok) return;
    assert.equal(Cell.fromBase64(compiled.message.payload ?? "").beginParse().loadUint(32), 1);

    const missing = compileStep(drafted("uton-burn", { amount: "" }));
    assert.equal(missing.ok, false);
    if (missing.ok) return;
    assert.match(missing.errors.fields?.amount ?? "", /nanotons/);
  });
});

describe("send failures", () => {
  it("classifies wallet responses without treating an unknown outcome as safe to retry", () => {
    assert.equal(classifySendError({ name: "UserRejectsError" }), "cancelled");
    assert.equal(
      classifySendError({ name: "WalletWrongNetworkError" }),
      "wrong-network",
    );
    assert.equal(classifySendError({ walletError: { code: 1 } }), "rejected");
    assert.equal(
      classifySendError({ name: "WalletNotSupportFeatureError" }),
      "rejected",
    );
    assert.equal(classifySendError(new Error("socket hang up")), "ambiguous");
    assert.match(sendFailureMessage("ambiguous"), /not sent twice/);
    assert.deepEqual(
      readFundedSendResult({
        ok: false,
        kind: "ambiguous",
        message: "Nothing was sent. Safe to try again.",
      }),
      { ok: false, text: "Nothing was sent. Safe to try again." },
    );
    assert.equal(readFundedSendResult({ ok: false, kind: "ambiguous" }), null);
    assert.deepEqual(readFundedSendResult({ ok: true }), { ok: true });
    assert.equal(
      connectFailureMessage("cancelled", "https://example.com/manifest.json"),
      null,
    );
  });
});
