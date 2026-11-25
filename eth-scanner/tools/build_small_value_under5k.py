#!/usr/bin/env python3
"""Write the under-$5k high-likelihood queue from the committed candidate pools.

Read-only. Uses the funds figures already on the rows (native ETH plus the
major tokens the scanner prices). Does not call a chain and does not send
a transaction.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.desk.small_value_under5k import (  # noqa: E402
    QUEUE_LIMIT,
    REASON_PEAK,
    REASON_SCORE,
    SMALL_VALUE_BATCH,
    SMALL_VALUE_BATCH_CU,
    collect_repo_candidates,
    queue_path,
    rank_candidates,
)


def _md(payload: dict) -> str:
    entries = payload["entries"]
    counts = payload["breakdown"]
    lines = [
        "# Under-$5,000 high-likelihood scan queue (%d contracts)" % payload["count"],
        "",
        "Generated %s · chain: ethereum · %d contracts" % (payload["generated_at"], payload["count"]),
        "",
        "## Cutoff rules",
        "",
        "- **Under $5,000:** `funds_usd` / `est_usd_held` is the scanner's native ETH plus major-token probe (WETH, USDC, USDT, DAI, WBTC, stETH, wstETH, USDe). Floor is the $100 engine minimum. Cap is exclusive of $5,000.",
        "- **High likelihood:** the same classes as the first small-value queue. Upgradeable proxy, spot oracle, ERC-4626 vault, and lending are structural signals. Rari Capital and Percent Finance are the past-hack Compound-fork lending family already used on list 2. `univ2-fork-unknown` and a protocol named ERC-4626 vault are the AMM-fork and share-inflation classes when the row only has a protocol name. A decompilable contract with none of those is the unverified leftover (score 35).",
        "- **Not this queue:** anything already in `small_value_queue.json`, the signal-rerun seed, or the seen skip list; list-2 canonical names; a negative drain prior; other chains (this job uses the Ethereum RPC).",
        "- **Order:** score descending, then smaller funds, then address. The queue stops at %d. %d further rows met the bar and stay off this queue so one list stays at the size Shane asked for."
        % (QUEUE_LIMIT, payload["deferred_count"]),
        "",
        "## Selection sources / breakdown",
        "",
        "| reason_class | n | class score | peak |",
        "|---|---|---|---|",
    ]
    for reason, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        lines.append("| %s | %d | %d | %d |" % (reason, count, REASON_SCORE[reason], REASON_PEAK[reason]))
    lines.extend([
        "",
        "- Lists: %s" % ", ".join("%s=%d" % item for item in sorted(payload["lists"].items())),
        "- Funds: <=$1,900: %d, <=$5,000: %d (median $%s)"
        % (payload["funds_le_1900"], payload["count"], payload["median_funds"]),
        "",
        "## How to run it",
        "",
        "Signal-rerun reads this file and scans **one batch**, then stops. Finished addresses are the `signal-rerun:<address>` rows already stored as done, so the next trigger continues where this one stopped.",
        "",
        "- **Batch:** %d contracts, proxy cap %s CU (about 2,600 CU each; the measured rerun was ~2,590). Four batches cover this queue. That is under one historical 4,000,000 CU run."
        % (SMALL_VALUE_BATCH, f"{SMALL_VALUE_BATCH_CU:,}"),
        "- **Trigger:** push `eth-scanner/signal-rerun.trigger` to `main`. The workflow runs `--small-value-batch`.",
        "- **Or manually:** Actions → *eth-scanner-signal-rerun* → *Run workflow* → mode `small-value-batch`. Mode `historical` is the old full-signal rerun.",
        "- **Or local:** `cd eth-scanner && python -m eth_scanner signal-rerun --small-value-batch --batch-size %d --budget-cu %d --deadline-minutes 55 --dry-run --json`"
        % (SMALL_VALUE_BATCH, SMALL_VALUE_BATCH_CU),
        "",
        "Watch the Actions log for `mode`, `selected`, `rerun_count`, `skipped_finished`, `cu_used`, and `status`. `skipped_finished` climbs by about %d after each batch that finishes."
        % SMALL_VALUE_BATCH,
        "",
        "## First batch",
        "",
        "| # | address | name | funds_usd | reason_class | peak |",
        "|---|---|---|---|---|---|",
    ])
    for index, row in enumerate(entries[:SMALL_VALUE_BATCH], start=1):
        lines.append(
            "| %d | `%s` | %s | %s | %s | %d |"
            % (index, row["address"], row["contract_name"].replace("|", "/"), _money(row["funds_usd"]), row["reason_class"], row["peak_heat"])
        )
    lines.extend([
        "",
        "## Queue",
        "",
        "| # | address | name | funds_usd | reason_class | signals | unverified | list | peak |",
        "|---|---|---|---|---|---|---|---|---|",
    ])
    for index, row in enumerate(entries, start=1):
        signals = ",".join(row["signals"]) or "—"
        lines.append(
            "| %d | `%s` | %s | %s | %s | %s | %s | %s | %d |"
            % (
                index,
                row["address"],
                row["contract_name"].replace("|", "/"),
                _money(row["funds_usd"]),
                row["reason_class"],
                signals,
                "Y" if row["unverified"] else "—",
                row["list"],
                row["peak_heat"],
            )
        )
    lines.append("")
    return "\n".join(lines)


def _money(value: float) -> str:
    return str(int(round(float(value))))


def main() -> None:
    kept, deferred = rank_candidates(collect_repo_candidates(), limit=QUEUE_LIMIT)
    funds = sorted(float(row["funds_usd"]) for row in kept)
    median = funds[len(funds) // 2] if funds else 0
    payload = {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "chain": "ethereum",
        "count": len(kept),
        "batch_size": SMALL_VALUE_BATCH,
        "batch_cu": SMALL_VALUE_BATCH_CU,
        "cutoffs": {
            "funds_min_usd": 100,
            "funds_max_usd_exclusive": 5000,
            "queue_limit": QUEUE_LIMIT,
            "measure": "native ETH + WETH/USDC/USDT/DAI/WBTC/stETH/wstETH/USDe as priced on the candidate rows",
        },
        "breakdown": dict(Counter(row["reason_class"] for row in kept)),
        "lists": dict(Counter(row["list"] for row in kept)),
        "funds_le_1900": sum(1 for row in kept if float(row["funds_usd"]) <= 1900),
        "median_funds": int(round(median)),
        "deferred_count": len(deferred),
        "entries": kept,
    }
    path = queue_path()
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    md_path = path.with_suffix(".md")
    md_path.write_text(_md(payload), encoding="utf-8")
    print(json.dumps({
        "count": payload["count"],
        "deferred": payload["deferred_count"],
        "breakdown": payload["breakdown"],
        "lists": payload["lists"],
        "funds_le_1900": payload["funds_le_1900"],
        "median_funds": payload["median_funds"],
        "max_funds": max(funds) if funds else None,
        "path": str(path),
    }, indent=2))


if __name__ == "__main__":
    main()
