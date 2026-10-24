import type { Metadata } from "next";
import { TonComposer } from "@/components/tons/ton-composer";
import { UtonNotes } from "@/components/tons/uton-notes";
import { site, tonManifestUrl } from "@/lib/site";
import Link from "next/link";

const title = `Stake native TON — ${site.name}`;
const description =
  "Step 1 of a uTON deposit: a stake message, opcode 0x1003, sent to proxy_ton with a query id, a user address, and a response address.";

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

export default function TonPage() {
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
        <p className="ton-kicker">Step 1 · mainnet</p>
        <h1>Stake native TON</h1>
        <p className="ton-lede">
          Deposit native TON with proxy_ton. The desk below is that one
          message: opcode 0x1003, a query id, the user who receives the uTON,
          and the address that receives excess gas.
        </p>
        <UtonNotes />
        <TonComposer manifestUrl={tonManifestUrl} />
      </main>
    </div>
  );
}
