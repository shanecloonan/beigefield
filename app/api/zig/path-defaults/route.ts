import "server-only";
import { loadZigPathDefaults } from "@/lib/valdora-query";
import { deskPublicAddress } from "@/lib/zig-funded-wallet";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const owner = new URL(request.url).searchParams.get("owner") ?? "";
  return respond(owner);
}

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return Response.json(
      { ok: false, message: "The lookup could not be read." },
      { status: 400 },
    );
  }
  const owner =
    body && typeof body === "object" && typeof (body as { owner?: unknown }).owner === "string"
      ? (body as { owner: string }).owner
      : "";
  return respond(owner);
}

async function respond(requested: string) {
  const trimmed = requested.trim();
  const owner = trimmed || (await deskPublicAddress());
  const result = await loadZigPathDefaults({ owner });
  return Response.json(result, { status: result.ok ? 200 : result.status });
}
