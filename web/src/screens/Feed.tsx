import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowUp, ChevronDown, Rows2, Rows4, Search, SlidersHorizontal } from "lucide-react";
import { api, query, type Me, type Opportunity, type Page } from "../api/client";
import { Detail } from "../components/Detail";
import { ErrorNote, ListSkeleton } from "../components/common";
import { RoleCard } from "../components/RoleCard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Drawer, DrawerClose, DrawerContent, DrawerDescription, DrawerHeader, DrawerTitle } from "@/components/ui/drawer";
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty";
import { Input } from "@/components/ui/input";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Switch } from "@/components/ui/switch";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { ago } from "../format";
import { useDensity, useMediaQuery, useSetStatus } from "../hooks";

/** "feed": what matches your profile (New, All matches). "jobs": everything, to filter by hand. */
type Screen = "feed" | "jobs";
type View = "new" | "matches";
type Sort = "posted" | "found" | "prestige";
type Filters = { q: string; location: string; view: View; sort: Sort; usOnly: boolean; closingSoon: boolean; ignored: boolean };

const VIEWS: { id: View; label: string }[] = [
  { id: "new", label: "New" },
  { id: "matches", label: "All matches" },
];
const SORTS: { id: Sort; label: string }[] = [
  { id: "posted", label: "Newest posted" },
  { id: "found", label: "Newest found" },
  { id: "prestige", label: "Most prestigious" },
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
  const [filters, setFilters] = useState<Filters>({ q: "", location: "", view: "new", sort: "posted", usOnly: false, closingSoon: false, ignored: false });
  const q = useDebounced(filters.q);
  const location = useDebounced(filters.location);
  const active = useMemo(() => ({ ...filters, q, location }), [filters, q, location]);
  const setStatus = useSetStatus();
  const me = useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/api/me") });
  const wide = useMediaQuery("(min-width: 1024px)");
  const [density, setDensity] = useDensity();
  const compact = density === "compact";
  const [activeId, setActiveId] = useState<string | null>(null);
  const [sheet, setSheet] = useState(false);
  const [filterSheet, setFilterSheet] = useState(false);
  const [trackFilter, setTrackFilter] = useState("");
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [fresh, setFresh] = useState<Set<string>>(new Set());
  const search = useRef<HTMLInputElement>(null);
  const rows = useRef<Map<string, HTMLElement>>(new Map());

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
  // The same role posted in several places is one card with the extra locations behind it.
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
  const current = shown.find((o) => o.id === activeId) ?? items[0];
  const unseen = incoming.filter((o) => !loaded.some((i) => i.id === o.id));
  const plainFeed = screen === "feed" && active.view === "new" && !active.q && !active.location && !active.usOnly && !active.closingSoon && !active.ignored;
  const activeFilters = [filters.location, filters.usOnly, filters.closingSoon, filters.ignored, filters.sort !== "posted"].filter(Boolean).length;

  // Refetch rather than prepend: a drop goes where its posting date puts it,
  // on top only if it is the newest.
  async function showIncoming() {
    const ids = unseen.map((o) => o.id);
    clearIncoming();
    await feed.refetch();
    setFresh(new Set(ids));
    setActiveId(null);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function openRole(o: Opportunity) {
    setActiveId(o.id);
    if (!wide) (document.activeElement as HTMLElement | null)?.blur(); // the drawer hides the page; focus must not stay behind it
    if (!wide) setSheet(true);
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (e.metaKey || e.ctrlKey || e.altKey || target.closest("input, textarea, select, [role=dialog]")) return;
      const index = Math.max(
        0,
        items.findIndex((o) => o.id === current?.id),
      );
      const move = (i: number) => {
        const next = items[Math.max(0, Math.min(items.length - 1, i))];
        if (!next) return;
        setActiveId(next.id);
        rows.current.get(next.id)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
      };
      if (e.key === "j") move(index + 1);
      else if (e.key === "k") move(index - 1);
      else if (e.key === "/") {
        e.preventDefault();
        search.current?.focus();
      } else if (!current) return;
      else if (e.key === "s") setStatus.mutate({ id: current.id, status: current.action?.status === "saved" ? "new" : "saved" });
      else if (e.key === "i") setStatus.mutate({ id: current.id, status: current.action?.status === "ignored" ? "new" : "ignored" });
      else if (e.key === "a") setStatus.mutate({ id: current.id, status: "applied" });
      else if ((e.key === "o" || e.key === "Enter") && current.url) window.open(current.url, "_blank", "noopener");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [items, current, setStatus]);

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
      ? "Everything your sources found, matching your profile or not."
      : active.view === "new"
        ? "Roles that match your profile, found since the radar started watching."
        : "Every role that matches your profile, new or not.";
  const newest = loaded.reduce<string | null>((m, o) => (!m || o.first_seen > m ? o.first_seen : m), null);
  const chip = "pointer-coarse:h-11 rounded-full px-3.5";
  const detail = current && (
    <Detail
      key={current.id}
      o={current}
      onStatus={(status) => setStatus.mutate({ id: current.id, status })}
      onNotes={(notes) => setStatus.mutate({ id: current.id, notes })}
    />
  );

  const filterBody = (
    <div className="flex flex-col gap-5 pt-2">
      <div className="flex flex-col gap-2">
        <label htmlFor="location" className="text-sm font-semibold">
          Location
        </label>
        <Input
          id="location"
          type="search"
          value={filters.location}
          onChange={(e) => set("location", e.target.value)}
          placeholder="City, state or country"
          className="h-11 text-base sm:h-10 sm:text-sm"
        />
      </div>
      <div className="flex flex-col gap-2">
        <span id="sort-label" className="text-sm font-semibold">
          Sort by
        </span>
        <ToggleGroup
          type="single"
          variant="outline"
          aria-labelledby="sort-label"
          value={filters.sort}
          onValueChange={(v) => v && set("sort", v as Sort)}
          className="flex w-full flex-col"
        >
          {SORTS.map((s) => (
            <ToggleGroupItem key={s.id} value={s.id} className="w-full justify-start pointer-coarse:h-11">
              {s.label}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      </div>
      {(
        [
          ["usOnly", "US only", "Hide roles outside the United States."],
          ["closingSoon", "Closing soon", "Deadline within 14 days."],
          ["ignored", "Ignored", "Show the roles you ignored instead."],
        ] as const
      ).map(([key, label, hint]) => (
        <div key={key} className="flex items-center justify-between gap-4">
          <label htmlFor={key} className="flex flex-col">
            <span className="text-sm font-semibold">{label}</span>
            <span className="text-sm text-muted-foreground">{hint}</span>
          </label>
          <Switch id={key} checked={filters[key]} onCheckedChange={(v) => set(key, v)} />
        </div>
      ))}
      <Button size="lg" onClick={() => setFilterSheet(false)}>
        Show results
      </Button>
    </div>
  );

  return (
    <div className="lg:grid lg:grid-cols-[minmax(0,1fr)_25rem] lg:items-start lg:gap-8">
      <section aria-labelledby="feed-title" className="flex min-w-0 flex-col gap-4">
        <header className="flex flex-col gap-1">
          <h1 id="feed-title" className="text-3xl font-bold tracking-tight text-balance sm:text-4xl">
            {feed.isPending ? (screen === "jobs" ? "All jobs" : "Your feed") : heading}
          </h1>
          <p className="text-sm text-muted-foreground">{blurb}</p>
          <p className="stamp text-muted-foreground">
            {[me.data && `${me.data.sources} sources watched`, newest && `newest found ${ago(newest)}`].filter(Boolean).join(" · ") || "Watching your sources"}
          </p>
        </header>

        <div className="flex flex-col gap-3">
          <div className="flex gap-2">
            <div className="relative min-w-0 flex-1">
              <Search aria-hidden className="pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                ref={search}
                type="search"
                value={filters.q}
                onChange={(e) => set("q", e.target.value)}
                placeholder="Search role or company"
                aria-label="Search role or company"
                name="q"
                className="h-11 rounded-full bg-card pl-10 text-base sm:h-10 sm:text-sm"
              />
            </div>
            <Button variant="outline" size="lg" className="rounded-full sm:h-10" onClick={() => setFilterSheet(true)}>
              <SlidersHorizontal data-icon="inline-start" />
              Filters
              {activeFilters > 0 && <Badge className="ml-0.5">{activeFilters}</Badge>}
            </Button>
            <Button
              variant="outline"
              size="icon"
              className="size-11 shrink-0 rounded-full sm:size-10"
              aria-pressed={compact}
              aria-label="Compact rows"
              title={compact ? "Switch to roomy cards" : "Switch to compact rows"}
              onClick={() => setDensity(compact ? "comfortable" : "compact")}
            >
              {compact ? <Rows2 /> : <Rows4 />}
            </Button>
          </div>
          {screen === "feed" && (
            <ToggleGroup
              type="single"
              variant="outline"
              aria-label="Show"
              value={filters.view}
              onValueChange={(v) => v && set("view", v as View)}
              className="self-start"
            >
              {VIEWS.map((v) => (
                <ToggleGroupItem key={v.id} value={v.id} className={`${chip} px-5`}>
                  {v.label}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          )}
          {trackCounts.length > 1 && (
            <ToggleGroup
              type="single"
              variant="outline"
              aria-label="Track"
              value={trackFilter}
              onValueChange={(v) => setTrackFilter(v)}
              className="-mx-4 w-auto max-w-none flex-nowrap justify-start gap-1.5 overflow-x-auto px-4 pb-1 sm:mx-0 sm:w-full sm:flex-wrap sm:px-0"
            >
              {[["", loaded.length] as [string, number], ...trackCounts].map(([t, n]) => (
                <ToggleGroupItem key={t} value={t} aria-label={`${t || "All"} (${n})`} className={`${chip} shrink-0`}>
                  {t || "All"} <span className="stamp opacity-70">{n}</span>
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          )}
        </div>

        {unseen.length > 0 && plainFeed && (
          <div className="sticky top-3 z-10 flex justify-center">
            <Button size="lg" onClick={showIncoming} className="rounded-full shadow-lg">
              <ArrowUp data-icon="inline-start" />
              {unseen.length} new {unseen.length === 1 ? "drop" : "drops"}
            </Button>
          </div>
        )}

        {feed.isPending ? (
          <ListSkeleton label={screen === "jobs" ? "Loading jobs" : "Loading your feed"} />
        ) : feed.isError ? (
          <ErrorNote error={feed.error} retry={() => feed.refetch()} />
        ) : items.length === 0 ? (
          <Empty className="rounded-xl border border-dashed border-border">
            <EmptyHeader>
              <EmptyTitle>{plainFeed ? "No new roles yet" : "Nothing here"}</EmptyTitle>
              <EmptyDescription>
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
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          GROUPS.map((g) => {
            const inGroup = items.filter((o) => group(o) === g);
            if (inGroup.length === 0) return null;
            return (
              <section key={g} aria-label={g} className="flex flex-col gap-2.5">
                <h2 className="mt-3 text-sm font-semibold text-muted-foreground">
                  {g} <span className="stamp">· {inGroup.length}</span>
                </h2>
                <ol className="flex flex-col gap-2.5">
                  {inGroup.map((o) => {
                    const more = (twins.get(twinKey(o)) ?? []).slice(1);
                    const card = (r: Opportunity) => (
                      <RoleCard
                        ref={(el) => {
                          if (el) rows.current.set(r.id, el);
                          else rows.current.delete(r.id);
                        }}
                        opportunity={r}
                        selected={wide && r.id === current?.id}
                        fresh={fresh.has(r.id)}
                        compact={compact}
                        onOpen={() => openRole(r)}
                        onStatus={(status) => setStatus.mutate({ id: r.id, status })}
                      />
                    );
                    return (
                      <li key={o.id} className="flex flex-col gap-2.5">
                        {card(o)}
                        {more.length > 0 && (
                          <Button
                            variant="ghost"
                            size="sm"
                            aria-expanded={open.has(o.id)}
                            onClick={() =>
                              setOpen((s) => {
                                const n = new Set(s);
                                if (!n.delete(o.id)) n.add(o.id);
                                return n;
                              })
                            }
                            className="self-start"
                          >
                            <ChevronDown data-icon="inline-start" className={open.has(o.id) ? "rotate-180" : ""} />
                            {open.has(o.id) ? "Hide" : `+${more.length} more posting${more.length === 1 ? "" : "s"} of this role`}
                          </Button>
                        )}
                        {open.has(o.id) && (
                          <ol className="flex flex-col gap-2.5 pl-4">
                            {more.map((r) => (
                              <li key={r.id}>{card(r)}</li>
                            ))}
                          </ol>
                        )}
                      </li>
                    );
                  })}
                </ol>
              </section>
            );
          })
        )}

        {feed.hasNextPage && (
          <div className="flex justify-center">
            <Button variant="outline" size="lg" onClick={() => feed.fetchNextPage()} disabled={feed.isFetchingNextPage} className="rounded-full">
              {feed.isFetchingNextPage ? "Loading…" : "Load more"}
            </Button>
          </div>
        )}
        {setStatus.isError && <ErrorNote error={setStatus.error} />}
        <p className="hidden text-center text-xs text-muted-foreground lg:block">
          <kbd>j</kbd>/<kbd>k</kbd> move · <kbd>s</kbd> save · <kbd>i</kbd> ignore · <kbd>a</kbd> applied · <kbd>o</kbd> open · <kbd>/</kbd> search
        </p>
      </section>

      {wide && (
        <aside aria-label="Role details" className="sticky top-6 max-h-[calc(100dvh-3rem)] overflow-y-auto rounded-2xl border border-border bg-card p-5">
          {detail || <p className="text-sm text-muted-foreground">Select a role to see why it matched, where it was found, and to add notes.</p>}
        </aside>
      )}

      <Drawer open={sheet && !wide} onOpenChange={setSheet}>
        <DrawerContent className="max-h-[88dvh]">
          <DrawerHeader className="sr-only">
            <DrawerTitle>{current?.title || "Role details"}</DrawerTitle>
            <DrawerDescription>Details, status and notes for this role.</DrawerDescription>
          </DrawerHeader>
          <div className="flex justify-end px-3 pt-1">
            <DrawerClose asChild>
              <Button variant="ghost">Close</Button>
            </DrawerClose>
          </div>
          <div className="overflow-y-auto px-4 pb-[max(1.5rem,env(safe-area-inset-bottom))]">{detail}</div>
        </DrawerContent>
      </Drawer>

      {wide ? (
        <Sheet open={filterSheet} onOpenChange={setFilterSheet}>
          <SheetContent side="right" className="gap-0 overflow-y-auto px-5 sm:max-w-sm">
            <SheetHeader className="px-0">
              <SheetTitle>Filters</SheetTitle>
              <SheetDescription>Narrow what the feed shows. Your profile still decides what matches.</SheetDescription>
            </SheetHeader>
            {filterBody}
          </SheetContent>
        </Sheet>
      ) : (
        <Drawer open={filterSheet} onOpenChange={setFilterSheet}>
          <DrawerContent className="max-h-[88dvh]">
            <DrawerHeader>
              <DrawerTitle>Filters</DrawerTitle>
              <DrawerDescription>Narrow what the feed shows. Your profile still decides what matches.</DrawerDescription>
            </DrawerHeader>
            <div className="overflow-y-auto px-4 pb-[max(1.5rem,env(safe-area-inset-bottom))]">{filterBody}</div>
          </DrawerContent>
        </Drawer>
      )}
    </div>
  );
}
