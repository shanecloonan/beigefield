/**
 * Common finding schema for the /test multi-engine desk.
 *
 * Funds-at-risk framing only: every finding is a *signal that value could be
 * lost or locked*, never an exploit recipe. Adapters strip counterexample
 * calldata / transaction sequences down to a one-line "counterexample found"
 * note; nothing here ever emits PoC code.
 */

export type Severity = "critical" | "high" | "medium" | "low" | "info";
export type Confidence = "high" | "medium" | "low";

/** Funds-at-risk classes. Shared vocabulary between engines and corpora. */
export const FUNDS_AT_RISK_CLASSES = {
  "reentrancy": "Reentrancy — state updated after an external call that moves value",
  "access-control": "Access control — privileged value-moving path reachable by anyone",
  "arithmetic": "Arithmetic — overflow / underflow / unsafe downcast in balances or shares",
  "rounding": "Rounding / precision loss in share or fee math",
  "oracle-manipulation": "Oracle / price manipulation (spot price, flash-loan skew)",
  "staleness": "Stale oracle or stale accounting state",
  "unchecked-call": "Unchecked low-level call or token return value",
  "token-integration": "Non-standard ERC-20 behaviour (fee-on-transfer, no-return, approve race)",
  "signature-replay": "Signature replay / malleability / missing domain separation",
  "delegatecall-storage": "Delegatecall / proxy storage collision or uninitialized implementation",
  "bridge-message": "Bridge message validation (chain-id spoofing, hash collision, replay)",
  "dos-locked-funds": "Denial of service / permanently locked funds",
  "mev-slippage": "MEV / missing slippage or deadline protection",
  "selfdestruct-ether": "Selfdestruct / forced ether / unexpected balance assumptions",
  "randomness": "Weak on-chain randomness gating value",
  "invariant-violation": "Funds-conservation invariant violated (solvency, share backing)",
  "other": "Other funds-at-risk signal",
} as const;

export type FundsAtRiskClass = keyof typeof FUNDS_AT_RISK_CLASSES;

export type Location = {
  file: string | null;
  line: number | null;
  contract: string | null;
  function: string | null;
};

export type DeskFinding = {
  /** Stable id: `${engine}:${rule}:${file}:${line}`. */
  id: string;
  engine: string;
  rule: string;
  title: string;
  severity: Severity;
  confidence: Confidence;
  class: FundsAtRiskClass;
  location: Location;
  /** Short human evidence. Truncated; never contains exploit payloads. */
  evidence: string;
  /** Corpus references attached by the cross-referencer. */
  references: { corpus: string; label: string; url: string }[];
  /** Always true — the desk is defensive only. */
  defensive_only: true;
};

const SEVERITY_ALIASES: Record<string, Severity> = {
  critical: "critical",
  high: "high",
  medium: "medium",
  med: "medium",
  low: "low",
  informational: "info",
  info: "info",
  optimization: "info",
  note: "info",
  warning: "medium",
};

export function normalizeSeverity(raw: unknown): Severity {
  const s = String(raw ?? "").trim().toLowerCase();
  return SEVERITY_ALIASES[s] ?? "info";
}

/** Noisy Slither checks still surface as findings, but cannot inflate triage. */
export const SLITHER_SEVERITY_OVERRIDE: Partial<Record<string, Severity>> = {
  timestamp: "info",
  "costly-loop": "info",
};

export function normalizeConfidence(raw: unknown): Confidence {
  const s = String(raw ?? "").trim().toLowerCase();
  if (s === "high") return "high";
  if (s === "medium" || s === "med") return "medium";
  return "low";
}

/** Ordered: first match wins. Keyed on rule ids, SWC ids, and titles. */
const CLASS_RULES: [RegExp, FundsAtRiskClass][] = [
  [/reentr|swc-107|read-only-reentr|erc777/i, "reentrancy"],
  [/delegatecall|storage[-_ ]?collision|uninitiali[sz]ed[-_ ]?(proxy|impl|state|storage)|swc-112|swc-109|proxy/i, "delegatecall-storage"],
  [/signature|ecrecover|replay|malleab|swc-117|swc-121|swc-122|permit/i, "signature-replay"],
  [/bridge|chain[-_ ]?id|hash[-_ ]?collision|encode[-_ ]?packed|swc-133/i, "bridge-message"],
  [/oracle|price[-_ ]?manip|flash[-_ ]?loan|spot[-_ ]?price|twap/i, "oracle-manipulation"],
  [/stale|heartbeat|updatedat/i, "staleness"],
  [/tx[-_.]?origin|access|owner|onlyowner|unprotected|protected[-_ ]?vars|arbitrary[-_ ]?send|suicidal|missing[-_ ]?auth|multiple[-_ ]?constructors|authori[sz]|role|swc-105|swc-106|swc-115|privilege|centrali/i, "access-control"],
  [/unchecked[-_ ]?(transfer|call|send|lowlevel|low-level|return)|low[-_ ]?level|unused[-_ ]?return|swc-104|return[-_ ]?value|no[-_ ]?return/i, "unchecked-call"],
  [/fee[-_ ]?on[-_ ]?transfer|erc20|approve|allowance|decimals|weird[-_ ]?token|rebasing/i, "token-integration"],
  [/overflow|underflow|downcast|arithmetic|incorrect[-_ ]?(shift|exp|unary)|swc-101|integer|truncat/i, "arithmetic"],
  [/divide[-_ ]?before[-_ ]?multiply|precision|rounding|share[-_ ]?inflation|first[-_ ]?deposit/i, "rounding"],
  [/slippage|deadline|front[-_ ]?run|sandwich|mev|swc-114/i, "mev-slippage"],
  [/selfdestruct|forced[-_ ]?ether|balance[-_ ]?equal|strict[-_ ]?equal|swc-132|swc-106/i, "selfdestruct-ether"],
  [/random|blockhash|timestamp|weak[-_ ]?prng|swc-120|swc-116/i, "randomness"],
  [/locked[-_ ]?ether|dos|denial|unbounded|gas[-_ ]?limit|swc-113|swc-128|calls[-_ ]?loop|costly[-_ ]?loop|msg[-_ ]?value[-_ ]?loop/i, "dos-locked-funds"],
  [/invariant|property|solvency|conservation|echidna_|check_|assert/i, "invariant-violation"],
];

