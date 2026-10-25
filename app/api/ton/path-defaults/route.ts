import { loadPathDefaults } from "@/lib/uton-path-defaults";
import { createPathDefaultDeps } from "@/lib/uton-path-chain";

export const runtime = "nodejs";

export async function GET(request: Request) {
  const owner = new URL(request.url).searchParams.get("owner") ?? "";
  const result = await loadPathDefaults(owner, createPathDefaultDeps());
  return Response.json(
    result.ok
      ? { ok: true, jettonWallet: result.jettonWallet, proxyId: result.proxyId }
      : { ok: false, message: result.message },
    { status: result.ok ? 200 : result.status },
  );
}
