import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { VALDORA_STAKER } from "./valdora";
import { compilePathRun, pathLookupNote, readZigPathDefaults, readZigSendResult } from "./valdora-path-run";

const desk = "zig1gy5zketezrfdea9g80we02663r2gjz3z0002kx";

describe("compilePathRun", () => {
  it("builds one withdraw_unbonded_by_id execute", () => {
    const compiled = compilePathRun({ id: 12, sender: desk, memo: "path" });
    assert.equal(compiled.ok, true);
    if (!compiled.ok) return;
    assert.equal(compiled.messages.length, 1);
    assert.equal(compiled.memo, "path");
    const message = compiled.messages[0];
    assert.equal(message?.typeUrl, "/cosmwasm.wasm.v1.MsgExecuteContract");
    assert.deepEqual(message?.value, {
      sender: desk,
      contract: VALDORA_STAKER,
      msg: { withdraw_unbonded_by_id: { id: 12 } },
      funds: [],
    });
    assert.equal(compiled.preview.sender, desk);
    assert.match(compiled.summary, /withdraw_unbonded_by_id id 12/);
  });

  it("rejects a missing or non-integer id and a bad sender", () => {
    for (const id of [-1, 1.5, Number.NaN, Number.POSITIVE_INFINITY, Number.MAX_SAFE_INTEGER + 1]) {
      const compiled = compilePathRun({ id, sender: desk });
      assert.equal(compiled.ok, false, String(id));
      if (!compiled.ok) assert.match(compiled.message, /Nothing was sent/);
    }
    const sender = compilePathRun({ id: 1, sender: "UQDXQTZUmyd5KRoP3cvjXfXOtx6FIZYOAtwXHEu2TY7WTorY" });
    assert.equal(sender.ok, false);
    const memo = compilePathRun({ id: 1, sender: desk, memo: "line\nbreak" });
    assert.equal(memo.ok, false);
  });
});

describe("path lookup note", () => {
  it("names the LCD fields", () => {
    assert.equal(
      pathLookupNote({ paused: false, total_count: 54, suggested_id: 12, token_name: "stzig" }),
      "LCD paused=false total_count=54 suggested_id=12 token=stzig.",
    );
    assert.equal(
      pathLookupNote({ paused: true, total_count: 0, suggested_id: null }),
      "LCD paused=true total_count=0 suggested_id=none.",
    );
  });
});

describe("zig reply readers", () => {
  it("reads a broadcast and a defaults payload", () => {
    const hash = "ab".repeat(32);
    assert.deepEqual(readZigSendResult({ ok: true, txHash: hash, height: 10 }), {
      ok: true,
      txHash: hash,
      height: 10,
    });
    assert.deepEqual(readZigSendResult({ ok: false, kind: "ambiguous", message: "Check the account." }), {
      ok: false,
      text: "Check the account.",
    });
    assert.equal(readZigSendResult({ ok: true, txHash: "zz", height: 1 }), null);
    assert.equal(readZigPathDefaults(null), null);
    const defaults = readZigPathDefaults({
      ok: true,
      staker: VALDORA_STAKER,
      paused: false,
      total_count: 54,
      suggested_id: 12,
      owner: desk,
      token_name: "stzig",
    });
    assert.equal(defaults?.ok, true);
    if (!defaults || !defaults.ok) return;
    assert.equal(defaults.suggested_id, 12);
    assert.equal(readZigPathDefaults({ ok: false, message: "Enter a zig1 address." })?.ok, false);
  });
});
