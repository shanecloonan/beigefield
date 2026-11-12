/**
 * Server-only Supabase client for /test desk persistence.
 * Never import from client components. Never log secret values.
 *
 * URL (first non-empty wins):
 *   ETH_SCANNER_SUPABASE_URL | SUPABASE_URL | NEXT_PUBLIC_SUPABASE_URL
 *
 * Service key (first non-empty wins):
 *   SUPABASE_SERVICE_ROLE_KEY | SUPABASE_SECRET_KEY
 */

import { createClient, type SupabaseClient } from "@supabase/supabase-js";

export type ServiceSupabaseEnv = {
  url: string;
  key: string;
  urlSource: "ETH_SCANNER_SUPABASE_URL" | "SUPABASE_URL" | "NEXT_PUBLIC_SUPABASE_URL" | "missing";
  keySource: "SUPABASE_SERVICE_ROLE_KEY" | "SUPABASE_SECRET_KEY" | "missing";
};

function trimmed(value: string | undefined): string {
  return (value || "").trim();
}

export function resolveServiceSupabaseEnv(
  env: NodeJS.ProcessEnv = process.env,
): ServiceSupabaseEnv {
  const scannerUrl = trimmed(env.ETH_SCANNER_SUPABASE_URL).replace(/\/+$/, "");
  const supabaseUrl = trimmed(env.SUPABASE_URL).replace(/\/+$/, "");
  const publicUrl = trimmed(env.NEXT_PUBLIC_SUPABASE_URL).replace(/\/+$/, "");
  const url = scannerUrl || supabaseUrl || publicUrl;
  const urlSource: ServiceSupabaseEnv["urlSource"] = scannerUrl
    ? "ETH_SCANNER_SUPABASE_URL"
    : supabaseUrl
      ? "SUPABASE_URL"
      : publicUrl
        ? "NEXT_PUBLIC_SUPABASE_URL"
        : "missing";

  const serviceRole = trimmed(env.SUPABASE_SERVICE_ROLE_KEY);
  const secret = trimmed(env.SUPABASE_SECRET_KEY);
  const key = serviceRole || secret;
  const keySource: ServiceSupabaseEnv["keySource"] = serviceRole
    ? "SUPABASE_SERVICE_ROLE_KEY"
    : secret
      ? "SUPABASE_SECRET_KEY"
      : "missing";

  return { url, key, urlSource, keySource };
}

export function createServiceSupabaseClient(
  env: NodeJS.ProcessEnv = process.env,
): SupabaseClient | null {
  const resolved = resolveServiceSupabaseEnv(env);
  if (!resolved.url || !resolved.key) return null;
  return createClient(resolved.url, resolved.key, {
    auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false },
    global: {
      fetch: (input, init) => fetch(input, { ...init, cache: "no-store" }),
    },
  });
}

export function serviceSupabaseConfigured(env: NodeJS.ProcessEnv = process.env): boolean {
  const resolved = resolveServiceSupabaseEnv(env);
  return Boolean(resolved.url && resolved.key);
}
