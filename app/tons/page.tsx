import type { Metadata } from "next";
import { TonComposer } from "@/components/tons/ton-composer";
import { site, tonManifestUrl } from "@/lib/site";
import Link from "next/link";

const title = `Bounce, then redeem — ${site.name}`;
const description =
  "The uTON burn with proxy id 3, the bounced notification, the wallet on_bounce read, and a later redeem on a whitelisted proxy.";

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
        <p className="ton-kicker">Proxy id 3, then a whitelisted id</p>
        <h1>Bounce, then redeem</h1>
        <TonComposer manifestUrl={tonManifestUrl} />
      </main>
    </div>
  );
}
