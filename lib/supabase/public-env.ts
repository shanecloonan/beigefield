export type SupabaseKeySource = "publishable" | "anon" | "missing";

export type SupabasePublicInput = {
  NEXT_PUBLIC_SUPABASE_URL?: string;
  NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY?: string;
  NEXT_PUBLIC_SUPABASE_ANON_KEY?: string;
};

export type SupabasePublicEnv = {
  url: string;
  host: string | null;
  key: string;
  keySource: SupabaseKeySource;
  hasUrl: boolean;
  hasPublishableKey: boolean;
  hasAnonKey: boolean;
};

function trimmed(value: string | undefined): string {
  return value?.trim() ?? "";
}

/** Hostname only. Credentials, paths, and query strings stay out of the UI. */
export function supabaseUrlHost(url: string): string | null {
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== "https:" && parsed.protocol !== "http:") return null;
    return parsed.host || null;
  } catch {
    return null;
  }
}

export function resolveSupabasePublicEnv(env: SupabasePublicInput): SupabasePublicEnv {
  const url = trimmed(env.NEXT_PUBLIC_SUPABASE_URL);
  const publishable = trimmed(env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY);
  const anon = trimmed(env.NEXT_PUBLIC_SUPABASE_ANON_KEY);
  const key = publishable || anon;
  const keySource: SupabaseKeySource = publishable ? "publishable" : anon ? "anon" : "missing";

  return {
    url,
    host: url ? supabaseUrlHost(url) : null,
    key,
    keySource,
    hasUrl: Boolean(url),
    hasPublishableKey: Boolean(publishable),
    hasAnonKey: Boolean(anon),
  };
}

/**
 * Static `process.env.NEXT_PUBLIC_*` reads so Next can inline them for the browser.
 * Dynamic lookups are not inlined and would be empty on the client.
 */
export function readSupabasePublicEnv(): SupabasePublicEnv {
  return resolveSupabasePublicEnv({
    NEXT_PUBLIC_SUPABASE_URL: process.env.NEXT_PUBLIC_SUPABASE_URL,
    NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY,
    NEXT_PUBLIC_SUPABASE_ANON_KEY: process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY,
  });
}
