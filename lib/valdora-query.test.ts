import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { VALDORA_STAKER } from "./valdora";
import {
  loadZigPathDefaults,
  parseDefaultId,
  pickCompletedId,
  pickCompletedIdFromTxs,
} from "./valdora-query";

const desk = "zig1gy5zketezrfdea9g80we02663r2gjz3z0002kx";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function queryKey(url: string): string | null {
  const marker = "/smart/";
  const at = url.indexOf(marker);
  if (at < 0) return null;
  const encoded = decodeURIComponent(url.slice(at + marker.length));
  const query = JSON.parse(Buffer.from(encoded, "base64").toString("utf8")) as Record<string, unknown>;
  return Object.keys(query)[0] ?? null;
}

function lcd(data: Record<string, unknown>, txs: unknown = { tx_responses: [] }): typeof fetch {
  return async (input) => {
    const url = String(input);
    if (url.includes("/smart/")) {
      const key = queryKey(url);
      if (!key || !(key in data)) return json({ message: "missing" }, 500);
      return json({ data: data[key] });
    }
    if (url.includes("/cosmos/tx/v1beta1/txs")) return json(txs);
    return json({ message: "missing" }, 404);
  };
}

const base = {
  total_completed_unbondings: { total_count: 54, total_amount: "1" },
  paused: { paused: false },
  protocol_info: { token_name: "stzig" },
};

describe("completed id pickers", () => {
  it("keeps the greatest completed id and ignores already executed withdraws", () => {
    assert.equal(pickCompletedId([{ id: 2 }, { id: 12 }, { id: -1 }, { id: "nope" }]), 12);
    assert.equal(parseDefaultId(" 7 "), 7);
    assert.equal(parseDefaultId("1.5"), null);
    assert.equal(
      pickCompletedIdFromTxs({
        tx_responses: [
          {
            events: [
              {
                type: "wasm",
                attributes: [
                  { key: "method", value: "withdraw_unbonded_by_id" },
                  { key: "id", value: "99" },
                ],
              },
              {
                type: "wasm",
                attributes: [
                  { key: "method", value: "collect_unbonded_amounts" },
                  { key: "completed_unbonding_id", value: "15" },
                ],
              },
            ],
          },
        ],
      }),
      15,
    );
  });
});

describe("loadZigPathDefaults", () => {
  it("suggests the owner's highest completed unbonding", async () => {
    const result = await loadZigPathDefaults(
      { owner: desk },
      {
        defaultId: "3",
        fetchImpl: lcd({
          ...base,
          completed_unbondings: {
            address: desk,
            completed_unbondings: [
              { id: 2, withdrawal_id: 1 },
              { id: 12, withdrawal_id: 11 },
            ],
          },
        }),
      },
    );
    assert.equal(result.ok, true);
    if (!result.ok) return;
    assert.equal(result.staker, VALDORA_STAKER);
    assert.equal(result.paused, false);
    assert.equal(result.total_count, 54);
    assert.equal(result.suggested_id, 12);
    assert.equal(result.owner, desk);
    assert.equal(result.token_name, "stzig");
  });

  it("falls back to VALDORA_DEFAULT_ID and then tx attributes", async () => {
    const fromEnv = await loadZigPathDefaults(
      { owner: desk },
      {
        defaultId: "7",
        fetchImpl: lcd({
          ...base,
          completed_unbondings: { address: desk, completed_unbondings: [] },
        }),
      },
    );
    assert.equal(fromEnv.ok, true);
    if (!fromEnv.ok) return;
    assert.equal(fromEnv.suggested_id, 7);

    const fromTx = await loadZigPathDefaults(
      { owner: "" },
      {
        defaultId: null,
        fetchImpl: lcd(base, {
          tx_responses: [
            {
              events: [
                {
                  type: "wasm",
                  attributes: [
                    { key: "method", value: "collect_unbonded_amounts" },
                    { key: "id", value: "21" },
                  ],
                },
              ],
            },
          ],
        }),
      },
    );
    assert.equal(fromTx.ok, true);
    if (!fromTx.ok) return;
    assert.equal(fromTx.suggested_id, 21);
    assert.equal(fromTx.owner, "");
  });

  it("rejects a bad owner and reports an LCD that does not answer", async () => {
    let called = false;
    const bad = await loadZigPathDefaults(
      { owner: "not-an-address" },
      {
        fetchImpl: async () => {
          called = true;
          return json({});
        },
      },
    );
    assert.equal(called, false);
    assert.deepEqual(bad, { ok: false, status: 400, message: "Enter a zig1 address." });

    const down = await loadZigPathDefaults(
      { owner: desk },
      {
        defaultId: null,
        searchTxs: false,
        fetchImpl: async () => {
          throw new Error("offline");
        },
      },
    );
    assert.equal(down.ok, false);
    if (!down.ok) assert.equal(down.status, 502);
  });
});