export function classifyFinding(...hints: (string | null | undefined)[]): FundsAtRiskClass {
  const text = hints.filter(Boolean).join(" ");
  for (const [re, cls] of CLASS_RULES) if (re.test(text)) return cls;
  return "other";
}

const MAX_EVIDENCE = 600;

/** Collapse whitespace, cap length, and drop hex blobs that look like calldata. */
export function sanitizeEvidence(raw: unknown): string {
  let s = String(raw ?? "").replace(/\s+/g, " ").trim();
  s = s.replace(/0x[0-9a-fA-F]{72,}/g, "0x…[calldata elided]");
  if (s.length > MAX_EVIDENCE) s = `${s.slice(0, MAX_EVIDENCE - 1)}…`;
  return s;
}

export function makeFinding(input: {
  engine: string;
  rule: string;
  title: string;
  severity?: unknown;
  confidence?: unknown;
  location?: Partial<Location>;
  evidence?: unknown;
  classHint?: string;
}): DeskFinding {
  const location: Location = {
    file: input.location?.file ?? null,
    line: input.location?.line ?? null,
    contract: input.location?.contract ?? null,
    function: input.location?.function ?? null,
  };
  const evidence = sanitizeEvidence(input.evidence);
  const unlocated = !location.file && location.line == null && !location.function && !location.contract;
  const idParts = [input.engine, input.rule, location.file ?? "-", location.line ?? "-", location.function ?? "-"];
  // Location-less findings (e.g. Slither detectors with no elements) would all
  // collide on "-:-:-" and be silently deduped; key them by evidence instead.
  if (unlocated) idParts.push(shortHash(`${input.title} ${evidence}`));
  return {
    id: idParts.join(":"),
    engine: input.engine,
    rule: input.rule,
    title: sanitizeEvidence(input.title).slice(0, 200),
    severity: (input.engine === "slither" && SLITHER_SEVERITY_OVERRIDE[input.rule])
      || normalizeSeverity(input.severity),
    confidence: normalizeConfidence(input.confidence),
    class: classifyFinding(input.classHint, input.rule, input.title),
    location,
    evidence,
    references: [],
    defensive_only: true,
  };
}

/** FNV-1a → 8 hex chars. Stable, non-cryptographic; only for id disambiguation. */
export function shortHash(s: string): string {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return (h >>> 0).toString(16).padStart(8, "0");
}

export const SEVERITY_RANK: Record<Severity, number> = { critical: 0, high: 1, medium: 2, low: 3, info: 4 };
const CONFIDENCE_RANK: Record<Confidence, number> = { high: 0, medium: 1, low: 2 };

/**
 * Severity first, then triage score (desc) when present, then confidence,
 * then engine/rule for a stable order. The table leads with triage, so rows
 * within one severity tier must read top-down by triage.
 */
export function sortFindings<T extends DeskFinding & { triage?: number }>(list: T[]): T[] {
  return [...list].sort(
    (a, b) =>
      SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity] ||
      (b.triage ?? 0) - (a.triage ?? 0) ||
      CONFIDENCE_RANK[a.confidence] - CONFIDENCE_RANK[b.confidence] ||
      a.engine.localeCompare(b.engine) ||
      a.rule.localeCompare(b.rule),
  );
}

export function severityCounts(list: { severity: Severity }[]): Record<Severity, number> {
  const out: Record<Severity, number> = { critical: 0, high: 0, medium: 0, low: 0, info: 0 };
  for (const f of list) out[f.severity] += 1;
  return out;
}

/** Drop duplicate ids (same engine/rule/location). */
export function dedupeFindings(list: DeskFinding[]): DeskFinding[] {
  const seen = new Set<string>();
  return list.filter((f) => (seen.has(f.id) ? false : (seen.add(f.id), true)));
}
