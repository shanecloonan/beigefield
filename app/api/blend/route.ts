import { NextResponse } from "next/server";
import { isScanListId } from "@/lib/eth-scanner/lists";
import { blendEtherscanKeys, blendRandomEnabled, runBlendCli } from "@/lib/eth-scanner/run-blend";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 300;

function json(body: unknown, status = 200) {
  return NextResponse.json(body, {
    status,
    headers: { "Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow" },
  });
}

export async function GET(req: Request) {
  const url = new URL(req.url);
  const list = url.searchParams.get("list");
  if (!list) {
    const ran = await runBlendCli(["--catalog", "--json"]);
    if (!ran.ok) return json({ ok: false, error: ran.error, random: randomStatus() }, 503);
    return json({ ...(ran.data as object), random: randomStatus() });
  }
  if (!isScanListId(list)) return json({ ok: false, error: "Unknown list." }, 400);
  const offset = Number(url.searchParams.get("offset") || "0");
  const limit = Number(url.searchParams.get("limit") || "40");
  const ran = await runBlendCli([
    "--select",
    "--list",
    list,
    "--offset",
    String(Number.isFinite(offset) ? offset : 0),
    "--limit",
    String(Number.isFinite(limit) ? limit : 40),
    "--json",
  ]);
  if (!ran.ok) return json({ ok: false, error: ran.error }, 503);
  return json({ ok: true, ...(ran.data as object), random: randomStatus() });
}

export async function POST(req: Request) {
  let body: { address?: unknown; list?: unknown; fixture?: unknown } = {};
  try {
    body = await req.json();
  } catch {
    return json({ ok: false, error: "Expected JSON." }, 400);
  }
  const fixture = typeof body.fixture === "string" ? body.fixture : "";
  const address = typeof body.address === "string" ? body.address.trim() : "";
  const list = typeof body.list === "string" && isScanListId(body.list) ? body.list : "";
  const args = ["--json"];
  if (fixture) args.push("--fixture", fixture);
  else if (address) args.push("--address", address);
  else return json({ ok: false, error: "Pass a fixture or an address." }, 400);
  if (list) args.push("--list", list);
  const ran = await runBlendCli(args);
  if (!ran.ok) return json({ ok: false, error: ran.error }, 503);
  return json({ ok: true, receipt: ran.data });
}

function randomStatus() {
  const enabled = blendRandomEnabled();
  const keyed = Boolean(blendEtherscanKeys());
  let reason = "Random scanning is on.";
  if (!enabled) reason = "Random scanning is off. Set ETH_SCANNER_BLEND_RANDOM=1 to enable it.";
  else if (!keyed) reason = "No Etherscan API key is set. Add ETHERSCAN_API_KEYS. Nothing will be scanned.";
  return { enabled, etherscan_configured: keyed, reason };
}
