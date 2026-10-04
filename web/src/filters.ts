import { query } from "./api/client";
import { LAST_VISIT } from "./lastVisit";

export const SCOPES = ["you", "all"] as const;
export const LEVELS = ["intern", "new_grad"] as const;
export const POSTED = ["1", "7", "30"] as const;
export const SORTS = ["posted", "prestige"] as const;
/** Names only; the rules live on the server (radar/pipeline/roles.py), which refuses any other name. */
export const TRACKS = ["Software", "AI / ML / Data", "Quant", "Finance", "Business", "Hardware", "Security", "Product", "Design", "Other"] as const;

export type Filters = {
  scope: (typeof SCOPES)[number];
  q: string;
  location: string;
  level: "" | (typeof LEVELS)[number];
  track: string;
  posted: "" | (typeof POSTED)[number];
  usOnly: boolean;
  closingSoon: boolean;
  dropsOnly: boolean;
  /** The New pill: drops since your last visit. null until chosen, so a landing on a busy day can pre-select it. */
  fresh: boolean | null;
  sort: (typeof SORTS)[number];
};

export const DEFAULTS: Filters = { scope: "you", q: "", location: "", level: "", track: "", posted: "", usOnly: false, closingSoon: false, dropsOnly: false, fresh: null, sort: "posted" };

const oneOf = <T extends string>(value: string | null, allowed: readonly T[], fallback: T): T => (allowed as readonly string[]).includes(value ?? "") ? (value as T) : fallback;

/** Filters live in the hash (`#/jobs?scope=all&level=intern`) so reloads, the back button and shared links keep them.
 * A bare `#/jobs` is an old "All jobs" link. */
export function parseFilters(hash = window.location.hash): Filters {
  const [path, search] = hash.split("?");
  const p = new URLSearchParams(search ?? "");
  const fresh = p.get("new");
  return {
    scope: search === undefined && path.replace(/^#\/?/, "") === "jobs" ? "all" : oneOf(p.get("scope"), SCOPES, "you"),
    q: p.get("q") ?? "",
    location: p.get("location") ?? "",
    level: oneOf(p.get("level"), ["", ...LEVELS], ""),
    track: oneOf(p.get("track"), ["", ...TRACKS], ""),
    posted: oneOf(p.get("posted"), ["", ...POSTED], ""),
    usOnly: p.get("us") === "1",
    closingSoon: p.get("closing") === "1",
    dropsOnly: p.get("drops") === "1",
    fresh: fresh === "1" ? true : fresh === "0" ? false : null,
    sort: oneOf(p.get("sort"), SORTS, "posted"),
  };
}

export function toHash(f: Filters): string {
  return `#/jobs${query({
    scope: f.scope,
    q: f.q,
    location: f.location,
    level: f.level,
    track: f.track,
    posted: f.posted,
    us: f.usOnly ? 1 : undefined,
    closing: f.closingSoon ? 1 : undefined,
    drops: f.dropsOnly ? 1 : undefined,
    new: f.fresh === null ? undefined : f.fresh ? 1 : 0,
    sort: f.sort === "posted" ? undefined : f.sort,
  })}`;
}

/** Everything except the search box and the drops-since-last-visit pill. */
export const isPlain = (f: Filters) => !(f.q || f.location || f.level || f.track || f.posted || f.usOnly || f.closingSoon || f.dropsOnly || f.fresh);

/** How many filters are set beyond the scope and the New pill: the badge on the Filters button. */
export const activeCount = (f: Filters) => [f.location, f.level, f.track, f.posted, f.usOnly, f.closingSoon, f.dropsOnly, f.sort !== "posted"].filter(Boolean).length;

/** The `/api/opportunities` query for these filters; `limit` and `cursor` are the caller's. */
export function apiParams(f: Filters) {
  return {
    include: f.scope === "all" ? "all" : "matches",
    backfill: f.dropsOnly || f.fresh ? false : undefined,
    since: f.fresh ? new Date(LAST_VISIT).toISOString() : undefined,
    sort: f.sort,
    us_only: f.usOnly || undefined,
    q: f.q,
    location: f.location,
    level: f.level,
    track: f.track,
    posted_within: f.posted,
    closing_within: f.closingSoon ? 14 : undefined,
  };
}
