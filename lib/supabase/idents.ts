const PUBLIC_IDENT = /^[A-Za-z_][A-Za-z0-9_]*$/;

export function isPublicIdentifier(name: string): boolean {
  return name.length > 0 && name.length <= 63 && PUBLIC_IDENT.test(name);
}

/** Quote a validated identifier. Throws if the name is not a plain public ident. */
export function quoteIdent(name: string): string {
  if (!isPublicIdentifier(name)) {
    throw new Error("Refusing to quote an unexpected SQL identifier.");
  }
  return `"${name}"`;
}
