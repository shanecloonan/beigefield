import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { databaseCredentialFlags, resolveDatabaseUrl, SUPABASE_DB_HOST } from "./supabase/database-url";
import { safeDatabaseError } from "./supabase/errors";
import { formatTimestamp, rowCountLabel } from "./supabase/format";
import { isPublicIdentifier, quoteIdent } from "./supabase/idents";
import { normalizePing, pingNote } from "./supabase/ping";
import { resolveSupabasePublicEnv, supabaseUrlHost } from "./supabase/public-env";

describe("Supabase public env", () => {
  it("prefers the publishable key and falls back to the anon key", () => {
    const preferred = resolveSupabasePublicEnv({
      NEXT_PUBLIC_SUPABASE_URL: " https://soswwsvunulnhlcitpwl.supabase.co/rest/v1 ",
      NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: " sb_publishable_example ",
      NEXT_PUBLIC_SUPABASE_ANON_KEY: "anon-example",
    });
    assert.equal(preferred.keySource, "publishable");
    assert.equal(preferred.key, "sb_publishable_example");
    assert.equal(preferred.host, "soswwsvunulnhlcitpwl.supabase.co");
    assert.equal(preferred.hasPublishableKey, true);
    assert.equal(preferred.hasAnonKey, true);

    const fallback = resolveSupabasePublicEnv({
      NEXT_PUBLIC_SUPABASE_URL: "https://soswwsvunulnhlcitpwl.supabase.co",
      NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: " ",
      NEXT_PUBLIC_SUPABASE_ANON_KEY: "anon-example",
    });
    assert.equal(fallback.keySource, "anon");
    assert.equal(fallback.key, "anon-example");

    const missing = resolveSupabasePublicEnv({});
    assert.equal(missing.keySource, "missing");
    assert.equal(missing.key, "");
    assert.equal(missing.host, null);
    assert.equal(missing.hasUrl, false);
  });

  it("keeps credentials out of the displayed host", () => {
    assert.equal(
      supabaseUrlHost("https://user:super-secret@soswwsvunulnhlcitpwl.supabase.co/path?token=abc"),
      "soswwsvunulnhlcitpwl.supabase.co",
    );
    assert.equal(supabaseUrlHost("not a url"), null);
  });
});

describe("database URL", () => {
  it("prefers DATABASE_URL and otherwise builds a direct connection", () => {
    const flags = databaseCredentialFlags({
      DATABASE_URL: "postgresql://postgres:secret@example.supabase.co:5432/postgres",
      SUPABASE_DB_PASSWORD: "other",
    });
    assert.deepEqual(flags, { hasDatabaseUrl: true, hasDbPassword: true });
    assert.equal(
      resolveDatabaseUrl({
        DATABASE_URL: " postgresql://example ",
        SUPABASE_DB_PASSWORD: "other",
      }),
      "postgresql://example",
    );

    const built = resolveDatabaseUrl({
      SUPABASE_DB_PASSWORD: "p@ss word/#",
      SUPABASE_DB_USER: "postgres",
    });
    assert.equal(
      built,
      `postgresql://postgres:p%40ss%20word%2F%23@${SUPABASE_DB_HOST}:5432/postgres?sslmode=require`,
    );
    assert.equal(resolveDatabaseUrl({}), null);
    assert.equal(resolveDatabaseUrl({ SUPABASE_DB_PASSWORD: "secret", SUPABASE_DB_PORT: "5432;drop" }), null);
  });

  it("reports a failure code without the driver message", () => {
    const error = new Error("connect postgresql://postgres:secret@db.example/postgres failed");
    (error as Error & { code: string }).code = "CONNECT_TIMEOUT";
    const text = safeDatabaseError(error);
    assert.equal(text, "Database query failed (CONNECT_TIMEOUT).");
    assert.equal(text.includes("secret"), false);
    assert.equal(safeDatabaseError(new Error("nope")), "Database query failed.");
  });
});

describe("ping notes and identifiers", () => {
  it("uses the trimmed note or a timestamp", () => {
    const now = new Date("2026-10-25T01:02:03.000Z");
    assert.equal(pingNote("  hello  ", now), "hello");
    assert.equal(pingNote("   ", now), "2026-10-25T01:02:03.000Z");
    assert.equal(pingNote("x".repeat(600), now).length, 500);
  });

  it("normalizes a ping row and quotes only plain identifiers", () => {
    assert.deepEqual(normalizePing({ id: 4, note: null, created_at: "2026-10-25T01:02:03.000Z" }), {
      id: "4",
      note: null,
      created_at: "2026-10-25T01:02:03.000Z",
    });
    assert.equal(normalizePing({ id: "9", note: "hi", created_at: "2026-10-25T01:02:03.000Z" })?.id, "9");
    assert.equal(normalizePing({ id: 1, note: 2, created_at: "2026-10-25T01:02:03.000Z" }), null);
    assert.equal(isPublicIdentifier("ping_tests"), true);
    assert.equal(isPublicIdentifier('ping_tests"; drop'), false);
    assert.equal(quoteIdent("ping_tests"), '"ping_tests"');
    assert.throws(() => quoteIdent("ping_tests;drop"));
    assert.equal(formatTimestamp("2026-10-25T01:02:03.000Z"), "2026-10-25 01:02:03 UTC");
    assert.equal(rowCountLabel("1"), "1 row");
    assert.equal(rowCountLabel("2"), "2 rows");
  });
});
