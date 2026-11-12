# Beigefield ETH scanner — architecture & phased roadmap

Goal: the most advanced **defensive** Ethereum contract bug scanner we can build on free tiers, where **heat reflects real problems** (measured funds + failed checks + multi-engine agreement), never code-shape noise.

Live desk: [`/test`](https://beigefield.vercel.app/test). Automation emits **buckets and evidence**, never a human verdict. Never auto-yes.

---

## Hard limits (non-negotiable)

| Rule | Meaning |
|---|---|
| **Defensive only** | Findings are funds-at-risk signals. No exploit code, drain PoCs, attack transaction sequences, or runnable counterexample scripts. |
| **Read-only chain I/O** | `eth_call`, `eth_getCode`, logs, Multicall3. **Never send transactions. Never spend ETH.** |
| **Free tiers only** | GitHub Actions free minutes, public RPCs / existing keys, free Supabase project. Ask before any paid service. |
| **Heat from evidence** | Pattern leads (weak auth regex, proxy mentions, fork family, generic detector hits) contribute **zero** heat. They only select which checks to run. |
| **Lane A stays fast** | Vercel `/api/test/run` remains a lightweight picker + live funds/invariant skim. Heavy engines run **off** serverless. |

---

## Architecture (current → target)

```
┌──────────────────────────── Vercel (/test) ─────────────────────────────┐
│  Lane A (fast): funds floor → scope → live eth_call invariants → heat   │
│  Engines tab: paste/normalize only on serverless (binaries missing)     │
│  Persist → Supabase test_scan_* + eth_scan_*                            │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │ promote
                                  ▼
┌──────────────── eth_scan_targets (lane-b-queue / manual-review) ────────┐
│  status pending|running|done  · claimed_by / claimed_at                 │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │ claim (service role)
                                  ▼
┌──────────────── GitHub Actions worker (Phase A+, free tier) ────────────┐
│  Slither / Aderyn / Mythril|Halmos → normalized findings                │
│  Cross-engine agreement → confidence (not raw heat)                     │
│  Phase B: anvil fork read-only property suites                          │
│  Phase C: protocol graph + risk factors                                 │
│  Write artifacts + update heat_breakdown / findings                     │
└─────────────────────────────────────────────────────────────────────────┘
```

### Heat model (evidence only)

Configured in `eth-scanner/src/eth_scanner/heat.py` (`ETH_SCANNER_HEAT_*`):

| Signal | Contributes heat? |
|---|---|
| Log-scaled measured funds USD | Yes |
| Live / fork invariant **failed** | Yes |
| Privileged function callable by arbitrary EOA (static `eth_call`) | Yes |
| EOA admin/upgrader on ≥ $100k | Yes |
| Code-shape pattern leads | **No** (routing only) |
| Single-engine generic detector | **No** heat alone |
| Multi-engine agreement on a concrete finding | Raises **confidence**; may unlock heat only when paired with funds + failed invariant / privileged evidence (Phase A policy) |

### Buckets

| Bucket | When |
|---|---|
| `lane-a-cool` | Default rank-by-funds; demoted classes; no promote evidence |
| `lane-b-queue` | Funds ≥ $2k **and** (failed invariant **or** privileged callable **or** EOA admin ≥ $100k) |
| `manual-review` | Funds ≥ floor with analysis failed, or Lane B ambiguity |
| `human-*-candidate` | Lane B S7 stubs only — still need human stamp |

### Persistence

| Tables | Role |
|---|---|
| `eth_scan_targets` / `eth_scan_results` / `eth_scan_artifacts` | Queue + Lane A/B state |
| `test_scan_runs` / `test_scan_findings` / `test_triage_events` | `/test` desk history + triage |
| `test_scan_precision` (view) | Flags vs confirmed true |

Migrations live under `supabase/migrations/` (idempotent). Apply via Supabase MCP or report SQL in the PR.

---

## Phase plan

Each phase ships as its **own PR → merge to `main` → confirm Vercel → report bucket / benchmark numbers**.

### Phase A — Worker + deep analysis (engines)

**Deliverable:** GitHub Actions workflow (schedule + `workflow_dispatch`) that claims `lane-b-queue` / `manual-review` rows and runs static/symbolic engines **outside** Vercel.

| Piece | Detail |
|---|---|
| Claim | `claim_deep` via `SUPABASE_URL` + `SUPABASE_SECRET_KEY` |
| Engines | Owner forks: [slither](https://github.com/shanecloonan/slither), [aderyn](https://github.com/shanecloonan/aderyn), Mythril **or** Halmos/hevm when feasible |
| Normalize | One findings schema (align with `lib/eth-scanner/desk/findings.ts`) |
| Dedupe | Stable key: class + rule family (+ location for within-engine) |
| Agreement | ≥2 engines on same class/rule-family → `confidence=high`; single generic detector → no heat bump |
| Secrets to add (repo → Settings → Secrets) | See [Secrets checklist](#secrets-checklist-phase-a) below |
| Code | `.github/workflows/eth-scanner-deep.yml`, `eth_scanner/deep/*`, CLI `python -m eth_scanner deep`, migration `20261112190000_deep_engines.sql` |

**Out of scope for A:** fuzz campaigns that emit exploit sequences; any transaction broadcast.

### Phase B — Property-based verification on a fork

Per-class invariant suites (ERC-4626, staking, lending/CDP, AMM/LP, bridges/escrow, vesting, governance/timelock) as **read-only** fork tests:

- Live `eth_call` property catalog (`eth_scanner/fork_props`) against current mainnet state
- Optional Foundry defensive mock suite (`research/fuzz`) when `forge` is installed; counterexample traces elided
- Output only: invariant name, `held` / `violated` / `unknown`, minimized **evidence summary** (state values), severity
- CLI: `python -m eth_scanner fork-props --address 0x… --class vault [--forge]`
- Migration: `20261112193000_fork_properties.sql`
- **Do not** store or emit a runnable attack sequence — prose + state values only

### Phase C — Protocol context graph

Build a contract graph from verified source + on-chain reads:

- Proxies / implementations, oracles, tokens held, external calls, roles / admins / timelocks / multisigs
- Risk factors: oracle (spot / manipulable / stale), upgrade/admin (EOA, no timelock, uninitialized impl), dependency (known-incident protocols)
- Score: funds-at-risk × likelihood; feeds heat only through the evidence gate
- Code: `eth_scanner/protocol_graph/`, CLI `protocol-graph`, migration `20261112194500_protocol_graph.sql`

### Phase D — Known-good / known-bad knowledge

- Curated audited fingerprints (bytecode + AST hashes) → score zero on standard surfaces (`known_safe.py` + `benchmarks/labeled.json`)
- Labeled benchmark from public post-mortems (read-only; **no PoC code**)
- `/test` benchmark panel: precision, recall, false-positive rate
- CI: `.github/workflows/eth-scanner-benchmark.yml` fails if precision/FP baseline regresses
- Code: `eth_scanner/benchmark/`, `lib/eth-scanner/benchmark.ts`

### Phase E — AI-assisted triage (optional)

- LLM pass **only if** a free/existing key is configured; otherwise skip
- Explains why a finding is / isn't real in plain language
- Ranks and explains only — **never adds heat alone**
- Learns weights from saved triage verdicts (`test_triage_events.verdict_kind`)

### Phase F — Monitoring

- Re-scan funded contracts on implementation change events and large TVL / funds deltas
- Alert surface on `/test` (no spam: dedupe by address + change fingerprint)

---

## Secrets checklist (Phase A)

Add these as **GitHub Actions repository secrets** (Settings → Secrets and variables → Actions). Do **not** put them in the Next.js client or `NEXT_PUBLIC_*`.

| Secret name | Required | Purpose |
|---|---|---|
| `SUPABASE_URL` | **Yes** | Project URL (same as Vercel `SUPABASE_URL` / `ETH_SCANNER_SUPABASE_URL`) |
| `SUPABASE_SECRET_KEY` | **Yes** | Service-role / secret key for claim + write (`eth_scan_*`, `test_scan_*`). Prefer secret key over legacy service_role if both exist. |
| `ETHERSCAN_API_KEYS` | Recommended | Verified-source fetch for claimed addresses (comma-separated). Falls back to free-tier test key if unset. |
| `ETH_RPC_URL` | Recommended | Read-only mainnet RPC for `eth_call` / fork base. Public RPCs used if unset (rate-limited). |
| `ETH_SCANNER_SLITHER_BIN` | Optional | Override Slither binary path in the runner image |
| `ETH_SCANNER_ADERYN_BIN` | Optional | Override Aderyn binary path |
| `ETH_SCANNER_MYTHRIL_BIN` | Optional | Override Mythril binary path |
| `ETH_SCANNER_HALMOS_BIN` | Optional | Override Halmos binary path |

**Not required for Phase A:** OpenAI/Anthropic keys (Phase E), paid RPC, paid CI minutes.

Vercel already needs the same Supabase + Etherscan vars for `/test`. Actions secrets are a **separate** store — copy the values into Actions secrets; do not rely on Vercel env for GHA.

Workflow permissions: `contents: read` only. No deploy keys. No write to the repo unless a later phase needs artifact upload (prefer Supabase).

---

## Free-tier budget notes

| Resource | Constraint | Mitigation |
|---|---|---|
| GHA minutes | ~2 000 min/month private free | Schedule every 30–60 min; claim ≤3 jobs; hard timeouts; skip when queue empty |
| Public RPC | Rate limits | Multicall3 batching; cache; prefer one `ETH_RPC_URL` |
| Etherscan | Free key quotas | Key rotation via `ETHERSCAN_API_KEYS` list |
| Vercel serverless | 60–180s, no engine binaries | Keep Lane A light; engines on GHA only |

---

## Success metrics (per phase report)

After each merge, report:

1. PR link
2. What shipped (files / workflow / migration)
3. Live bucket distribution (`test_scan_runs` / `eth_scan_targets`)
4. For D+: precision / recall / FP rate from `test_scan_precision` + benchmark panel

---

## Implementation order

1. **This doc** — architecture freeze
2. **Phase A** — `.github/workflows/eth-scanner-deep.yml` + Python deep worker + findings normalize/dedupe/agreement
3. **Phase B** — fork invariant suites (read-only evidence)
4. **Phase C** — protocol graph
5. **Phase D** — fingerprints + `/test` benchmark + CI gate
6. **Phase E** — optional LLM explain
7. **Phase F** — upgrade / TVL monitors

Lane A evidence-heat (#37 / #38) and the $2k funds floor (#36) are **prerequisites** already on `main`.
