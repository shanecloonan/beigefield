import assert from "node:assert/strict";
import { afterEach, describe, it } from "node:test";
import {
  buildDedupeKey,
  enginesPersistInput,
  laneAPersistInput,
  researchPersistInput,
  TRIAGE_STATUSES,
} from "./persist-test-results";
import { resolveServiceSupabaseEnv, serviceSupabaseConfigured } from "./service-supabase";

const saved = {
  ETH_SCANNER_SUPABASE_URL: process.env.ETH_SCANNER_SUPABASE_URL,
  SUPABASE_URL: process.env.SUPABASE_URL,
  NEXT_PUBLIC_SUPABASE_URL: process.env.NEXT_PUBLIC_SUPABASE_URL,
  SUPABASE_SERVICE_ROLE_KEY: process.env.SUPABASE_SERVICE_ROLE_KEY,
  SUPABASE_SECRET_KEY: process.env.SUPABASE_SECRET_KEY,
};

afterEach(() => {
  for (const [k, v] of Object.entries(saved)) {
    if (v == null) delete process.env[k];
    else process.env[k] = v;
  }
});

describe("service supabase env resolution", () => {
  it("prefers ETH_SCANNER_SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY", () => {
    process.env.ETH_SCANNER_SUPABASE_URL = "https://scanner.example.co/";
    process.env.SUPABASE_URL = "https://fallback.example.co";
    process.env.NEXT_PUBLIC_SUPABASE_URL = "https://public.example.co";
    process.env.SUPABASE_SERVICE_ROLE_KEY = "service-role";
    process.env.SUPABASE_SECRET_KEY = "secret-key";
    const resolved = resolveServiceSupabaseEnv();
    assert.equal(resolved.url, "https://scanner.example.co");
    assert.equal(resolved.urlSource, "ETH_SCANNER_SUPABASE_URL");
    assert.equal(resolved.key, "service-role");
    assert.equal(resolved.keySource, "SUPABASE_SERVICE_ROLE_KEY");
    assert.equal(serviceSupabaseConfigured(), true);
  });

  it("falls back to NEXT_PUBLIC_SUPABASE_URL and SUPABASE_SECRET_KEY", () => {
    delete process.env.ETH_SCANNER_SUPABASE_URL;
    delete process.env.SUPABASE_URL;
    delete process.env.SUPABASE_SERVICE_ROLE_KEY;
    process.env.NEXT_PUBLIC_SUPABASE_URL = "https://soswwsvunulnhlcitpwl.supabase.co";
    process.env.SUPABASE_SECRET_KEY = "secret-key";
    const resolved = resolveServiceSupabaseEnv();
    assert.equal(resolved.urlSource, "NEXT_PUBLIC_SUPABASE_URL");
    assert.equal(resolved.keySource, "SUPABASE_SECRET_KEY");
    assert.equal(serviceSupabaseConfigured(), true);
  });

  it("reports missing when neither URL nor key is set", () => {
    delete process.env.ETH_SCANNER_SUPABASE_URL;
    delete process.env.SUPABASE_URL;
    delete process.env.NEXT_PUBLIC_SUPABASE_URL;
    delete process.env.SUPABASE_SERVICE_ROLE_KEY;
    delete process.env.SUPABASE_SECRET_KEY;
    assert.equal(serviceSupabaseConfigured(), false);
  });
});

describe("persist payload mappers", () => {
  it("builds a stable dedupe key for identical lane-a payloads", () => {
    const input = laneAPersistInput({
      result: {
        address: "0x1111111111111111111111111111111111111111",
        bucket: "lane-a-cool",
        dropped: false,
        drop_reason: null,
        heat: 0,
        src_confidence: "high",
        ir_confidence: "high",
        value_movers: [],
        contract_class: "vault",
        scope: "in-scope",
        notes: ["ok"],
      },
      fixture: "gated_vault",
      duration_ms: 12,
      receipt_filename: "receipt.md",
    });
    const a = buildDedupeKey(input);
    const b = buildDedupeKey(input);
    assert.equal(a, b);
    assert.match(a, /^[a-f0-9]{64}$/);
  });

  it("maps research findings into persist rows", () => {
    const input = researchPersistInput({
      result: {
        address: "0x2222222222222222222222222222222222222222",
        gated: false,
        gate_reason: "",
        role: "vault",
        scope: "in-scope",
        layers_run: ["L0"],
        layers_skipped: [],
        findings: [
          {
            id: "f1",
            severity: "high",
            layer: "L1",
            title: "share inflation",
            evidence: "deposit path",
            address: "0x2222222222222222222222222222222222222222",
            detector: "erc4626",
            defensive_only: true,
          },
        ],
        notes: [],
      },
      fixture: "erc4626_vault",
    });
    assert.equal(input.kind, "research");
    assert.equal(input.findings?.length, 1);
    assert.equal(input.findings?.[0].finding_key, "f1");
  });

  it("maps engine findings with triage scores", () => {
    const input = enginesPersistInput({
      mode: "engines-paste",
      engine: "slither",
      findings: [
        {
          id: "slither:reentrancy:a.sol:10",
          engine: "slither",
          rule: "reentrancy-eth",
          title: "reentrancy",
          severity: "high",
          confidence: "medium",
          class: "reentrancy",
          triage: 72,
          evidence: "external call before state update",
          defensive_only: true,
        },
      ],
      severity_counts: { high: 1 },
      raw: { ok: true },
    });
    assert.equal(input.kind, "engines-paste");
    assert.equal(input.findings?.[0].triage_score, 72);
    assert.equal(input.findings?.[0].funds_at_risk_class, "reentrancy");
  });

  it("exposes triage statuses used by the API", () => {
    assert.ok(TRIAGE_STATUSES.includes("open"));
    assert.ok(TRIAGE_STATUSES.includes("human_yes"));
  });
});
