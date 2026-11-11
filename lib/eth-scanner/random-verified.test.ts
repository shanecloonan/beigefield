import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  EtherscanSampleError,
  SAMPLE_NOTE,
  sampleErrorStatus,
  sampleVerifiedContract,
} from "./random-verified";

const ADDR_A = "0x" + "ab".repeat(20);
const ADDR_B = "0x" + "cd".repeat(20);
const ADDR_C = "0x" + "11".repeat(20);

function block(hex = "0x180000") {
  return { jsonrpc: "2.0", id: 1, result: hex };
}

function logs(addresses: string[]) {
  return {
    status: "1",
    message: "OK",
    result: addresses.map((address) => ({ address, topics: [], data: "0x" })),
  };
}

function unverified() {
  return {
    status: "1",
    message: "OK",
    result: [{ SourceCode: "", ABI: "Contract source code not verified", ContractName: "" }],
  };
}

function verified(name: string) {
  return {
    status: "1",
    message: "OK",
    result: [{ SourceCode: `contract ${name} {}`, ABI: "[]", ContractName: name, CompilerVersion: "v0.8.24" }],
  };
}

function scripted(responses: { status?: number; body?: unknown; throwMsg?: string }[]) {
  const calls: string[] = [];
  let i = 0;
  const fetchImpl: typeof fetch = async (input) => {
    const url = String(input);
    calls.push(url);
    const spec = responses[i++];
    if (!spec) throw new Error(`unexpected fetch #${calls.length}`);
    if (spec.throwMsg) throw new Error(spec.throwMsg);
    return new Response(JSON.stringify(spec.body ?? {}), { status: spec.status ?? 200 });
  };
  return { fetchImpl, calls, sent: () => i };
}

const quiet = {
  keys: "test-key",
  minIntervalMs: 0,
  sleep: async () => {},
  now: () => 1_000,
  rng: () => 0.999999,
};

