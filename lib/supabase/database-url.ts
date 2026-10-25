/** Direct Postgres host for the beigefield project. Not a credential. */
export const SUPABASE_DB_HOST = "db.soswwsvunulnhlcitpwl.supabase.co";

export type DatabaseEnv = {
  DATABASE_URL?: string;
  SUPABASE_DB_PASSWORD?: string;
  SUPABASE_DB_USER?: string;
  SUPABASE_DB_NAME?: string;
  SUPABASE_DB_PORT?: string;
};

export type DatabaseCredentialFlags = {
  hasDatabaseUrl: boolean;
  hasDbPassword: boolean;
};

function trimmed(value: string | undefined): string {
  return value?.trim() ?? "";
}

export function databaseCredentialFlags(env: DatabaseEnv): DatabaseCredentialFlags {
  return {
    hasDatabaseUrl: Boolean(trimmed(env.DATABASE_URL)),
    hasDbPassword: Boolean(trimmed(env.SUPABASE_DB_PASSWORD)),
  };
}

/**
 * Prefer `DATABASE_URL`. Otherwise build a direct connection from
 * `SUPABASE_DB_PASSWORD`. Returns null when neither is set.
 * Callers must not log or render the result.
 */
export function resolveDatabaseUrl(env: DatabaseEnv): string | null {
  const databaseUrl = trimmed(env.DATABASE_URL);
  if (databaseUrl) return databaseUrl;

  const password = trimmed(env.SUPABASE_DB_PASSWORD);
  if (!password) return null;

  const user = trimmed(env.SUPABASE_DB_USER) || "postgres";
  const database = trimmed(env.SUPABASE_DB_NAME) || "postgres";
  const port = trimmed(env.SUPABASE_DB_PORT) || "5432";
  if (!/^\d{2,5}$/.test(port)) return null;

  const auth = `${encodeURIComponent(user)}:${encodeURIComponent(password)}`;
  return `postgresql://${auth}@${SUPABASE_DB_HOST}:${port}/${encodeURIComponent(database)}?sslmode=require`;
}
