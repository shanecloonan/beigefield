import type { Metadata } from "next";
import { KatanaComposer } from "@/components/katana/katana-composer";
import { KatanaAuthorizedNotes } from "@/components/katana/katana-notes";
import { site } from "@/lib/site";
import Link from "next/link";

const title = `Katana — ${site.name}`;
const description =
  "Withdraw a same-round pending deposit from a Katana vault on Solana mainnet. The connected wallet pays the fee and receives the underlying on its own associated token account.";

export const metadata: Metadata = {
  title,
  description,
  alternates: {
    canonical: "/katana",
  },
  openGraph: {
    title,
    description,
    url: `${site.url}/katana`,
  },
  twitter: {
    card: "summary_large_image",
    title,
    description,
  },
};

export default function KatanaPage() {
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
        <p className="ton-kicker">Katana · Solana mainnet</p>
        <h1>Katana</h1>
        <p className="ton-lede">
          Withdraw a same-round pending deposit from a Katana vault. The
          connected wallet pays the fee and receives the underlying on its own
          associated token account.
        </p>
        <KatanaAuthorizedNotes />
        <KatanaComposer />
      </main>
    </div>
  );
}
