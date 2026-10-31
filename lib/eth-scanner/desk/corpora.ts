/**
 * Vulnerability corpora used as *reference context* for desk findings.
 *
 * We do not vendor these repos (several contain exploit PoCs). Each adapter
 * carries a small hand-curated index from our funds-at-risk classes to
 * category folders / files in Shane's forks, so a finding links to prior art.
 * If ETH_SCANNER_CORPORA_DIR/<repo> exists locally, status reports "mirrored".
 */

import type { DeskFinding, FundsAtRiskClass } from "./findings";

export const CORPUS_IDS = [
  "smartbugs-curated",
  "web3bugs",
  "defivulnlabs",
  "not-so-smart-contracts",
  "bridge-vulns",
  "buggy-erc20",
  "clustered-web3",
  "bug-bounty-intel",
] as const;
export type CorpusId = (typeof CORPUS_IDS)[number];

export type CorpusMeta = {
  id: CorpusId;
  name: string;
  fork: string;
  upstream: string;
  branch: string;
  blurb: string;
  /** class → [label, path in repo] */
  index: Partial<Record<FundsAtRiskClass, [string, string][]>>;
};

export const CORPORA: Record<CorpusId, CorpusMeta> = {
  "smartbugs-curated": {
    id: "smartbugs-curated",
    name: "SmartBugs Curated",
    fork: "shanecloonan/smartbugs-curated",
    upstream: "smartbugs/smartbugs-curated",
    branch: "main",
    blurb: "143 annotated vulnerable contracts in DASP categories.",
    index: {
      "reentrancy": [["DASP reentrancy", "dataset/reentrancy"]],
      "access-control": [["DASP access control", "dataset/access_control"]],
      "arithmetic": [["DASP arithmetic", "dataset/arithmetic"]],
      "randomness": [["DASP bad randomness", "dataset/bad_randomness"], ["DASP time manipulation", "dataset/time_manipulation"]],
      "dos-locked-funds": [["DASP denial of service", "dataset/denial_of_service"]],
      "mev-slippage": [["DASP front running", "dataset/front_running"]],
      "unchecked-call": [["DASP unchecked low-level calls", "dataset/unchecked_low_level_calls"]],
      "token-integration": [["DASP short addresses", "dataset/short_addresses"]],
      "other": [["DASP other", "dataset/other"]],
    },
  },
  "web3bugs": {
    id: "web3bugs",
    name: "Web3Bugs",
    fork: "shanecloonan/Web3Bugs",
    upstream: "ZhangZhuoSJTU/Web3Bugs",
    branch: "main",
    blurb: "Exploitable Code4rena bugs with a functional-bug taxonomy (ICSE '23).",
    index: {
      "oracle-manipulation": [["Price-oracle manipulation (S2)", "results/bugs.csv"]],
      "rounding": [["Erroneous accounting (S6)", "results/bugs.csv"]],
      "access-control": [["ID-uniqueness / privilege (S3/S5)", "results/bugs.csv"]],
      "invariant-violation": [["Contract-implementation-specific bugs", "results/bugs.csv"]],
      "mev-slippage": [["Transaction-order / slippage", "results/bugs.csv"]],
      "other": [["Full bug table", "results/bugs.csv"]],
    },
  },
  "defivulnlabs": {
    id: "defivulnlabs",
    name: "DeFiVulnLabs",
    fork: "shanecloonan/DeFiVulnLabs",
    upstream: "SunWeb3Sec/DeFiVulnLabs",
    branch: "main",
    blurb: "Foundry lessons per vulnerability class (reference only — not executed here).",
    index: {
      "reentrancy": [["Reentrancy", "src/test/Reentrancy.sol"], ["Read-only reentrancy", "src/test/ReadOnlyReentrancy.sol"], ["ERC777 reentrancy", "src/test/ERC777-reentrancy.sol"]],
      "access-control": [["Visibility", "src/test/Visibility.sol"], ["tx.origin", "src/test/txorigin.sol"], ["Unprotected callback", "src/test/Unprotected-callback.sol"]],
      "arithmetic": [["Overflow", "src/test/Overflow.sol"], ["Unsafe downcast", "src/test/unsafe-downcast.sol"]],
      "rounding": [["Precision loss", "src/test/Precision-loss.sol"], ["Divide before multiply", "src/test/Divmultiply.sol"], ["First deposit", "src/test/first-deposit.sol"]],
      "oracle-manipulation": [["Price manipulation", "src/test/Price_manipulation.sol"], ["Flash-loan flaw", "src/test/Flashloan-flaw.sol"]],
      "staleness": [["Stale oracle", "src/test/Oracle-stale.sol"]],
      "unchecked-call": [["Return value", "src/test/Returnvalue.sol"], ["Unsafe call", "src/test/UnsafeCall.sol"]],
      "token-integration": [["Fee-on-transfer", "src/test/fee-on-transfer.sol"], ["Phantom permit", "src/test/phantom-permit.sol"], ["Return false", "src/test/Returnfalse.sol"]],
      "signature-replay": [["Signature replay", "src/test/SignatureReplay.sol"], ["ecrecover", "src/test/ecrecover.sol"]],
      "delegatecall-storage": [["Delegatecall", "src/test/Delegatecall.sol"], ["Storage collision", "src/test/Storage-collision.sol"], ["Uninitialized variables", "src/test/Uninitialized_variables.sol"]],
      "mev-slippage": [["Slippage / deadline", "src/test/Slippage-deadline.sol"]],
      "selfdestruct-ether": [["Selfdestruct", "src/test/Selfdestruct.sol"]],
      "dos-locked-funds": [["DoS", "src/test/DOS.sol"]],
      "randomness": [["Randomness", "src/test/Randomness.sol"]],
      "invariant-violation": [["Invariant", "src/test/Invariant.sol"]],
    },
  },
  "not-so-smart-contracts": {
    id: "not-so-smart-contracts",
    name: "Not So Smart Contracts",
    fork: "shanecloonan/not-so-smart-contracts",
    upstream: "crytic/not-so-smart-contracts",
    branch: "master",
    blurb: "Trail of Bits' canonical vulnerable-pattern examples.",
    index: {
      "reentrancy": [["Reentrancy", "reentrancy"]],
      "access-control": [["Unprotected function", "unprotected_function"], ["Wrong constructor name", "wrong_constructor_name"]],
      "arithmetic": [["Integer overflow", "integer_overflow"]],
      "randomness": [["Bad randomness", "bad_randomness"]],
      "dos-locked-funds": [["Denial of service", "denial_of_service"]],
      "selfdestruct-ether": [["Forced ether reception", "forced_ether_reception"]],
      "unchecked-call": [["Unchecked external call", "unchecked_external_call"]],
      "token-integration": [["Incorrect interface", "incorrect_interface"]],
      "mev-slippage": [["Race condition", "race_condition"]],
      "delegatecall-storage": [["Variable shadowing", "variable shadowing"]],
    },
  },
  "bridge-vulns": {
    id: "bridge-vulns",
    name: "Blockchain bridge vulnerabilities",
    fork: "shanecloonan/Blockchain-bridge-vulnerabilities",
    upstream: "the-caliber/Blockchain-bridge-vulnerabilities",
    branch: "main",
    blurb: "Bridge-specific failure classes (spoofed chain id, replay, hash collision).",
    index: {
      "bridge-message": [["Spoofed chain id", "src/BridgeSpoofChainId.sol"], ["Hash collision", "src/BridgeHashCollision.sol"], ["Safe token send", "src/BridgeSafeTokenSend.sol"]],
      "signature-replay": [["Bridge signature replay", "src/BridgeSignatureReplay.sol"]],
    },
  },
  "buggy-erc20": {
    id: "buggy-erc20",
    name: "Awesome buggy ERC-20 tokens",
    fork: "shanecloonan/awesome-buggy-erc20-tokens",
    upstream: "sec-bit/awesome-buggy-erc20-tokens",
    branch: "master",
    blurb: "Catalogue of real token bugs (overflow mints, no-return, approve races).",
    index: {
      "token-integration": [["ERC-20 issue list", "ERC20_token_issue_list.md"], ["Bad tokens (top)", "bad_tokens.top.csv"]],
      "arithmetic": [["Overflow-class token issues", "ERC20_token_issue_list.md"]],
      "access-control": [["Anyone-can (setOwner / pause) issues", "ERC20_token_issue_list.md"]],
    },
  },
  "clustered-web3": {
    id: "clustered-web3",
    name: "Clustered Web3 vulnerabilities",
    fork: "shanecloonan/clustered-web3-vulnerabilities",
    upstream: "LyuboslavLyubenov/clustered-web3-vulnerabilities",
    branch: "main",
    blurb: "Audit findings clustered by similarity — browse neighbours of a class.",
    index: {
      "other": [["Cluster pages", "cluster_pages"]],
      "invariant-violation": [["Cluster pages", "cluster_pages"]],
      "rounding": [["Cluster pages", "cluster_pages"]],
      "oracle-manipulation": [["Cluster pages", "cluster_pages"]],
    },
  },
  "bug-bounty-intel": {
    id: "bug-bounty-intel",
    name: "Bug-bounty intelligence",
    fork: "shanecloonan/bug-bounty-intelligence-mcp",
    upstream: "holistis/bug-bounty-intelligence-mcp",
    branch: "main",
    blurb: "CC0 Sherlock acceptance-rate priors per pattern (used to rank triage).",
    index: {
      "reentrancy": [["Acceptance priors", "vulnerability-acceptance-rates.json"]],
      "access-control": [["Acceptance priors", "vulnerability-acceptance-rates.json"]],
      "arithmetic": [["Acceptance priors", "vulnerability-acceptance-rates.json"]],
      "rounding": [["Acceptance priors", "vulnerability-acceptance-rates.json"]],
      "oracle-manipulation": [["Acceptance priors", "vulnerability-acceptance-rates.json"]],
      "staleness": [["Acceptance priors", "vulnerability-acceptance-rates.json"]],
      "mev-slippage": [["Acceptance priors", "vulnerability-acceptance-rates.json"]],
      "dos-locked-funds": [["Acceptance priors", "vulnerability-acceptance-rates.json"]],
    },
  },
};

