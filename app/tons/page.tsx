import type { Metadata } from "next";
import { ZigComposer } from "@/components/tons/zig-composer";
import { site } from "@/lib/site";
import { deskPublicAddress } from "@/lib/zig-funded-wallet";
import Link from "next/link";

const title = `withdraw_unbonded_by_id — ${site.name}`;
const description =
  "One MsgExecuteContract on the Valdora staker. The LCD lookup supplies a completed-unbonding id. The desk wallet signs it on ZIGChain.";

export const metadata: Metadata = {
  title,
  description,
  alternates: {
    canonical: "/tons",
  },
  openGraph: {
    title,
    description,
    url: `${site.url}/tons`,
  },
  twitter: {
    card: "summary_large_image",
    title,
    description,
  },
};

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export default async function TonPage() {
  const deskAddress = await deskPublicAddress();
  return (
    <div className="page">
      <div className="frame" aria-hidden="true">
        <span className="corner corner-tl" />
        <span className="corner corner-tr" />
        <span className="corner corner-bl" />
        <span className="corner corner-br" />
      </div>
      <main className="ton-main">
        <Link className="ton-mark" href="/">
          Beigefield
        </Link>
        <p className="ton-kicker">Valdora staker · code 179</p>
        <h1>withdraw_unbonded_by_id</h1>
        <ZigComposer deskAddress={deskAddress} />
      </main>
    </div>
  );
}
