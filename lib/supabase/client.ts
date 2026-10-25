import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { readSupabasePublicEnv } from "./public-env";

/**
 * Browser and server client for the public Supabase API.
 * Uses the publishable key when it is set, otherwise the legacy anon key.
 * No session is stored; this app does not sign users in.
 */
export function createSupabaseClient(): SupabaseClient | null {
  const { url, key } = readSupabasePublicEnv();
  if (!url || !key) return null;

  return createClient(url, key, {
    auth: {
      persistSession: false,
      autoRefreshToken: false,
      detectSessionInUrl: false,
    },
    global: {
      fetch: (input, init) => fetch(input, { ...init, cache: "no-store" }),
    },
  });
}
