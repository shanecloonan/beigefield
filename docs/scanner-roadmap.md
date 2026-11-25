# Beigefield ETH scanner — architecture & phased roadmap

Goal: the most advanced **defensive** Ethereum contract bug scanner we can build on free tiers plus Shane's capped Alchemy RPC, where **heat reflects real problems** (measured funds + failed checks + multi-engine agreement), never code-shape noise.

Live desk: [`/test`](https://beigefield.vercel.app/test). Automation emits **buckets and evidence**, never a human verdict. Never auto-yes.

---

## Hard limits (non-negotiable)

| Rule | Meaning |
|---|---|
| **Defensive only** | Findings are funds-at-risk signals. No mainnet broadcast and no packaged exploit scripts. A post-heat fork-verify stage may record a *sanitized* Foundry sequence when a conservation invariant breaks on a **local** fork. |
| **Read-only chain I/O** | `eth_call`, `eth_getCode`, logs, Multicall3, and — when the endpoint allows — `trace_*` / `debug_*` / `alchemy_getAssetTransfers`. **Never send transactions. Never spend ETH.** |
| **Free tiers plus Shane's capped Alchemy PAYG RPC ($50/mo hard cap)** | GitHub Actions free minutes, the existing `ETH_RPC_URL` secret (Alchemy Pay-as-You-Go, `eth-mainnet.g.alchemy.com`, ~96M CU/month), and the free Supabase project. No other paid service. Trace and debug calls are feature-detected, cached, and capped per run; a missing method or HTTP 429 keeps the previous behavior. |
| **Heat from evidence** | Pattern leads (weak auth regex, proxy mentions, fork family, generic detector hits) contribute **zero** heat. They only select which checks to run. |
| **Lane A stays fast** | Vercel `/api/test/run` remains a lightweight picker + live funds/invariant skim. Heavy engines run **off** serverless. |

A `chain` field on targets and runs defaults to `ethereum`. The Blend board and `/api/blend/stats` stay on Ethereum unless `chain` is set, so Ethereum totals do not move when another chain is stored. Solana is the first adapter beside Ethereum (`eth_scanner/chains`). A later chain registers a name and an address form; it does not go through the Ethereum claim path.

`python -m eth_scanner solana-discover` reads the public DefiLlama Solana TVL and, when `SOLANA_RPC_URL` is set, that RPC. Otherwise it uses the public mainnet-beta endpoint and backs off once on HTTP 429. Dollars at risk are evidence. The command adds no heat and does not send a transaction. The $100 floor is unchanged.

`python -m eth_scanner solana-inspect --address <program>` reads the upgradeable loader account and classifies the upgrade authority as immutable, a single key, or a known multisig/governance program. OtterSec's public verify endpoint records whether a build is verified and, when present, the source URL. `--source` runs local notes for a missing signer check, a missing owner check, an arbitrary CPI shape, a PDA helper with no bump, and unchecked math. `--tools` runs `cargo audit` and `cargo clippy --offline` only when those binaries are already installed. All of these add no heat.

`python -m eth_scanner solana-sim --address <program> --rpc http://127.0.0.1:8899` plans a local `solana-test-validator` clone. Any other RPC, including public mainnet-beta and Alchemy, is refused before a process starts. `--run` starts that local validator only when the binary is already installed, then stops it. The command never sends a transaction and adds no heat.

EVM chains beside Ethereum are BNB Chain (56), Arbitrum One (42161), Base (8453), Optimism (10), and Polygon (137). `python -m eth_scanner evm-chains` prints the chain id, native token, and whether `ETH_RPC_URL`, `BSC_RPC_URL`, `ARBITRUM_RPC_URL`, `BASE_RPC_URL`, `OPTIMISM_RPC_URL`, or `POLYGON_RPC_URL` is set. It never prints the URL. Ethereum still uses only `ETH_RPC_URL` and does not gain a public fallback. The other chains use that same Alchemy key on their own host when their variable is unset, then a free public endpoint, and a 429 is retried once. Explorer reads stay on Etherscan v2 with that chain's `chainid`, and Sourcify is the fallback when no key is set. The same capped Alchemy key also covers `bnb-mainnet.g.alchemy.com`, `arb-mainnet.g.alchemy.com`, `base-mainnet.g.alchemy.com`, `opt-mainnet.g.alchemy.com`, and `polygon-mainnet.g.alchemy.com`; those hosts share the $10/month cap. Ethereum's 50-scan example is unchanged. Optimism and Polygon are capped at 4 deep scans a day. Each chain holds its own scan-cycle lease, so a non-Ethereum pass does not take the Ethereum lease. `evm-fork` plans a loopback anvil fork and does not broadcast. Trace and proof methods are feature-detected per endpoint. A missing method or a 429 does not add heat.

`python -m eth_scanner evm-discover --chain bsc` reads DefiLlama TVL for BNB Chain (`Binance`), Arbitrum, or Base. Dollars are that chain's TVL, never the protocol total, and the $100 floor is unchanged. A bare address is kept only when the protocol lists that one chain. `eth_getCode` must show code before a row is queued. `eth_scan_targets` is keyed by `(chain, address)`. An Ethereum row keeps its address, and the same address on another chain is a second row. The command refuses `--chain ethereum`. The Blend board filters Ethereum, BNB, Arbitrum, Base, Optimism, Polygon, Solana, and All. Every row shows a chain badge. The Ethereum filter is the default, and a row from another chain does not change its totals. `evm-semantics` records Arbitrum's L2 head and `l1BlockNumber` separately, lists chain precompiles, and flags PancakeSwap or Venus names in local source. Those flags add no heat. A header without `l1BlockNumber` stays unknown. `decompile-funded` runs Heimdall on an unverified contract at or above the $100 floor and falls back to Panoramix. The text is lower confidence than verified source and adds no heat. A missing tool, a verified contract, or funds below the floor skips the run. `defihacklabs-index` counts public incident names and dates and drops the writeups. It adds no heat and does not change the labeled benchmark or the corpus floor. A failed fetch stays empty. `defihacklabs-recall` joins DefiLlama hack rows to the protocol's listed address and scores custom-detector leads only when that account still has code, is not a proxy or a clone, and Sourcify has the runtime source. Proxy and unverified rows stay out of the denominator. The listed address is often the token, not the exploited contract. The leads add no heat, and the labeled heat benchmark is unchanged. `wake-detect` runs Ackee Wake when the binary is already installed and keeps the detector name, impact, and confidence. Source snippets are dropped. The names add no heat. A missing binary or a crash leaves an empty lead list. The deep worker installs Heimdall 0.9.3, `eth-wake` 5.0.0, and `panoramix-decompiler` 0.6.1 into cached prefixes and runs them on deep targets. Wake names and decompile notes stay generic, so they add no heat. Unit-test CI does not install them. Ethereum still gets 50 deep scans a day. BNB, Arbitrum, and Base get 8 each, about 9.8M CU/month together against the 96M cap. This stage adds no heat. `advanced-invariants` keeps only defensive catalog properties that held on a known-good baseline. A property that fails that baseline is dropped. Heat moves only when a local fuzzer or prover later fails a property that was kept. With no LLM key the command skips and heat stays 0. `maybe-triage` annotates a manual-review row and may lower its heat. Another bucket is left unchanged, and the heat cannot rise. `taint-flow` names a variable `delegatecall` target, and an oracle read that precedes a value move in the same function. Both are leads and add no heat. A `delegatecall` to `address(this)` stays quiet. `hevm` runs beside Halmos on deployed bytecode under `out/`, with a 20 second cap. A missing binary, missing bytecode, or a timeout adds no heat. A local hevm failure is a generic lead. `learned-rank` orders contracts by lead count only when labeled incidents have a higher mean than labeled safe contracts. Otherwise the weight is 0. The order adds no heat. Kontrol runs beside hevm when `kontrol` is on PATH and the project has a `foundry.toml`, with a 30 second cap. A missing binary or a timeout adds no heat. `protocol-invariants` applies the vault catalog to a system and records a strategy, oracle, or router as a witness. Heat moves only when a local failure survives the known-good baseline. `fork-sensitivity` repeats a `totalAssets` read on a localhost fork and may override one storage word inside `eth_call`. A public URL is refused. The call is not a transaction, and heat stays 0. `system-graph` links protocol roles by `(chain, address)`. Two chains produce a cross-chain edge. The graph stores no message and no calldata, and it adds no heat. `l2-invariants` compares an Arbitrum or Base header with a supplied L1 head. A missing L1 number stays unknown. An L1 number past that head is a lead. Heat stays 0. Ethereum and BNB Chain are skipped. `message-match` compares 32-byte ids that were already observed. The same id on two chains is a lead. A longer word is dropped, so calldata is not stored. Nothing is replayed and heat stays 0. `bridge-note` records a role or a source word of bridge, inbox, outbox, or messenger. The note stores the name only. No call is built and heat stays 0. The Blend heat board ranks all-time heat and does not drop a row for age or liveness. A failed `eth_getCode` is unknown, not an EOA. A privileged call counts only when its selector is dispatched and a garbage selector reverts. The same fact adds heat once. A passed Halmos access-control check removes that weaker probe.

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
| Allowlisted static detector (Slither / Aderyn / Semgrep) | Yes — `static_evidence`. High-confidence funds rules weigh 3, medium 1, cap 6. Admin-gated and generic hits stay 0 |
| Single-engine generic detector | **No** heat alone |
| Multi-engine agreement on a concrete finding | Raises **confidence**; may unlock heat only when paired with funds + failed invariant / privileged evidence (Phase A policy) |

### Buckets

| Bucket | When |
|---|---|
| `lane-a-cool` | Default rank-by-funds; demoted classes; no promote evidence |
| `lane-b-queue` | Funds ≥ $100 **and** (failed invariant **or** privileged callable **or** EOA admin ≥ $100k) |
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
| Code | `.github/workflows/eth-scanner-deep.yml`, `eth_scanner/deep/*`, CLI `python -m eth_scanner deep`, migration `20261112184417_deep_engines.sql` |

**Out of scope for A:** fuzz campaigns that emit exploit sequences; any transaction broadcast.

### Phase B — Property-based verification on a fork

Per-class invariant suites (ERC-4626, staking, lending/CDP, AMM/LP, bridges/escrow, vesting, governance/timelock) as **read-only** fork tests:

- Live `eth_call` property catalog (`eth_scanner/fork_props`) against current mainnet state
- Touched storage from `debug_traceTransaction` `prestateTracer` (else `eth_getProof` / `eth_getStorageAt`) is copied onto the **local** anvil with `anvil_setStorageAt` and recorded as evidence. Cap 1,500 CU. A missing debug API or a 429 leaves the simulation on its current state. Non-loopback URLs are refused.
- Already-drained detection (`eth_scanner/chain/liveness.py`): a historical external ETH outflow to an account with no code, plus a collapsed balance, sets `heat_breakdown.liveness` to `already-exploited` or `dead`. That flag adds **no** heat and the Blend board lists the row under Already drained instead of the heat ranking. Cap 400 CU. No transfer API or a 429 leaves the row in the normal ranking.
- The Blend top 100 ranks each contract by its **latest** heat. The historical peak stays visible. A live contract whose peak heat is at least 1 and whose latest scan is 14 days or older is listed for rescan (`python -m eth_scanner requeue-stale --runs rows.json` sets those targets back to `pending`). Drained rows are not requeued.
- Optional Foundry defensive mock suite (`research/fuzz`) when `forge` is installed; counterexample traces elided
- Output only: invariant name, `held` / `violated` / `unknown`, minimized **evidence summary** (state values), severity
- CLI: `python -m eth_scanner fork-props --address 0x… --class vault [--forge]`
- Migration: `20261112185036_fork_properties.sql`
- **Do not** store or emit a runnable attack sequence — prose + state values only

### Phase C — Protocol context graph

Build a contract graph from verified source + on-chain reads:

- Proxies / implementations, oracles, tokens held, external calls, roles / admins / timelocks / multisigs
- Risk factors: oracle (spot / manipulable / stale), upgrade/admin (EOA, no timelock, uninitialized impl), dependency (known-incident protocols)
- Score: funds-at-risk × likelihood; feeds heat only through the evidence gate
- Code: `eth_scanner/protocol_graph/`, CLI `protocol-graph`, migration `20261112185337_protocol_graph.sql`

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
- Code: `eth_scanner/triage_ai/`, CLI `explain`; optional env `OPENAI_API_KEY` / `ETH_SCANNER_LLM_API_KEY` (not required)
- Deep worker attaches up to 3 explanations when a key exists

### Phase F — Monitoring

- Re-scan funded contracts on implementation change events and large TVL / funds deltas
- Alert surface on `/test` (no spam: dedupe by address + change fingerprint)
- Code: `eth_scanner/monitor/`, CLI `monitor`, workflow `eth-scanner-monitor.yml`, table `eth_scan_alerts`


### Phase G — Fork-verify (conservation break → proven-drainable)

For contracts already at heat ≥ `ETH_SCANNER_FUZZ_MIN_HEAT` (default 8), run a Foundry invariant campaign on a local anvil (optionally forked from `ETH_RPC_URL`):

- Property: an unprivileged caller cannot increase its ETH balance while the target's ETH balance decreases
- Engine: Foundry (`forge test --fork-url`) first; no extra install. Medusa is not required.
- On a break: `heat_breakdown.exploit_poc` (`drainable=true`, sanitized sequence), heat bump (`ETH_SCANNER_HEAT_EXPLOIT_POC`, default 6, capped at 12), bucket promoted to `manual-review` (existing enum; `bucket_hint=proven-drainable`)
- CLI: `python -m eth_scanner fork-verify --fixture leaky|safe` (no RPC) or `--from-store --min-heat 8 --limit 1`
- Lane A is opt-in (`ETH_SCANNER_FORK_VERIFY=1`) so the monitor stays fast
- Deep CI always runs the planted leaky/safe fixtures; live `--from-store` runs only when `ETH_RPC_URL` is set, 1 contract, 60s budget
- **Do not** broadcast. Live forks use the capped Alchemy `ETH_RPC_URL` only. Ask before raising per-run CU caps.


---


CI workflow patches (need a token with the `workflow` scope to commit `.github/workflows/*`; this PR ships the scanner code and these snippets):

Add to `.github/workflows/eth-scanner-deep.yml` after the Phase B Foundry step (Foundry is already installed in that job):

```yaml
      - name: Fork-verify planted fixtures (no RPC)
        run: |
          set -euo pipefail
          command -v forge && command -v anvil
          python -m eth_scanner fork-verify --fixture leaky --timeout 90 --json
          python -m eth_scanner fork-verify --fixture safe --timeout 90 --json
          cd eth-scanner && PYTHONPATH=src python -m unittest tests.test_fork_verify -q
```

And after the strong-deep / discovery step:

```yaml
      - name: Fork-verify high-heat store rows
        env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SECRET_KEY: ${{ secrets.SUPABASE_SECRET_KEY }}
          ETH_SCANNER_SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          ETH_RPC_URL: ${{ secrets.ETH_RPC_URL }}
          ETH_SCANNER_FUZZ_MIN_HEAT: "8"
          ETH_SCANNER_FUZZ_TIMEOUT_S: "60"
        run: |
          set -euo pipefail
          if [ -z "${ETH_RPC_URL:-}" ]; then
            echo "ETH_RPC_URL unset — skipping live fork-verify (no public RPC fallback; fork campaigns are chatty)."
            exit 0
          fi
          if [ -z "${SUPABASE_URL:-}" ] || [ -z "${SUPABASE_SECRET_KEY:-}" ]; then
            echo "Supabase secrets missing — skipping live fork-verify."
            exit 0
          fi
          python -m eth_scanner fork-verify --from-store --min-heat 8 --limit 1 --timeout 60 --json
```

Add to `.github/workflows/eth-scanner-benchmark.yml` (no Foundry, no RPC):

```yaml
      - name: Fork-verify unit tests (no RPC / no Foundry)
        run: |
          cd eth-scanner && PYTHONPATH=src python -m unittest \
            tests.test_fork_verify.GateAndConfig \
            tests.test_fork_verify.SelectorsAndHarness \
            tests.test_fork_verify.ApplyAndHeat -q
```

## Secrets checklist (Phase A)

Add these as **GitHub Actions repository secrets** (Settings → Secrets and variables → Actions). Do **not** put them in the Next.js client or `NEXT_PUBLIC_*`.

| Secret name | Required | Purpose |
|---|---|---|
| `SUPABASE_URL` | **Yes** | Project URL (same as Vercel `SUPABASE_URL` / `ETH_SCANNER_SUPABASE_URL`) |
| `SUPABASE_SECRET_KEY` | **Yes** | Service-role / secret key for claim + write (`eth_scan_*`, `test_scan_*`). Prefer secret key over legacy service_role if both exist. |
| `ETHERSCAN_API_KEYS` | Recommended | Verified-source fetch for claimed addresses (comma-separated). Falls back to free-tier test key if unset. |
| `ETH_RPC_URL` | Recommended | Alchemy Pay-as-You-Go (`eth-mainnet.g.alchemy.com`), hard $50/month org cap (~96M CU). Read-only `eth_call`, logs, and — when enabled — `trace_*` / `debug_*`. **Fork-verify never falls back to a public RPC**; it skips when this secret is missing. |
| `BSC_RPC_URL` | Optional | BNB Chain. The same Alchemy key's `bnb-mainnet.g.alchemy.com` host. Unset uses a public dataseed and backs off once on 429. |
| `ARBITRUM_RPC_URL` | Optional | Arbitrum One. The same key's `arb-mainnet.g.alchemy.com` host. Unset uses the public Arbitrum RPC. |
| `BASE_RPC_URL` | Optional | Base. The same key's `base-mainnet.g.alchemy.com` host. Unset uses `mainnet.base.org`. |
| `ETH_SCANNER_SLITHER_BIN` | Optional | Override Slither binary path in the runner image |
| `ETH_SCANNER_ADERYN_BIN` | Optional | Override Aderyn binary path |
| `ETH_SCANNER_MYTHRIL_BIN` | Optional | Override Mythril binary path |
| `ETH_SCANNER_HALMOS_BIN` | Optional | Override Halmos binary path |

**Not required for Phase A:** OpenAI/Anthropic keys (Phase E), any paid service besides the capped Alchemy RPC, paid CI minutes.

Vercel already needs the same Supabase + Etherscan vars for `/test`. Actions secrets are a **separate** store — copy the values into Actions secrets; do not rely on Vercel env for GHA.

Workflow permissions: `contents: read` only. No deploy keys. No write to the repo unless a later phase needs artifact upload (prefer Supabase).

---

## Free-tier budget notes

| Resource | Constraint | Mitigation |
|---|---|---|
| GHA minutes | ~2 000 min/month private free | Schedule every 30–60 min; claim ≤3 jobs; hard timeouts; skip when queue empty |
| Alchemy PAYG | $50/month hard cap, ~96M CU | Per-run caps (trace seeds 2,500 CU, storage preload 1,500 CU, liveness 400 CU). Fifty scans/day is about 6.6M CU/month. Cache repeats. Back off on 429. `debug_traceTransaction` is budgeted at 1,000 CU. |
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

Lane A evidence-heat (#37 / #38) and the funds floor (#36, now $100) are **prerequisites** already on `main`.

`similarity-search` compares a function's statement graph with confirmed function text and a few saved shapes. A renamed or reordered body can still be a neighbor. The score is a lead for the existing detectors, and it adds no heat.

A scan stores one row per stage. The quick stage sets a provisional heat immediately. Similarity, cross-contract reachability, Halmos, hevm, Kontrol, fork, and fuzz stay pending until their own job finishes. Fusion sums distinct evidence facts. An empty stage does not lower that sum, and a hold counts only when it is more confident than the fact it contradicts.

`cross-contract` asks whether an open function reaches a value move, a signature check, or a library in a different contract, and whether a caller-controlled value is an argument. A public address getter can be read with `eth_call`. The path is a lead and adds no heat.

During a scan, the similarity and cross-contract stages finish from the source already in hand. A neighbor or a path is stored on the row and adds no heat. Halmos, hevm, Kontrol, fork, and fuzz stay pending for their own jobs.

`eth-scanner-rescore` re-reads stored heat with the existing `ETH_RPC_URL` and Supabase secrets. It only lowers a contradicted stamp. A failed read leaves the old points. A push to `main` that changes the rescore or heat files starts it, and a daily run repeats it. One run at a time. When that read contradicts the old peak, every stored scan for the contract is rewritten and the original peak is kept as `original_peak`. The evidence is read from `heat_breakdown` or from `blend_receipt`, because Blend stores the breakdown on the receipt. A saved confirmation that only says `eth_call succeeded (no revert)` is the retired probe, so that privileged stamp is withdrawn even when the live read fails. An EOA stamp counts only when the saved record shows `code_status` ok and empty code, or a live read confirms it. A multisig, Safe, or timelock does not. A bare heat number does not outrank a scan that stored component zeros. A confirmation that records the control selector is kept until a live read contradicts it. A real invariant failure stays. Heat with no stored evidence is left alone. The board shows `original_peak` for a peak a rescore recomputed.
