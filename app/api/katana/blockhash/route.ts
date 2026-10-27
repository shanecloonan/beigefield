import "server-only";
import { loadLatestBlockhash } from "@/lib/katana-query";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  const result = await loadLatestBlockhash();
  return Response.json(result, { status: result.ok ? 200 : result.status });
}