describe("sampleVerifiedContract", () => {
  it("returns the first verified Transfer emitter and stops", async () => {
    const { fetchImpl, calls } = scripted([
      { body: block() },
      { body: logs([ADDR_A, ADDR_B]) },
      { body: unverified() },
      { body: verified("FooVault") },
      { body: verified("ShouldNotFetch") },
    ]);
    const out = await sampleVerifiedContract({ ...quiet, fetch: fetchImpl, maxSourceChecks: 4, maxBlocks: 2 });
    assert.equal(out.address, ADDR_B);
    assert.equal(out.contract_name, "FooVault");
    assert.equal(out.compiler, "v0.8.24");
    assert.equal(out.strategy, "transfer-log-sample");
    assert.equal(out.source_checks, 2);
    assert.equal(out.blocks_tried, 1);
    assert.equal(out.note, SAMPLE_NOTE);
    assert.equal(calls.length, 4);
    assert.match(calls[0]!, /module=proxy/);
    assert.match(calls[0]!, /chainid=1/);
    assert.match(calls[1]!, /action=getLogs/);
    assert.match(calls[1]!, /topic0=0xddf252ad/);
    assert.match(calls[3]!, new RegExp(`address=${ADDR_B}`));
    assert.equal(calls.some((u) => u.includes("apikey=test-key")), true);
  });

  it("caps source checks and does not keep walking blocks", async () => {
    const { fetchImpl, calls } = scripted([
      { body: block() },
      { body: logs([ADDR_A, ADDR_B, ADDR_C]) },
      { body: unverified() },
      { body: unverified() },
      { body: verified("Nope") },
    ]);
    await assert.rejects(
      () => sampleVerifiedContract({ ...quiet, fetch: fetchImpl, maxSourceChecks: 2, maxBlocks: 1 }),
      (err: unknown) => err instanceof EtherscanSampleError && err.kind === "none",
    );
    const sourceCalls = calls.filter((u) => u.includes("action=getsourcecode"));
    assert.equal(sourceCalls.length, 2);
  });

  it("tries a second block when the first has no Transfer logs", async () => {
    const { fetchImpl, calls } = scripted([
      { body: block() },
      { body: { status: "0", message: "No records found", result: [] } },
      { body: logs([ADDR_A]) },
      { body: verified("SecondBlock") },
    ]);
    const out = await sampleVerifiedContract({ ...quiet, fetch: fetchImpl, maxBlocks: 2 });
    assert.equal(out.contract_name, "SecondBlock");
    assert.equal(out.blocks_tried, 2);
    assert.equal(calls.filter((u) => u.includes("action=getLogs")).length, 2);
  });

  it("stops after a single rate-limit retry and names the limit", async () => {
    const { fetchImpl, calls } = scripted([
      { status: 429, body: { status: "0", message: "NOTOK", result: "Max rate limit reached" } },
      { status: 429, body: { status: "0", message: "NOTOK", result: "Max rate limit reached" } },
      { body: block() },
    ]);
    await assert.rejects(
      () => sampleVerifiedContract({ ...quiet, fetch: fetchImpl }),
      (err: unknown) => {
        assert.ok(err instanceof EtherscanSampleError);
        assert.equal(err.kind, "rate_limit");
        assert.match(err.message, /rate limit reached/i);
        assert.match(err.message, /nothing was scanned/i);
        assert.equal(err.message.includes("test-key"), false);
        return true;
      },
    );
    assert.equal(calls.length, 2);
    assert.equal(sampleErrorStatus(new EtherscanSampleError("rate_limit", "x")), 429);
    assert.equal(sampleErrorStatus(new EtherscanSampleError("none", "x")), 404);
  });

  it("does not treat a rate-limit sentence inside real source as unverified-or-limited", async () => {
    const { fetchImpl } = scripted([
      { body: block() },
      { body: logs([ADDR_A]) },
      {
        body: {
          status: "1",
          message: "OK",
          result: [{
            SourceCode: "contract Foo { // rate limit is a comment in a long source " + "x".repeat(200) + " }",
            ABI: "[]",
            ContractName: "Foo",
            CompilerVersion: "v0.8.19",
          }],
        },
      },
    ]);
    const out = await sampleVerifiedContract({ ...quiet, fetch: fetchImpl });
    assert.equal(out.address, ADDR_A);
    assert.equal(out.contract_name, "Foo");
  });

  it("redacts the API key when the request throws", async () => {
    const secret = "SUPERSECRETKEY";
    const { fetchImpl } = scripted([
      { throwMsg: `connect ECONNRESET https://api.etherscan.io/v2/api?apikey=${secret}&module=proxy` },
    ]);
    await assert.rejects(
      () => sampleVerifiedContract({ ...quiet, keys: secret, fetch: fetchImpl }),
      (err: unknown) => {
        assert.ok(err instanceof EtherscanSampleError);
        assert.equal(err.kind, "unavailable");
        assert.equal(err.message.includes(secret), false);
        assert.match(err.message, /apikey=\[redacted\]/);
        return true;
      },
    );
  });

  it("surfaces a log query timeout instead of claiming nothing was verified", async () => {
    const { fetchImpl, calls } = scripted([
      { body: block() },
      { body: { status: "0", message: "NOTOK", result: "Query Timeout occured. Please select a smaller result dataset" } },
      { body: logs([ADDR_A]) },
    ]);
    await assert.rejects(
      () => sampleVerifiedContract({ ...quiet, fetch: fetchImpl }),
      (err: unknown) => {
        assert.ok(err instanceof EtherscanSampleError);
        assert.equal(err.kind, "unavailable");
        assert.match(err.message, /Timeout/i);
        assert.equal(err.message.includes("test-key"), false);
        return true;
      },
    );
    assert.equal(calls.filter((u) => u.includes("action=getLogs")).length, 1);
  });

  it("rejects an empty key list before any request", async () => {
    let called = false;
    const fetchImpl: typeof fetch = async () => {
      called = true;
      return new Response("{}", { status: 200 });
    };
    await assert.rejects(
      () => sampleVerifiedContract({ ...quiet, keys: " , ", fetch: fetchImpl }),
      (err: unknown) => err instanceof EtherscanSampleError && err.kind === "config",
    );
    assert.equal(called, false);
  });
});
