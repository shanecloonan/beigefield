function errorCode(error: unknown): string | null {
  if (!error || typeof error !== "object" || !("code" in error)) return null;
  const code = (error as { code?: unknown }).code;
  if (typeof code !== "string" && typeof code !== "number") return null;
  const text = String(code);
  if (!/^[A-Za-z0-9_]{2,48}$/.test(text)) return null;
  return text;
}

/** A stable failure string that never includes the driver message or a URL. */
export function safeDatabaseError(error: unknown): string {
  const code = errorCode(error);
  if (code) return `Database query failed (${code}).`;
  return "Database query failed.";
}
