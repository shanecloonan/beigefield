import type { Metadata } from "next";
import { TonComposer } from "@/components/tons/ton-composer";
import { UtonNotes } from "@/components/tons/uton-notes";
import { site, tonManifestUrl } from "@/lib/site";
import Link from "next/link";

const title = `uTON — ${site.name}`;
const description =
  "Notes on UTONIC uTON: the mainnet minter, how a native TON stake is minted, and how burn and withdraw return native TON. A mainnet message desk sits on the same page.";

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
        <p className="ton-kicker">UTONIC · mainnet</p>
        <h1>uTON</h1>
        <p className="ton-lede">
          The liquid restaking jetton on UTONIC. Minted with native TON or an
          LST such as stTON or tsTON, and withdrawn as native TON. The notes
          follow the published contracts at one commit.
        </p>
        <UtonNotes />
        <TonComposer manifestUrl={tonManifestUrl} />
      </main>
    </div>
  );
}
