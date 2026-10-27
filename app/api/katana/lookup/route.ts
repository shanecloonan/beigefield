import "server-only";
import { loadKatanaAuthorizedLookup } from "@/lib/katana-query";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const url = new URL(request.url);
  return respond(url.searchParams.get("owner") ?? "", url.searchParams.get("state") ?? "");
}

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return Response.json({ ok: false, message: "The lookup could not be read." }, { status: 400 });
  }
  const record = body && typeof body === "object" ? (body as { owner?: unknown; state?: unknown }) : {};
  const owner = typeof record.owner === "string" ? record.owner : "";
  const state = typeof record.state === "string" ? record.state : "";
  return respond(owner, state);
}

async function respond(requestedOwner: string, requestedState: string) {
  const result = await loadKatanaAuthorizedLookup({
    owner: requestedOwner,
    state: requestedState,
  });
  return Response.json(result, { status: result.ok ? 200 : result.status });
}
