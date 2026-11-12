/**
 * Phase D — mirror of eth_scanner.benchmark.eval for the /test desk.
 * Labeled set is the curated safe/affected list (no PoC content).
 */

import labeled from "../../eth-scanner/benchmarks/labeled.json";

export type BenchmarkRow = {
  address: string;
  name?: string;
  label: "safe" | "affected";
  bucket?: string | null;
  predicted_hot: boolean;
  outcome: "tp" | "fp" | "tn" | "fn";
};

export type BenchmarkStats = {
  labeled: number;
  safe_total: number;
  affected_total: number;
  true_positive: number;
  false_positive: number;
  true_negative: number;
  false_negative: number;
  precision: number | null;
  recall: number | null;
  false_positive_rate: number | null;
  baseline_precision_min: number;
  passes_baseline: boolean;
  rows: BenchmarkRow[];
};

const HOT = new Set(["lane-b-queue", "manual-review", "human-yes-candidate"]);

function isHot(bucket: string | null | undefined): boolean {
  return HOT.has(String(bucket || ""));
}

export function evaluateLabeledBenchmark(
  predictions: Record<string, string | null | undefined>,
): BenchmarkStats {
  const entries = (labeled as { entries: { address: string; name?: string; label: string }[]; baseline_precision_min?: number })
    .entries;
  const baseline = Number((labeled as { baseline_precision_min?: number }).baseline_precision_min ?? 0.5);
  const rows: BenchmarkRow[] = [];
  let tp = 0;
  let fp = 0;
  let tn = 0;
  let fn = 0;
  let safeTotal = 0;
  let affectedTotal = 0;

  for (const ent of entries) {
    const address = String(ent.address || "").toLowerCase();
    const label = String(ent.label || "").toLowerCase();
    if (!address || (label !== "safe" && label !== "affected")) continue;
    const bucket = predictions[address] ?? null;
    const hot = isHot(bucket);
    let outcome: BenchmarkRow["outcome"];
    if (label === "safe") {
      safeTotal += 1;
      if (hot) {
        fp += 1;
        outcome = "fp";
      } else {
        tn += 1;
        outcome = "tn";
      }
    } else {
      affectedTotal += 1;
      if (hot) {
        tp += 1;
        outcome = "tp";
      } else {
        fn += 1;
        outcome = "fn";
      }
    }
    rows.push({
      address,
      name: ent.name,
      label: label as "safe" | "affected",
      bucket,
      predicted_hot: hot,
      outcome,
    });
  }

  const denomP = tp + fp;
  const denomR = tp + fn;
  const denomFpr = fp + tn;
  const precision = denomP ? tp / denomP : null;
  const recall = denomR ? tp / denomR : null;
  const false_positive_rate = denomFpr ? fp / denomFpr : null;
  const passes_baseline =
    precision == null ? (false_positive_rate ?? 0) <= 1 - baseline : precision >= baseline;

  return {
    labeled: rows.length,
    safe_total: safeTotal,
    affected_total: affectedTotal,
    true_positive: tp,
    false_positive: fp,
    true_negative: tn,
    false_negative: fn,
    precision,
    recall,
    false_positive_rate,
    baseline_precision_min: baseline,
    passes_baseline,
    rows,
  };
}
