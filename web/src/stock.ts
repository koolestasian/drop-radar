import type { Opportunity } from "./api/client";

export type Stock = { key: "fresh" | "saved" | "applied" | "interview" | "offer" | "quiet" | "plain"; label: string; bg: string };

const FRESH_MS = 3 * 60 * 60 * 1000;

/** The card's stock colour is its state: fresh drops yellow, then your own statuses; everything else plain paper.
 * The label is the same fact in words, so colour is never the only signal. */
export function stockOf(o: Opportunity, now = Date.now()): Stock {
  switch (o.action?.status) {
    case "saved": return { key: "saved", label: "Saved", bg: "bg-stock-saved" };
    case "applied": return { key: "applied", label: "Applied", bg: "bg-stock-applied" };
    case "interview": return { key: "interview", label: "Interview", bg: "bg-stock-interview" };
    case "offer": return { key: "offer", label: "Offer", bg: "bg-stock-offer" };
    case "rejected": return { key: "quiet", label: "Rejected", bg: "bg-stock-quiet" };
    case "ignored": return { key: "quiet", label: "Ignored", bg: "bg-stock-quiet" };
  }
  if (!o.backfill && now - new Date(o.first_seen).getTime() < FRESH_MS) return { key: "fresh", label: "New", bg: "bg-stock-fresh" };
  return { key: "plain", label: "", bg: "bg-card" };
}
