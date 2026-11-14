/**
 * Client-safe list identities. No filesystem access.
 * List 1 is the funded curated feed. List 2 is the sketchy junk-drawer.
 * Bounds match eth-scanner/data/lists.json.
 */

export const LIST1_ID = "list-1" as const;
export const LIST2_ID = "list-2" as const;

export type ScanListId = typeof LIST1_ID | typeof LIST2_ID;

export type ScanList = {
  id: ScanListId;
  name: string;
  kind: "funded-curated" | "sketchy";
  blurb: string;
  min_usd: number | null;
  max_usd: number | null;
};

export const SCAN_LISTS: readonly ScanList[] = [
  {
    id: LIST1_ID,
    name: "List 1",
    kind: "funded-curated",
    blurb: "Funded, credible-but-less-audited curated feed. Bounds are $2,000–$9,000,000.",
    min_usd: 2000,
    max_usd: 9_000_000,
  },
  {
    id: LIST2_ID,
    name: "List 2",
    kind: "sketchy",
    blurb: "Junk-drawer / sketchy small-dollar contracts in the $50–$1,900 band.",
    min_usd: 50,
    max_usd: 1900,
  },
] as const;

export function scanList(id: string): ScanList | null {
  return SCAN_LISTS.find((row) => row.id === id) ?? null;
}

export function isScanListId(value: unknown): value is ScanListId {
  return value === LIST1_ID || value === LIST2_ID;
}
