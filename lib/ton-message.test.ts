import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { Address, beginCell, Cell } from "@ton/core";
import {
  TON_MAINNET_CHAIN,
  chainLabel,
  classifySendError,
  compileScript,
  compileStep,
  connectFailureMessage,
  decodeTextComment,
  emptyStep,
  isMainnetChain,
  normalizeMainnetAddress,
  readMaxMessages,
  sendFailureMessage,
  type ScriptStep,
} from "./ton-message";

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
    assert.equal(result.request.messages[0]?.amount, "500000000");
    assert.equal(decodeTextComment(result.request.messages[1]?.payload ?? ""), "next");
    assert.equal(result.previews[1]?.bounceable, false);

    const limited = compileScript([first, second], { maxMessages: 1 });
    assert.equal(limited.ok, false);
    if (limited.ok) return;
    assert.match(limited.message ?? "", /accepts 1 message/);
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
    assert.equal(
      connectFailureMessage("cancelled", "https://example.com/manifest.json"),
      null,
    );
  });
});
