import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, query, type Me, type Opportunity, type Page } from "../api/client";
import { FeedRow } from "../components/FeedRow";
import { Button, Empty, ErrorNote, Spinner } from "../components/ui";
import { ago } from "../format";
import { useSetStatus } from "../hooks";

/** "feed": what matches your profile (New, All matches). "jobs": everything, to filter by hand. */
type Screen = "feed" | "jobs";
type View = "new" | "matches";
type Sort = "posted" | "found" | "prestige";
type Filters = {
  q: string;
  location: string;
  view: View;
  sort: Sort;
  usOnly: boolean;
  closingSoon: boolean;
  ignored: boolean;
};

const VIEWS: { id: View; label: string }[] = [
  { id: "new", label: "New" },
  { id: "matches", label: "All matches" },
];

// "Internships" before "New grad", like a digest; anything else last.
const GROUPS = ["Internships", "New grad", "Other roles"] as const;
const INTERN = /\b(intern(ship)?s?|co-?op)\b/i;
const NEW_GRAD = /\b(new (college )?grad(uate)?s?|graduate|early career|entry[- ]level|university|campus|junior)\b/i;
function group(o: Opportunity): (typeof GROUPS)[number] {
  // The title says it best; the enriched category only breaks a tie.
  for (const text of [o.title, o.category]) {
    if (INTERN.test(text)) return "Internships";
    if (NEW_GRAD.test(text)) return "New grad";
  }
  return "Other roles";
}

// Track chips: the stored role_track is blank on most rows (no LLM on the box), so the title decides first.
const TRACKS: [string, RegExp][] = [
  ["Quant", /\b(quant|trading|trader)\b/i],
  ["AI / ML / Data", /\b(machine learning|ml|ai|data (scien|eng|analy)\w*|research scientist|nlp|llm)\b/i],
  ["Hardware", /\b(hardware|electrical|embedded|firmware|silicon|asic|fpga|mechanical)\b/i],
  ["Security", /\b(security|cyber|risk)\b/i],
  ["Product", /\b(product|program) (manag|design)/i],
  ["Design", /\b(design|ux|ui)\b/i],
  ["Software", /\b(software|swe|developer|engineer|backend|frontend|full[- ]?stack|devops|sre|platform)\b/i],
];
const twinKey = (o: Opportunity) => `${o.company}|${o.title}`.toLowerCase();
function track(o: Opportunity): string {
  const text = `${o.title} ${o.role_track}`;
  return TRACKS.find(([, re]) => re.test(text))?.[0] ?? "Other";
}

