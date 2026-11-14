/**
 * Named scan lists shared by Blend and the /test desk.
 * Field names match the Python feed (`eth_scanner.feed.lists`).
 * List 1 is the funded curated master feed. List 2 is the $50–$1,900 sketchy feed.
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
    blurb: "Funded curated feed. Deep lane uses the existing strong-candidate rules.",
    min_usd: null,
    max_usd: null,
  },
  {
    id: LIST2_ID,
    name: "List 2",
    kind: "sketchy",
    blurb: "Janky and sketchy targets holding $50–$1,900. Rows outside that band are dropped.",
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
