import type { Opportunity } from "./api/client";
import { LAST_VISIT } from "./lastVisit";

export type Stock = { key: "fresh" | "saved" | "applied" | "interview" | "offer" | "quiet" | "plain"; label: string; bg: string };

/** The card's stock colour is its state: a drop found since your last visit yellow, then your own statuses; everything else plain paper.
 * The label is the same fact in words, so colour is never the only signal. */
export function stockOf(o: Opportunity, since = LAST_VISIT): Stock {
  switch (o.action?.status) {
    case "saved": return { key: "saved", label: "Saved", bg: "bg-stock-saved" };
    case "applied": return { key: "applied", label: "Applied", bg: "bg-stock-applied" };
    case "interview": return { key: "interview", label: "Interview", bg: "bg-stock-interview" };
    case "offer": return { key: "offer", label: "Offer", bg: "bg-stock-offer" };
    case "rejected": return { key: "quiet", label: "Rejected", bg: "bg-stock-quiet" };
    case "ignored": return { key: "quiet", label: "Hidden", bg: "bg-stock-quiet" };
  }
  if (!o.backfill && new Date(o.first_seen).getTime() > since) return { key: "fresh", label: "New", bg: "bg-stock-fresh" };
  return { key: "plain", label: "", bg: "bg-card" };
}
