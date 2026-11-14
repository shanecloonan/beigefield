import type { Metadata } from "next";
import BlendApp from "./blend-app";

export const metadata: Metadata = {
  title: "Blend",
  description: "Fused Ethereum scanner. Local simulation only. Not a verdict.",
  robots: { index: false, follow: false },
};

export default function BlendPage() {
  return <BlendApp />;
}
