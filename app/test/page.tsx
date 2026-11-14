import type { Metadata } from "next";
import TestApp from "./test-app";

export const metadata: Metadata = {
  title: "ETH scanner master lists",
  description: "Named master lists for the Ethereum invariant scanner. List 1 is the funded feed. List 2 is the sketchy small-dollar feed. Not a verdict UI.",
  robots: { index: false, follow: false },
};

export default function TestPage() {
  return <TestApp />;
}
