import type { Metadata } from "next";
import Link from "next/link";
import { connection } from "next/server";
import { CatalogList } from "@/components/supabase/catalog-list";
import { PingDesk } from "@/components/supabase/ping-desk";
import { loadPublicCatalog } from "@/lib/supabase/catalog";
import { databaseCredentialFlags } from "@/lib/supabase/database-url";
import { fetchPingTests } from "@/lib/supabase/ping";
import { readSupabasePublicEnv, type SupabaseKeySource } from "@/lib/supabase/public-env";
import { site } from "@/lib/site";

const title = `Supabase — ${site.name}`;
const description =
  "Connection status for the Beigefield Supabase project, the public tables, and a note written to ping_tests.";

export const metadata: Metadata = {
  title,
  description,
  alternates: {
    canonical: "/supabase",
  },
  openGraph: {
    title,
    description,
    url: `${site.url}/supabase`,
  },
  twitter: {
    card: "summary_large_image",
    title,
    description,
  },
};

export const runtime = "nodejs";

function presence(set: boolean): string {
  return set ? "Present" : "Missing";
}

function keyLabel(source: SupabaseKeySource): string {
  if (source === "publishable") return "Publishable key";
  if (source === "anon") return "Anon key";
  return "Missing";
}

export default async function SupabasePage() {
  await connection();

  const publicEnv = readSupabasePublicEnv();
  const credentials = databaseCredentialFlags({
    DATABASE_URL: process.env.DATABASE_URL,
    SUPABASE_DB_PASSWORD: process.env.SUPABASE_DB_PASSWORD,
  });
  const [catalog, pings] = await Promise.all([loadPublicCatalog(), fetchPingTests()]);

  return (
    <div className="page">
      <div className="frame" aria-hidden="true">
        <span className="corner corner-tl" />
        <span className="corner corner-tr" />
        <span className="corner corner-bl" />
        <span className="corner corner-br" />
      </div>
      <main className="ton-main">
        <Link className="ton-mark" href="/">
          Beigefield
        </Link>
        <p className="ton-kicker">Database</p>
        <h1>Supabase</h1>
        <p className="ton-lede">
          The Beigefield project: which keys are configured, the tables in{" "}
          <span className="ton-mono">public</span>, and a note you can write to{" "}
          <span className="ton-mono">ping_tests</span>.
        </p>
        <nav className="ton-contents" aria-label="On this page">
          <a href="#connection">Connection</a>
          <a href="#tables">Tables</a>
          <a href="#ping">Ping test</a>
        </nav>

        <section className="ton-section" id="connection" aria-labelledby="connection-title">
          <h2 id="connection-title">Connection</h2>
          <dl className="ton-where">
            <div>
              <dt>API host</dt>
              <dd className="ton-mono">{publicEnv.host ?? "Not set"}</dd>
            </div>
            <div>
              <dt>Project URL</dt>
              <dd>{presence(publicEnv.hasUrl)}</dd>
            </div>
            <div>
              <dt>Publishable key</dt>
              <dd>{presence(publicEnv.hasPublishableKey)}</dd>
            </div>
            <div>
              <dt>Anon key</dt>
              <dd>{presence(publicEnv.hasAnonKey)}</dd>
            </div>
            <div>
              <dt>Client key</dt>
              <dd>{keyLabel(publicEnv.keySource)}</dd>
            </div>
            <div>
              <dt>Database URL</dt>
              <dd>{presence(credentials.hasDatabaseUrl)}</dd>
            </div>
            <div>
              <dt>Database password</dt>
              <dd>{presence(credentials.hasDbPassword)}</dd>
            </div>
          </dl>
        </section>

        <section className="ton-section" id="tables" aria-labelledby="tables-title">
          <h2 id="tables-title">Public tables</h2>
          <p className="ton-section-copy">
            Names, counts, and a few recent rows are read on the server when a
            database URL or password is configured. Those values are not sent to
            the browser as credentials.
          </p>
          <CatalogList catalog={catalog} />
        </section>

        <section className="ton-section" id="ping" aria-labelledby="ping-title">
          <h2 id="ping-title">Ping test</h2>
          <p className="ton-section-copy">
            Inserts a row into <span className="ton-mono">ping_tests</span> with
            the public key. Row level security allows that insert and the read
            that follows.
          </p>
          <PingDesk
            initialRows={pings.rows}
            initialError={pings.error}
            canWrite={publicEnv.keySource !== "missing" && publicEnv.hasUrl}
          />
        </section>
      </main>
    </div>
  );
}
