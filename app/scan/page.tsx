import type { Metadata } from "next";
import ScanApp from "./scan-app";

export const metadata: Metadata = {
  title: "Scan",
  description: "Passive website checks. Heat comes from evidence. Not a verdict.",
  robots: { index: false, follow: false },
};

export default function ScanPage() {
  return <ScanApp />;
}
