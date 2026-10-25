import "server-only";

import postgres from "postgres";
import { databaseCredentialFlags, resolveDatabaseUrl, type DatabaseEnv } from "./database-url";
import { safeDatabaseError } from "./errors";
import { isPublicIdentifier } from "./idents";

const SAMPLE_LIMIT = 8;
const MAX_TABLES = 40;
const MAX_CELL = 160;

export type CatalogCell = string | number | boolean | null;

export type PublicTableSnapshot = {
  name: string;
  rowCount: string | null;
  columns: string[];
  sample: CatalogCell[][];
  error: string | null;
};

export type PublicCatalog = {
  configured: boolean;
  tables: PublicTableSnapshot[];
  error: string | null;
};

function databaseEnv(): DatabaseEnv {
  return {
    DATABASE_URL: process.env.DATABASE_URL,
    SUPABASE_DB_PASSWORD: process.env.SUPABASE_DB_PASSWORD,
    SUPABASE_DB_USER: process.env.SUPABASE_DB_USER,
    SUPABASE_DB_NAME: process.env.SUPABASE_DB_NAME,
    SUPABASE_DB_PORT: process.env.SUPABASE_DB_PORT,
  };
}

function toCell(value: unknown): CatalogCell {
  if (value === null || value === undefined) return null;
  if (typeof value === "bigint") return value.toString();
  if (value instanceof Date) return value.toISOString();
  if (typeof value === "number" || typeof value === "boolean") return value;
  if (typeof value === "string") {
    return value.length > MAX_CELL ? `${value.slice(0, MAX_CELL)}…` : value;
  }
  try {
    const json = JSON.stringify(value);
    if (!json) return null;
    return json.length > MAX_CELL ? `${json.slice(0, MAX_CELL)}…` : json;
  } catch {
    return null;
  }
}

async function readTable(
  sql: ReturnType<typeof postgres>,
  name: string,
): Promise<PublicTableSnapshot> {
  if (!isPublicIdentifier(name)) {
    return {
      name: "skipped",
      rowCount: null,
      columns: [],
      sample: [],
      error: "Skipped a table with an unexpected name.",
    };
  }

  try {
    const columnRows = await sql<{ column_name: string }[]>`
      SELECT column_name
      FROM information_schema.columns
      WHERE table_schema = 'public' AND table_name = ${name}
      ORDER BY ordinal_position
    `;
    const columns = columnRows.map((row) => row.column_name).filter(isPublicIdentifier);
    const counted = await sql<{ count: string }[]>`
      SELECT count(*)::text AS count FROM public.${sql(name)}
    `;
    const orderColumn = columns.includes("created_at")
      ? "created_at"
      : columns.includes("id")
        ? "id"
        : null;

    let sample: CatalogCell[][] = [];
    if (columns.length > 0) {
      const rows = orderColumn
        ? await sql<Record<string, unknown>[]>`
            SELECT ${sql(columns)} FROM public.${sql(name)}
            ORDER BY ${sql(orderColumn)} DESC
            LIMIT ${SAMPLE_LIMIT}
          `
        : await sql<Record<string, unknown>[]>`
            SELECT ${sql(columns)} FROM public.${sql(name)}
            LIMIT ${SAMPLE_LIMIT}
          `;
      sample = rows.map((row) => columns.map((column) => toCell(row[column])));
    }

    return {
      name,
      rowCount: counted[0]?.count ?? null,
      columns,
      sample,
      error: null,
    };
  } catch (error) {
    return {
      name,
      rowCount: null,
      columns: [],
      sample: [],
      error: safeDatabaseError(error),
    };
  }
}

export async function loadPublicCatalog(): Promise<PublicCatalog> {
  const env = databaseEnv();
  const flags = databaseCredentialFlags(env);
  const url = resolveDatabaseUrl(env);
  if (!url || (!flags.hasDatabaseUrl && !flags.hasDbPassword)) {
    return { configured: false, tables: [], error: null };
  }

  const sql = postgres(url, {
    ssl: "require",
    max: 1,
    connect_timeout: 8,
    idle_timeout: 2,
    prepare: false,
    fetch_types: false,
    onnotice: () => {},
    connection: {
      statement_timeout: 8000,
    },
  });

  try {
    const tables = await sql<{ table_name: string }[]>`
      SELECT c.relname AS table_name
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
      WHERE n.nspname = 'public'
        AND c.relkind = 'r'
      ORDER BY c.relname
      LIMIT ${MAX_TABLES}
    `;

    const snapshots: PublicTableSnapshot[] = [];
    for (const table of tables) {
      snapshots.push(await readTable(sql, table.table_name));
    }
    return { configured: true, tables: snapshots, error: null };
  } catch (error) {
    return { configured: true, tables: [], error: safeDatabaseError(error) };
  } finally {
    await sql.end({ timeout: 2 }).catch(() => {});
  }
}
