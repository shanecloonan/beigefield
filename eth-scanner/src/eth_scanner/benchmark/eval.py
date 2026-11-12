"""Evaluate scanner buckets against the labeled benchmark (no PoCs)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional


DEFAULT_PATH = Path(__file__).resolve().parents[3] / "benchmarks" / "labeled.json"


@dataclass
class BenchmarkReport:
    labeled: int = 0
    safe_total: int = 0
    affected_total: int = 0
    true_positive: int = 0  # affected predicted hot
    false_positive: int = 0  # safe predicted hot
    true_negative: int = 0
    false_negative: int = 0
    precision: Optional[float] = None
    recall: Optional[float] = None
    false_positive_rate: Optional[float] = None
    baseline_precision_min: float = 0.5
    passes_baseline: bool = True
    rows: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_labeled(path: Optional[Path] = None) -> dict[str, Any]:
    p = Path(path or DEFAULT_PATH)
    return json.loads(p.read_text(encoding="utf-8"))


def _is_hot(bucket: Optional[str]) -> bool:
    return (bucket or "") in {"lane-b-queue", "manual-review", "human-yes-candidate"}


def evaluate_labeled_benchmark(
    predictions: dict[str, str],
    *,
    labeled_path: Optional[Path] = None,
) -> BenchmarkReport:
    """predictions: address(lower) -> bucket string from a scan/store."""
    data = load_labeled(labeled_path)
    entries = data.get("entries") or []
    baseline = float(data.get("baseline_precision_min") or 0.5)
    report = BenchmarkReport(baseline_precision_min=baseline)
    for ent in entries:
        if not isinstance(ent, dict):
            continue
        addr = str(ent.get("address") or "").lower()
        label = str(ent.get("label") or "").lower()
        if not addr or label not in {"safe", "affected"}:
            continue
        bucket = predictions.get(addr)
        hot = _is_hot(bucket)
        report.labeled += 1
        row = {
            "address": addr,
            "name": ent.get("name"),
            "label": label,
            "bucket": bucket,
            "predicted_hot": hot,
        }
        if label == "safe":
            report.safe_total += 1
            if hot:
                report.false_positive += 1
                row["outcome"] = "fp"
            else:
                report.true_negative += 1
                row["outcome"] = "tn"
        else:
            report.affected_total += 1
            if hot:
                report.true_positive += 1
                row["outcome"] = "tp"
            else:
                report.false_negative += 1
                row["outcome"] = "fn"
        report.rows.append(row)

    denom_p = report.true_positive + report.false_positive
    denom_r = report.true_positive + report.false_negative
    denom_fpr = report.false_positive + report.true_negative
    report.precision = (report.true_positive / denom_p) if denom_p else None
    report.recall = (report.true_positive / denom_r) if denom_r else None
    report.false_positive_rate = (report.false_positive / denom_fpr) if denom_fpr else None
    # When there are no affected labels yet, precision is undefined — pass if FP rate is low.
    if report.precision is None:
        report.passes_baseline = (report.false_positive_rate or 0.0) <= (1.0 - baseline)
    else:
        report.passes_baseline = report.precision >= baseline
    return report