function useDebounced<T>(value: T, ms = 250) {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export function feedKey(screen: Screen, f: Filters) {
  return ["opportunities", screen, f] as const;
}

export function Feed({ screen = "feed", incoming = [], clearIncoming = () => {} }: { screen?: Screen; incoming?: Opportunity[]; clearIncoming?: () => void }) {
  const [filters, setFilters] = useState<Filters>({
    q: "",
    location: "",
    view: "new",
    sort: "posted",
    usOnly: false,
    closingSoon: false,
    ignored: false,
  });
  const q = useDebounced(filters.q);
  const location = useDebounced(filters.location);
  const active = useMemo(() => ({ ...filters, q, location }), [filters, q, location]);
  const setStatus = useSetStatus();
  const me = useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/api/me") });
  const [selected, setSelected] = useState(0);
  const [trackFilter, setTrackFilter] = useState("");
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [fresh, setFresh] = useState<Set<string>>(new Set());
  const search = useRef<HTMLInputElement>(null);
  const rows = useRef<(HTMLElement | null)[]>([]);

  const feed = useInfiniteQuery({
    queryKey: feedKey(screen, active),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      api<Page>(
        `/api/opportunities${query({
          include: screen === "jobs" ? "all" : "matches",
          backfill: screen === "feed" && active.view === "new" ? false : undefined,
          sort: active.sort,
          us_only: active.usOnly || undefined,
          q: active.q,
          location: active.location,
          closing_within: active.closingSoon ? 14 : undefined,
          action: active.ignored ? "ignored" : undefined,
          cursor: pageParam,
          limit: 30,
        })}`,
      ),
    getNextPageParam: (last) => last.next_cursor,
    // Live drops arrive over SSE; this only reconciles missed frames and first-poll backfill.
    refetchInterval: 30_000,
  });

  const loaded = useMemo(() => feed.data?.pages.flatMap((p) => p.items) ?? [], [feed.data]);
  const trackCounts = useMemo(() => {
    const c = new Map<string, number>();
    for (const o of loaded) c.set(track(o), (c.get(track(o)) ?? 0) + 1);
    return [...c].sort((a, b) => b[1] - a[1]);
  }, [loaded]);
  const shown = useMemo(() => (trackFilter ? loaded.filter((o) => track(o) === trackFilter) : loaded), [loaded, trackFilter]);
  // The same role posted in several places is one row with the extra locations behind it.
  const twins = useMemo(() => {
    const m = new Map<string, Opportunity[]>();
    for (const o of shown) m.set(twinKey(o), [...(m.get(twinKey(o)) ?? []), o]);
    return m;
  }, [shown]);
  // Grouped display order; j/k walk it top to bottom.
  const items = useMemo(() => {
    const seen = new Set<string>();
    return GROUPS.flatMap((g) => shown.filter((o) => group(o) === g)).filter((o) => !seen.has(twinKey(o)) && seen.add(twinKey(o)));
  }, [shown]);
  const unseen = incoming.filter((o) => !loaded.some((i) => i.id === o.id));
  const plainFeed = screen === "feed" && active.view === "new" && !active.q && !active.location && !active.usOnly && !active.closingSoon && !active.ignored;

  // Refetch rather than prepend: a drop goes where its posting date puts it,
  // on top only if it is the newest.
  async function showIncoming() {
    const ids = unseen.map((o) => o.id);
    clearIncoming();
    await feed.refetch();
    setFresh(new Set(ids));
    setSelected(0);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (e.metaKey || e.ctrlKey || e.altKey || target.closest("input, textarea, select")) return;
      const current = items[selected];
      const move = (i: number) => {
        const next = Math.max(0, Math.min(items.length - 1, i));
        setSelected(next);
        rows.current[next]?.scrollIntoView({
          block: "nearest",
          behavior: "smooth",
        });
      };
      if (e.key === "j") move(selected + 1);
      else if (e.key === "k") move(selected - 1);
      else if (e.key === "/") {
        e.preventDefault();
        search.current?.focus();
      } else if (!current) return;
      else if (e.key === "s")
        setStatus.mutate({
          id: current.id,
          status: current.action?.status === "saved" ? "new" : "saved",
        });
      else if (e.key === "i")
        setStatus.mutate({
          id: current.id,
          status: current.action?.status === "ignored" ? "new" : "ignored",
        });
      else if (e.key === "a") setStatus.mutate({ id: current.id, status: "applied" });
      else if ((e.key === "o" || e.key === "Enter") && current.url) window.open(current.url, "_blank", "noopener");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [items, selected, setStatus]);

  const set = <K extends keyof Filters>(key: K, value: Filters[K]) => setFilters((f) => ({ ...f, [key]: value }));
  const count = `${loaded.length}${feed.hasNextPage ? "+" : ""}`;
  const heading = active.ignored
    ? "Ignored"
    : screen === "jobs"
      ? `${count} ${loaded.length === 1 ? "job" : "jobs"}`
      : active.view === "new"
        ? `${count} new ${loaded.length === 1 ? "role" : "roles"}`
        : `${count} ${loaded.length === 1 ? "match" : "matches"}`;
  const blurb =
    screen === "jobs"
      ? "Everything your sources found, matching your profile or not. Search and filter it your way."
      : active.view === "new"
        ? "Roles that match your profile, found since the radar started watching."
        : "Every role that matches your profile, new or not.";
  const newest = loaded.reduce<string | null>((m, o) => (!m || o.first_seen > m ? o.first_seen : m), null);
  const pill = (on: boolean) =>
    `min-h-8 shrink-0 rounded-full px-3.5 text-sm font-medium transition-colors ${
      on ? "bg-zinc-950 text-white dark:bg-white dark:text-zinc-950" : "text-zinc-600 hover:text-zinc-950 dark:text-zinc-400 dark:hover:text-white"
    }`;
  const field = "min-h-10 min-w-0 rounded-full border border-zinc-200 bg-white px-4 text-sm dark:border-zinc-800 dark:bg-zinc-900";

  let index = 0;
  return (
    <section aria-labelledby="feed-title" className="mx-auto max-w-3xl space-y-5">
      <header className="space-y-3">
        <p className="inline-flex items-center gap-2 rounded-full border border-zinc-200 bg-white px-3 py-1 font-mono text-xs text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-400">
          <span className="size-1.5 rounded-full bg-emerald-500" aria-hidden />
          {[me.data && `${me.data.sources} sources watched`, newest && `newest found ${ago(newest)}`].filter(Boolean).join(" · ") || "Watching your sources"}
        </p>
        <h1 id="feed-title" className="text-3xl font-black tracking-tight text-zinc-950 sm:text-4xl dark:text-white">
          {feed.isPending ? (screen === "jobs" ? "All jobs" : "Your feed") : heading}
        </h1>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">{blurb}</p>
      </header>

      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap gap-2">
          <input
            ref={search}
            type="search"
            value={filters.q}
            onChange={(e) => set("q", e.target.value)}
            placeholder="Search role or company"
            aria-label="Search role or company"
            className={`${field} w-full sm:w-auto sm:flex-1`}
          />
          <input
            type="search"
            value={filters.location}
            onChange={(e) => set("location", e.target.value)}
            placeholder="Location"
            aria-label="Location"
            className={`${field} flex-1 sm:w-44 sm:flex-none`}
          />
          <select
            aria-label="Sort"
            value={filters.sort}
            onChange={(e) => set("sort", e.target.value as Sort)}
            className="min-h-10 shrink-0 rounded-full border border-zinc-200 bg-white px-3 text-sm font-medium text-zinc-700 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300"
          >
            <option value="posted">Newest posted</option>
            <option value="found">Newest found</option>
            <option value="prestige">Most prestigious</option>
          </select>
        </div>
        <div className="-mx-4 flex items-center gap-1 overflow-x-auto px-4 sm:mx-0 sm:px-0">
          {screen === "feed" && (
            <div
              role="group"
              aria-label="Show"
              className="flex shrink-0 rounded-full border border-zinc-200 bg-white p-1 dark:border-zinc-800 dark:bg-zinc-900"
            >
              {VIEWS.map((v) => (
                <button key={v.id} type="button" aria-pressed={filters.view === v.id} onClick={() => set("view", v.id)} className={pill(filters.view === v.id)}>
                  {v.label}
                </button>
              ))}
            </div>
          )}
          <button type="button" aria-pressed={filters.usOnly} onClick={() => set("usOnly", !filters.usOnly)} className={pill(filters.usOnly)}>
            US only
          </button>
          <button
            type="button"
            aria-pressed={filters.closingSoon}
            onClick={() => set("closingSoon", !filters.closingSoon)}
            className={pill(filters.closingSoon)}
          >
            Closing soon
          </button>
          <button type="button" aria-pressed={filters.ignored} onClick={() => set("ignored", !filters.ignored)} className={pill(filters.ignored)}>
            Ignored
          </button>
        </div>
      </div>

      {trackCounts.length > 1 && (
        <div role="group" aria-label="Track" className="-mx-4 flex gap-1 overflow-x-auto px-4 sm:mx-0 sm:px-0">
          {[["", loaded.length] as [string, number], ...trackCounts].map(([t, n]) => (
            <button
              key={t}
              type="button"
              aria-pressed={trackFilter === t}
              onClick={() => setTrackFilter(t)}
              className={`${pill(trackFilter === t)} border border-zinc-200 dark:border-zinc-800`}
            >
              {t || "All"} <span className="font-mono text-xs opacity-60">{n}</span>
            </button>
          ))}
        </div>
      )}

      {unseen.length > 0 && plainFeed && (
        <div className="sticky top-16 z-10 flex justify-center">
          <Button variant="primary" onClick={showIncoming} className="rounded-full shadow-lg">
            ↑ {unseen.length} new {unseen.length === 1 ? "drop" : "drops"}
          </Button>
        </div>
      )}

      {feed.isPending ? (
        <Spinner label={screen === "jobs" ? "Loading jobs" : "Loading your feed"} />
      ) : feed.isError ? (
        <ErrorNote error={feed.error} retry={() => feed.refetch()} />
      ) : items.length === 0 ? (
        <Empty title={plainFeed ? "No new roles yet" : "Nothing here"}>
          {plainFeed ? (
            <>
              New postings that match your profile land here the moment a source finds them, and buzz your phone once alerts are on.{" "}
              <button type="button" className="underline" onClick={() => set("view", "matches")}>
                See all matches
              </button>
              .
            </>
          ) : (
            "Clear the search or switch filters."
          )}
        </Empty>
      ) : (
        <div className="overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
          {GROUPS.map((g) => {
            const inGroup = items.filter((o) => group(o) === g);
            if (inGroup.length === 0) return null;
            return (
              <section key={g} aria-label={g}>
                <h2 className="border-b border-zinc-100 px-4 pt-5 pb-2 font-mono text-[11px] tracking-[0.12em] text-zinc-500 uppercase sm:px-5 dark:border-zinc-800">
                  {g} · {inGroup.length}
                </h2>
                <ol className="divide-y divide-zinc-100 dark:divide-zinc-800">
                  {inGroup.map((o) => {
                    const i = index++;
                    const more = (twins.get(twinKey(o)) ?? []).slice(1);
                    const row = (r: Opportunity, n?: number) => (
                      <FeedRow
                        ref={
                          n === undefined
                            ? (el) => {
                                rows.current[i] = el;
                              }
                            : undefined
                        }
                        opportunity={r}
                        selected={n === undefined && i === selected}
                        fresh={fresh.has(r.id)}
                        onSelect={() => n === undefined && setSelected(i)}
                        onStatus={(status) => setStatus.mutate({ id: r.id, status })}
                      />
                    );
                    return (
                      <li key={o.id}>
                        {row(o)}
                        {more.length > 0 && (
                          <button
                            type="button"
                            aria-expanded={open.has(o.id)}
                            onClick={() =>
                              setOpen((s) => {
                                const n = new Set(s);
                                if (!n.delete(o.id)) n.add(o.id);
                                return n;
                              })
                            }
                            className="mb-3 ml-16 text-xs font-medium text-zinc-500 underline hover:text-zinc-900 dark:hover:text-zinc-100"
                          >
                            {open.has(o.id) ? "Hide" : `+${more.length} more posting${more.length === 1 ? "" : "s"} of this role`}
                          </button>
                        )}
                        {open.has(o.id) && (
                          <ol className="divide-y divide-zinc-100 border-t border-zinc-100 dark:divide-zinc-800 dark:border-zinc-800">
                            {more.map((r) => (
                              <li key={r.id}>{row(r, 0)}</li>
                            ))}
                          </ol>
                        )}
                      </li>
                    );
                  })}
                </ol>
              </section>
            );
          })}
        </div>
      )}

      {feed.hasNextPage && (
        <div className="flex justify-center">
          <Button onClick={() => feed.fetchNextPage()} disabled={feed.isFetchingNextPage} className="rounded-full">
            {feed.isFetchingNextPage ? "Loading…" : "Load more"}
          </Button>
        </div>
      )}
      {setStatus.isError && <ErrorNote error={setStatus.error} />}
      <p className="hidden text-center text-xs text-zinc-500 sm:block">
        <kbd>j</kbd>/<kbd>k</kbd> move · <kbd>s</kbd> save · <kbd>i</kbd> ignore · <kbd>a</kbd> applied · <kbd>o</kbd> open · <kbd>/</kbd> search
      </p>
    </section>
  );
}