/**
 * Sherlock acceptance priors (CC0) from bug-bounty-intelligence-mcp,
 * vulnerability-acceptance-rates.json (10 contests, 1,032 findings).
 * Mapped onto our classes; used only to rank triage, never as a verdict.
 */
export const ACCEPTANCE_PRIORS: Partial<Record<FundsAtRiskClass, { pattern: string; rate: number; n: number }>> = {
  "reentrancy": { pattern: "reentrancy", rate: 0.78, n: 51 },
  "arithmetic": { pattern: "overflow", rate: 0.58, n: 45 },
  "access-control": { pattern: "access-control", rate: 0.47, n: 74 },
  "rounding": { pattern: "rounding", rate: 0.4, n: 63 },
  "oracle-manipulation": { pattern: "oracle-manipulation", rate: 0.36, n: 131 },
  "staleness": { pattern: "staleness", rate: 0.49, n: 174 },
  "mev-slippage": { pattern: "mev-slippage", rate: 0.49, n: 89 },
  "dos-locked-funds": { pattern: "dos-griefing", rate: 0.41, n: 156 },
};

export function corpusUrl(c: CorpusMeta, p: string): string {
  const kind = /\.[a-z0-9]+$/i.test(p) ? "blob" : "tree";
  return `https://github.com/${c.fork}/${kind}/${c.branch}/${p.split("/").map(encodeURIComponent).join("/")}`;
}

