import type { Metadata } from "next";
import { BurnDesk } from "@/components/burn/burn-desk";
import { site } from "@/lib/site";
import Link from "next/link";

const title = `Burn uTON — ${site.name}`;
const description =
  "Burn uTON from the desk wallet to redeem native TON. The same amount is burned on proxy id 3, then on the minter's listed proxy.";

export const metadata: Metadata = {
  title,
  description,
  alternates: {
    canonical: "/burn",
  },
  openGraph: {
    title,
    description,
    url: `${site.url}/burn`,
  },
  twitter: {
    card: "summary_large_image",
    title,
    description,
  },
};

export default function BurnPage() {
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
        <p className="ton-kicker">Desk wallet · mainnet</p>
        <h1>Burn uTON</h1>
        <p className="ton-lede">
          This burns uTON held by the desk wallet in order to redeem native TON.
          The amount is burned on proxy id 3, whose notification bounces and
          returns the uTON, and again on the minter&apos;s listed proxy, which is
          the redeem. The desk wallet signs every message. The withdraw waits on
          a time lock and is not sent from this page.
        </p>
        <BurnDesk />
      </main>
    </div>
  );
}
