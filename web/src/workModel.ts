import type { Opportunity } from "./api/client";

export type WorkModel = "Remote" | "Hybrid" | "On site";

// Location text is trusted ("Remote in USA", "Hybrid - New York", glued "SFRemote"); a title only counts when the
// word is a tag, not part of the role ("Hybrid Cloud Engineer" stays unlabelled).
const TITLE_TAG = /\((?:[^)]*\b)?(hybrid|remote|on-?site)\b|[-–|]\s*(hybrid|remote|on-?site)\s*$|\b(hybrid|remote|on-?site)\s*$/i;

export function workModel(o: Pick<Opportunity, "location" | "title"> & { location_raw?: string }): WorkModel | null {
  const t = TITLE_TAG.exec(o.title);
  const word = (/hybrid|remote|on-?site/i.exec(o.location_raw ?? o.location)?.[0] ?? (t && (t[1] || t[2] || t[3])) ?? "").toLowerCase();
  if (word === "hybrid") return "Hybrid";
  if (word === "remote") return "Remote";
  return word ? "On site" : null;
}
