import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { Address, Cell } from "@ton/core";
import {
  TON_MAINNET_CHAIN,
  chainLabel,
  classifySendError,
  connectFailureMessage,
  decodeTextComment,
  isMainnetChain,
  normalizeMainnetAddress,
  sendFailureMessage,
  validateMainnetTransfer,
} from "./ton-message";

const sample = new Address(0, Buffer.alloc(32, 7));

describe("mainnet chain", () => {
  it("accepts only the mainnet global id", () => {
    assert.equal(isMainnetChain("-239"), true);
    assert.equal(isMainnetChain("-3"), false);
    assert.equal(isMainnetChain(undefined), false);
    assert.equal(chainLabel("-3"), "testnet");
    assert.equal(chainLabel("-239"), "mainnet");
  });
});

describe("destination addresses", () => {
  it("keeps the bounce flag on a mainnet friendly address", () => {
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

  it("rejects a testnet-only friendly address", () => {
    const testOnly = sample.toString({
      urlSafe: true,
      bounceable: true,
      testOnly: true,
    });
    assert.throws(
      () => normalizeMainnetAddress(testOnly),
      /marked for testnet/,
    );
  });

  it("converts a raw address to a non-bounceable mainnet address", () => {
    const friendly = normalizeMainnetAddress(sample.toRawString());
    const parsed = Address.parseFriendly(friendly);
    assert.equal(parsed.isTestOnly, false);
    assert.equal(parsed.isBounceable, false);
    assert.equal(parsed.address.equals(sample), true);
  });
});

describe("validateMainnetTransfer", () => {
  const destination = sample.toString({
    urlSafe: true,
    bounceable: false,
    testOnly: false,
  });

  it("builds a mainnet transfer with a text comment", () => {
    const result = validateMainnetTransfer({
      destination,
      amountTon: "1.25",
      comment: "  Rent  ",
      fromRaw: sample.toRawString(),
      nowSeconds: 1_700_000_000,
    });

    assert.equal(result.ok, true);
    if (!result.ok) return;

    assert.equal(result.request.network, TON_MAINNET_CHAIN);
    assert.equal(result.request.validUntil, 1_700_000_600);
    assert.equal(result.request.from, sample.toRawString());
    assert.equal(result.request.messages[0]?.address, destination);
    assert.equal(result.request.messages[0]?.amount, "1250000000");
    assert.equal(
      decodeTextComment(result.request.messages[0]?.payload ?? ""),
      "Rent",
    );
    assert.equal(Cell.fromBase64(result.request.messages[0]!.payload!).refs.length, 0);
  });

  it("omits the payload when the comment is blank", () => {
    const result = validateMainnetTransfer({
      destination,
      amountTon: "0.000000001",
      comment: "   ",
      nowSeconds: 10,
    });
    assert.equal(result.ok, true);
    if (!result.ok) return;
    assert.equal(result.request.messages[0]?.amount, "1");
    assert.equal("payload" in result.request.messages[0]!, false);
    assert.equal(result.request.from, undefined);
  });

  it("reports every invalid field", () => {
    const result = validateMainnetTransfer({
      destination: "not-an-address",
      amountTon: "0",
      comment: "x".repeat(400),
      fromRaw: "not-raw",
    });
    assert.equal(result.ok, false);
    if (result.ok) return;
    assert.match(result.errors.destination ?? "", /could not be read/);
    assert.match(result.errors.amount ?? "", /greater than zero/);
    assert.match(result.errors.comment ?? "", /too long/);
  });

  it("rejects amounts with more than 9 decimal places", () => {
    const result = validateMainnetTransfer({
      destination,
      amountTon: "1.1234567891",
      comment: "",
    });
    assert.equal(result.ok, false);
    if (result.ok) return;
    assert.match(result.errors.amount ?? "", /9 decimal places/);
  });
});

describe("send failures", () => {
  it("classifies wallet responses without treating an unknown outcome as safe to retry", () => {
    assert.equal(
      classifySendError({ name: "UserRejectsError" }),
      "cancelled",
    );
    assert.equal(
      classifySendError({ name: "WalletWrongNetworkError" }),
      "wrong-network",
    );
    assert.equal(classifySendError({ walletError: { code: 1 } }), "rejected");
    assert.equal(classifySendError(new Error("socket hang up")), "ambiguous");
    assert.match(sendFailureMessage("ambiguous"), /not sent twice/);
    assert.equal(
      connectFailureMessage("cancelled", "https://example.com/manifest.json"),
      null,
    );
    assert.match(
      connectFailureMessage(
        "manifest",
        "https://www.beigefield.com/tonconnect-manifest.json",
      ) ?? "",
      /tonconnect-manifest.json/,
    );
  });
});
