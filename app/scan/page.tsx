import type { Metadata } from "next";
import { loadSiteBoard } from "@/lib/site-scanner/load";
import ScanBoard from "./scan-board";

export const metadata: Metadata = {
  title: "Scan",
  description: "Passive website checks. Heat comes from evidence. Not a verdict.",
  robots: { index: false, follow: false },
};

export const dynamic = "force-dynamic";
export const revalidate = 0;

export default async function ScanPage() {
  const board = await loadSiteBoard();
  return <ScanBoard board={board} />;
}
