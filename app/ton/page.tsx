import type { Metadata } from "next";
import { TonComposer } from "@/components/ton/ton-composer";
import { site, tonManifestUrl } from "@/lib/site";

const title = `TON messages — ${site.name}`;
const description =
  "Script outgoing messages on The Open Network mainnet with a connected wallet.";

export const metadata: Metadata = {
  title,
  description,
  alternates: {
    canonical: "/ton",
  },
  openGraph: {
    title,
    description,
    url: `${site.url}/ton`,
  },
  twitter: {
    card: "summary_large_image",
    title,
    description,
  },
};

export default function TonPage() {
  return <TonComposer manifestUrl={tonManifestUrl} />;
}
