# List 2 — Janky / Sketchy / Weird ($50–$1,900)

Strictly defensive, read-only candidate feed for the Beigefield ETH invariant scanner.

## Strategy (differs from List 1)
List 1 = funded, money-holding, less-audited contracts ranked by drain-probability prior
  (includes some recognizable protocols; $2k–$9M historically, now configurable).

List 2 = the OPPOSITE curation bias in the small-dollar band:
  - Target the most janky, sketchy, or weird contracts
  - Abandoned / unaudited / odd-pattern / previously-hacked-lineage
  - NO big names, NO canonical protocols (Aave/Compound/Uniswap/Curve/Lido/Yearn/Morpho/…)
  - Funds strictly in [$50, $1,900] USD (live-verified where possible)

## Method
1. Seeded from excluded.csv rows that were dropped only for being below the old $2,000 floor
   (`list2_rules.below_floor_marker` is still `below-2000`, the historical seed tag)
2. Filtered to janky profile (dropped Sushi/Pancake/DODO/Euler V2/Sommelier/Silo/etc.)
3. Live-verified via public Ethereum RPC + Blockscout token balances
4. Expanded via DefiLlama low-TVL Ethereum protocols + adapter address extraction
5. Scored with drain-probability prior (0–100), same schema as hand_ranked_candidates.csv

The live scanner / Lane-B / advanced-engine funds floor is $100. List 2's
membership band stays [$50, $1,900]; contracts in that band at or above $100
are engine-eligible. Contracts under $100 still fail the funds floor.

## Schema
address, protocol, contract_class, funds_usd, drain_probability, candidate_reason,
evidence_note, source, already_on_master

Prior is a PRE-SCAN likelihood, NOT a finding. Heat still requires a live-chain rule failure
or a fork-proven caller-profit invariant break.
