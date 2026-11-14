/**
 * Group Blend findings by engine and rule.
 * Agreement raises the score shown here. It does not decide heat.
 */

export const BLEND_ENGINES = ["ityfuzz", "halmos", "medusa", "echidna"] as const;

export type BlendLabel = "drain proof" | "evidence only";

export type BlendGroupInput = {
  engine: string;
  rule: string;
  kind?: string | null;
  label?: string | null;
  agreement_score?: number | null;
  agreement_count?: number | null;
  engines_agreeing?: string[] | null;
  title?: string | null;
  severity?: string | null;
};

export type BlendGroup = {
  engine: string;
  rule: string;
  agreement_score: number;
  agreement_count: number;
  engines_agreeing: string[];
  kind: string;
  label: BlendLabel;
  title: string;
  severity: string;
};

const BLEND = new Set<string>(BLEND_ENGINES);

function labelOf(row: BlendGroupInput): BlendLabel {
  if (row.label === "drain proof" || row.kind === "drain-proof") return "drain proof";
  return "evidence only";
}

/** One row per engine that agreed on a finding, keyed for an engine+rule table. */
export function groupByEngineRule(findings: BlendGroupInput[]): BlendGroup[] {
  const out: BlendGroup[] = [];
  for (const finding of findings) {
    const engines = (finding.engines_agreeing?.length ? finding.engines_agreeing : [finding.engine]).filter(Boolean);
    const blendEngines = engines.filter((engine) => BLEND.has(engine));
    if (!blendEngines.length) continue;
    const score =
      typeof finding.agreement_score === "number"
        ? finding.agreement_score
        : Math.round((blendEngines.length / BLEND_ENGINES.length) * 100) / 100;
    const label = labelOf(finding);
    for (const engine of blendEngines) {
      out.push({
        engine,
        rule: finding.rule,
        agreement_score: score,
        agreement_count: finding.agreement_count ?? blendEngines.length,
        engines_agreeing: blendEngines,
        kind: finding.kind || (label === "drain proof" ? "drain-proof" : "evidence-only"),
        label,
        title: finding.title || finding.rule,
        severity: finding.severity || "info",
      });
    }
  }
  out.sort((a, b) => a.engine.localeCompare(b.engine) || a.rule.localeCompare(b.rule));
  return out;
}
