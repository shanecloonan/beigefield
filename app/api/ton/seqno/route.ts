import { FUNDED_WALLET_ADDRESS } from "@/lib/funded-wallet-public";
import { readAccountState, readSeqno, TON_NETWORK_WAIT } from "@/lib/ton-rpc";

export const runtime = "nodejs";

/** Reads the desk wallet sequence number. It does not broadcast. */
export async function GET() {
  const state = await readAccountState(FUNDED_WALLET_ADDRESS);
  if (!state.ok) {
    return Response.json(
      {
        ok: false,
        message: `${TON_NETWORK_WAIT} The wallet state was not read.`,
      },
      { status: 502 },
    );
  }
  if (state.state !== "active") {
    return Response.json({ ok: true, state: state.state, seqno: 0 });
  }
  const seqno = await readSeqno(FUNDED_WALLET_ADDRESS);
  if (seqno === null) {
    return Response.json(
      {
        ok: false,
        message: `The sequence number could not be read. ${TON_NETWORK_WAIT}`,
      },
      { status: 502 },
    );
  }
  return Response.json({ ok: true, state: state.state, seqno });
}