export function corpusCatalog() {
  return CORPUS_IDS.map((id) => {
    const c = CORPORA[id];
    return {
      id: c.id,
      name: c.name,
      fork: c.fork,
      upstream: c.upstream,
      fork_url: `https://github.com/${c.fork}`,
      blurb: c.blurb,
      classes: Object.keys(c.index) as FundsAtRiskClass[],
    };
  });
}

/** Attach corpus references (max 6) to each finding by funds-at-risk class. */
export function crossReference(findings: DeskFinding[]): DeskFinding[] {
  return findings.map((f) => {
    const refs: DeskFinding["references"] = [];
    for (const id of CORPUS_IDS) {
      const c = CORPORA[id];
      for (const [label, p] of c.index[f.class] ?? []) {
        refs.push({ corpus: c.name, label, url: corpusUrl(c, p) });
        break; // one link per corpus keeps the row readable
      }
    }
    return { ...f, references: refs.slice(0, 6) };
  });
}

/** Triage score: severity × confidence × acceptance prior. 0–100. */
export function triageScore(f: DeskFinding): number {
  const sev = { critical: 1, high: 0.8, medium: 0.5, low: 0.25, info: 0.05 }[f.severity];
  const conf = { high: 1, medium: 0.7, low: 0.4 }[f.confidence];
  const prior = ACCEPTANCE_PRIORS[f.class]?.rate ?? 0.45;
  return Math.min(100, Math.round(sev * conf * (0.5 + prior) * 80));
}
