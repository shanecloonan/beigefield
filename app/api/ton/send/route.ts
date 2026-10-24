import { sendFundedScript } from "@/lib/funded-send";

export const runtime = "nodejs";

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return Response.json(
      {
        ok: false,
        kind: "rejected",
        message: "The message could not be read. Nothing was sent.",
      },
      { status: 400 },
    );
  }

  const result = await sendFundedScript(body, {
    endpoint: process.env.TONCENTER_ENDPOINT,
    apiKey: process.env.TONCENTER_API_KEY,
  });
  const status = result.ok ? 200 : result.kind === "ambiguous" ? 502 : 400;
  return Response.json(result, { status });
}
