import { createSupabaseClient } from "./client";

export const PING_NOTE_MAX = 500;

export type PingRow = {
  id: string;
  note: string | null;
  created_at: string;
};

export type PingQuery = {
  rows: PingRow[];
  error: string | null;
};

export function pingNote(input: string, now = new Date()): string {
  const trimmed = input.trim().slice(0, PING_NOTE_MAX);
  return trimmed || now.toISOString();
}

export function normalizePing(value: unknown): PingRow | null {
  if (!value || typeof value !== "object") return null;
  const row = value as Record<string, unknown>;
  const id = row.id;
  const createdAt = row.created_at;
  if ((typeof id !== "number" && typeof id !== "string") || typeof createdAt !== "string") {
    return null;
  }
  const note = row.note;
  if (note !== null && note !== undefined && typeof note !== "string") return null;
  return {
    id: String(id),
    note: typeof note === "string" ? note : null,
    created_at: createdAt,
  };
}

export async function fetchPingTests(limit = 12): Promise<PingQuery> {
  try {
    const supabase = createSupabaseClient();
    if (!supabase) {
      return { rows: [], error: "Supabase URL or public key is not set." };
    }

    const { data, error } = await supabase
      .from("ping_tests")
      .select("id, note, created_at")
      .order("id", { ascending: false })
      .limit(limit);

    if (error) return { rows: [], error: error.message };

    const rows = (data ?? [])
      .map((row) => normalizePing(row))
      .filter((row): row is PingRow => row !== null);
    return { rows, error: null };
  } catch {
    return { rows: [], error: "Could not read ping_tests." };
  }
}

export async function insertPingTest(note: string): Promise<{ row: PingRow | null; error: string | null }> {
  try {
    const supabase = createSupabaseClient();
    if (!supabase) {
      return { row: null, error: "Supabase URL or public key is not set." };
    }

    const { data, error } = await supabase
      .from("ping_tests")
      .insert({ note: pingNote(note) })
      .select("id, note, created_at")
      .single();

    if (error) return { row: null, error: error.message };
    const row = normalizePing(data);
    if (!row) return { row: null, error: "The insert succeeded but the new row could not be read." };
    return { row, error: null };
  } catch {
    return { row: null, error: "Could not insert into ping_tests." };
  }
}
