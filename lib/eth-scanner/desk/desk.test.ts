import assert from "node:assert/strict";
import { test } from "node:test";
import { CORPORA, CORPUS_IDS, corpusUrl, crossReference, triageScore } from "./corpora";
import { ENGINE_IDS, ENGINES, PARSERS, engineCatalog, isEngineId } from "./engines";
import { classifyFinding, dedupeFindings, makeFinding, sanitizeEvidence, sortFindings } from "./findings";
import { finalizeFindings, parsePasted } from "./runtime";

test("every engine has metadata + parser + fork url", () => {
  assert.equal(ENGINE_IDS.length, 8);
  for (const id of ENGINE_IDS) {
    assert.ok(ENGINES[id].envBin.startsWith("ETH_SCANNER_"));
    assert.equal(typeof PARSERS[id], "function");
    for (const garbage of ["", "nope", "{", "null", "[1,2]"]) assert.deepEqual(PARSERS[id](garbage), []);
  }
  for (const e of engineCatalog()) assert.match(e.fork_url, /^https:\/\/github\.com\/shanecloonan\//);
  assert.ok(isEngineId("halmos"));
  assert.ok(!isEngineId("forge"));
});

test("slither json → normalized findings", () => {
  const out = PARSERS.slither(
    JSON.stringify({
      success: true,
      results: {
        detectors: [
          {
            check: "reentrancy-eth",
            impact: "High",
            confidence: "Medium",
            description: "Reentrancy in Vault.withdraw()",
            elements: [
              {
                type: "function",
                name: "withdraw",
                source_mapping: { filename_relative: "src/Vault.sol", lines: [42, 43] },
                type_specific_fields: { parent: { name: "Vault" } },
              },
            ],
          },
        ],
      },
    }),
  );
  assert.equal(out.length, 1);
  assert.equal(out[0].severity, "high");
  assert.equal(out[0].class, "reentrancy");
  assert.equal(out[0].location.line, 42);
  assert.equal(out[0].location.contract, "Vault");
  assert.equal(out[0].defensive_only, true);
});

test("aderyn buckets map to severity", () => {
  const out = PARSERS.aderyn(
    JSON.stringify({
      high_issues: { issues: [{ title: "Arbitrary from in transferFrom", detector_name: "arbitrary-transfer-from", description: "d", instances: [{ contract_path: "src/A.sol", line_no: 7 }] }] },
      low_issues: { issues: [{ title: "Unspecific pragma", detector_name: "unspecific-solidity-pragma", description: "d", instances: [] }] },
    }),
  );
  assert.deepEqual(out.map((f) => f.severity).sort(), ["high", "low"]);
});

test("mythril drops tx sequences", () => {
  const out = PARSERS.mythril(
    JSON.stringify({ issues: [{ "swc-id": "107", title: "External Call To User-Supplied Address", severity: "Medium", description: "call", tx_sequence: { steps: [{ input: "0xdeadbeef" }] } }] }),
  );
  assert.equal(out[0].rule, "SWC-107");
  assert.ok(!JSON.stringify(out).includes("deadbeef"));
});

test("fuzz / symbolic parsers only report failures", () => {
  const ech = PARSERS.echidna("echidna_share_solvency: failed!💥\n  Call sequence:\n    deposit(1)\necho_ok: passing");
  assert.equal(ech.length, 1);
  assert.equal(ech[0].class, "invariant-violation");
  assert.ok(!ech[0].evidence.includes("deposit(1)"));
  assert.equal(PARSERS.medusa("[FAILED] Property Test: VaultProperties.echidna_no_free_shares()\n[PASSED] Property Test: X.y()").length, 1);
  const hal = PARSERS.halmos(
    "Running 1 tests for test/V.t.sol:VaultConservation\n[PASS] check_a() (paths: 1)\n[FAIL] check_shareSolvency() (paths: 2)\nCounterexample: p_x = 0x01",
  );
  assert.equal(hal.length, 1);
  assert.equal(hal[0].location.contract, "VaultConservation");
  assert.ok(!hal[0].evidence.includes("0x01"));
  assert.equal(PARSERS.achecker("Contract is not vulnerable\nAccess control vulnerability found at pc: 0x1a").length, 1);
});

test("evidence sanitizer elides long hex and caps length", () => {
  const s = sanitizeEvidence(`payload 0x${"ab".repeat(80)} ${"x".repeat(2000)}`);
  assert.ok(!s.includes("abababab".repeat(8)));
  assert.ok(s.length <= 601);
});

test("classification + dedupe + sort", () => {
  assert.equal(classifyFinding("oracle price manipulation"), "oracle-manipulation");
  assert.equal(classifyFinding("delegatecall to untrusted"), "delegatecall-storage");
  const a = makeFinding({ engine: "slither", rule: "r", title: "t", severity: "low", confidence: "high", evidence: "e" });
  const b = makeFinding({ engine: "slither", rule: "r2", title: "t", severity: "critical", confidence: "high", evidence: "e" });
  const sorted = sortFindings(dedupeFindings([a, a, b]));
  assert.equal(sorted.length, 2);
  assert.equal(sorted[0].severity, "critical");
});

test("corpora: 8 forks, valid links, cross-reference + triage", () => {
  assert.equal(CORPUS_IDS.length, 8);
  for (const id of CORPUS_IDS) assert.match(CORPORA[id].fork, /^shanecloonan\//);
  assert.equal(
    corpusUrl(CORPORA["not-so-smart-contracts"], "variable shadowing"),
    "https://github.com/shanecloonan/not-so-smart-contracts/tree/master/variable%20shadowing",
  );
  const f = makeFinding({ engine: "slither", rule: "reentrancy-eth", title: "reentrancy", severity: "high", confidence: "medium", evidence: "e" });
  const [x] = crossReference([f]);
  assert.ok(x.references.length >= 3);
  assert.ok(x.references.every((r) => r.url.startsWith("https://github.com/shanecloonan/")));
  const t = triageScore(x);
  assert.ok(t > 0 && t <= 100);
});

test("location-less findings with different evidence are not collapsed by dedupe", () => {
  const a = makeFinding({ engine: "slither", rule: "r", title: "t", severity: "high", confidence: "high", evidence: "first issue" });
  const b = makeFinding({ engine: "slither", rule: "r", title: "t", severity: "high", confidence: "high", evidence: "second issue" });
  assert.notEqual(a.id, b.id);
  assert.equal(dedupeFindings([a, b, a]).length, 2);
});

test("finalizeFindings orders by severity, then triage within a severity", () => {
  const re = makeFinding({ engine: "slither", rule: "reentrancy-eth", title: "reentrancy", severity: "high", confidence: "medium", evidence: "x" });
  const send = makeFinding({ engine: "slither", rule: "arbitrary-send-eth", title: "arbitrary send of eth", severity: "high", confidence: "high", evidence: "y" });
  const low = makeFinding({ engine: "slither", rule: "naming", title: "naming", severity: "low", confidence: "high", evidence: "z" });
  const out = finalizeFindings([low, re, send]);
  assert.deepEqual(out.map((f) => f.severity), ["high", "high", "low"]);
  assert.ok(out[0].triage >= out[1].triage);
});

test("parsePasted: auto-detects wrong engine, warns on garbage, counts severities", () => {
  const slither = JSON.stringify({
    success: true,
    results: { detectors: [{ check: "reentrancy-eth", impact: "High", confidence: "Medium", description: "reentrancy in V.w()", elements: [] }] },
  });
  const ok = parsePasted("slither", slither);
  assert.equal(ok.findings.length, 1);
  assert.equal(ok.severity_counts.high, 1);
  assert.equal(ok.warning, null);
  const wrong = parsePasted("halmos", slither);
  assert.equal(wrong.detected, true);
  assert.equal(wrong.engine, "slither");
  assert.ok(wrong.warning);
  const junk = parsePasted("slither", "hello world");
  assert.equal(junk.findings.length, 0);
  assert.match(String(junk.warning), /not a clean result/);
});
