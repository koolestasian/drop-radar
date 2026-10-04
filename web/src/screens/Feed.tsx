import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowUp, ChevronDown, Rows2, Rows4, Search, SlidersHorizontal } from "lucide-react";
import { api, query, type Me, type Opportunity, type Page, type Summary } from "../api/client";
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
import { ago, LEVEL_LABEL } from "../format";
import { activeCount, apiParams, DEFAULTS, isPlain, LEVELS, parseFilters, SCOPES, SORTS, toHash, TRACKS, type Filters } from "../filters";
import { LAST_VISIT } from "../lastVisit";
import { useDensity, useMediaQuery, useSetStatus } from "../hooks";

const SCOPE_LABEL = { you: "For you", all: "Everything" } as const;
const POSTED_OPTIONS: [string, string][] = [["", "Any time"], ["1", "Past 24 hours"], ["7", "Past 7 days"], ["30", "Past 30 days"]];
const SORT_LABEL = { posted: "Newest posted", prestige: "Most prestigious" } as const;

const twinKey = (o: Opportunity) => `${o.company}|${o.title}`.toLowerCase();

function useDebounced<T>(value: T, ms = 250) {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

/** A filter pill: a native select dressed as a chip, so phones get their own picker. */
function PillSelect({ label, value, onChange, options, className = "" }: { label: string; value: string; onChange: (v: string) => void; options: [string, string][]; className?: string }) {
  return (
    <select
      aria-label={label}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={`h-10 rounded-full border bg-card px-3 text-sm pointer-coarse:h-11 ${value ? "border-foreground font-medium" : "border-input"} ${className}`}
    >
      {options.map(([v, text]) => (
        <option key={v} value={v}>
          {v ? text : `${label}: ${text}`}
        </option>
      ))}
    </select>
  );
}

export function Feed({ incoming = [], clearIncoming = () => {}, guest = false }: { incoming?: Opportunity[]; clearIncoming?: () => void; guest?: boolean }) {
  const [filters, setFilters] = useState<Filters>(parseFilters);
  const latest = useRef(filters);
  // The hash is the source of truth: back, forward, a pasted link and the nav's own links all arrive here.
  useEffect(() => {
    const sync = () => {
      latest.current = parseFilters();
      setFilters(latest.current);
    };
    window.addEventListener("hashchange", sync);
    window.addEventListener("popstate", sync);
    return () => {
      window.removeEventListener("hashchange", sync);
      window.removeEventListener("popstate", sync);
    };
  }, []);
  /** Change filters and the address; typing replaces the history entry, a deliberate choice adds one. */
  function update(patch: Partial<Filters>, replace = false) {
    if (!window.location.hash.startsWith("#/jobs")) return; // already on another screen: a late landing or debounce must not pull you back
    const next = { ...latest.current, ...patch };
    latest.current = next;
    setFilters(next);
    const hash = toHash(next);
    if (hash !== window.location.hash) window.history[replace ? "replaceState" : "pushState"](null, "", hash);
  }
  const q = useDebounced(filters.q);
  const location = useDebounced(filters.location);
  const active = useMemo(() => ({ ...filters, q, location }), [filters, q, location]);
  const setStatus = useSetStatus();
  const me = useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/api/me") });
  const summary = useQuery({ queryKey: ["summary"], queryFn: () => api<Summary>("/api/opportunities/summary"), refetchInterval: 300_000 });
  const wide = useMediaQuery("(min-width: 1024px)");
  const roomy = useMediaQuery("(min-width: 640px)");
  const [density, setDensity] = useDensity();
  const compact = density === "compact";
  const [activeId, setActiveId] = useState<string | null>(null);
  const [sheet, setSheet] = useState(false);
  const [filterSheet, setFilterSheet] = useState(false);
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [pinned, setPinned] = useState<Set<string>>(new Set());
  const search = useRef<HTMLInputElement>(null);
  const rows = useRef<Map<string, HTMLElement>>(new Map());

  const feed = useInfiniteQuery({
    queryKey: ["opportunities", "jobs", active],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => api<Page>(`/api/opportunities${query({ ...apiParams(active), cursor: pageParam, limit: 30 })}`),
    getNextPageParam: (last) => last.next_cursor,
    // Live drops arrive over SSE; this only reconciles missed frames and first-poll backfill.
    refetchInterval: 30_000,
  });
  // How many drops since your last visit in this scope: the New pill and the header line.
  const drops = useQuery({
    queryKey: ["opportunities", "drops", filters.scope],
    queryFn: () => api<Page>(`/api/opportunities${query({ ...apiParams({ ...DEFAULTS, scope: filters.scope, fresh: true }), limit: 200 })}`),
    refetchInterval: 30_000,
  });
  const newCount = drops.data?.items.length ?? 0;
  const newLabel = drops.data ? `${newCount}${drops.data.next_cursor ? "+" : ""}` : "";
  // Land on the drops when there are some; a quiet day lands on the normal list.
  const landed = useRef(false);
  useEffect(() => {
    if (landed.current || !drops.data) return;
    landed.current = true;
    if (filters.fresh === null && filters.scope === "you" && isPlain(filters) && newCount > 0) update({ fresh: true }, true);
  }, [drops.data]); // eslint-disable-line react-hooks/exhaustive-deps

  const loaded = useMemo(() => feed.data?.pages.flatMap((p) => p.items) ?? [], [feed.data]);
  // The same role posted in several places is one card with the extra locations behind it.
  const twins = useMemo(() => {
    const m = new Map<string, Opportunity[]>();
    for (const o of loaded) m.set(twinKey(o), [...(m.get(twinKey(o)) ?? []), o]);
    return m;
  }, [loaded]);
  // j/k walk this top to bottom.
  const items = useMemo(() => {
    const seen = new Set<string>();
    return loaded.filter((o) => !seen.has(twinKey(o)) && seen.add(twinKey(o)));
  }, [loaded]);
  const current = loaded.find((o) => o.id === activeId) ?? items[0];
  const unseen = incoming.filter((o) => !loaded.some((i) => i.id === o.id));
  const noSearch = isPlain({ ...filters, fresh: false });
  const counts = summary.data?.[filters.scope === "all" ? "everything" : "you"];

  // Refetch rather than prepend: a drop goes where its posting date puts it,
  // on top only if it is the newest.
  async function showIncoming() {
    const ids = unseen.map((o) => o.id);
    clearIncoming();
    await feed.refetch();
    setPinned(new Set(ids));
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
      else if (!guest && e.key === "s") setStatus.mutate({ id: current.id, status: current.action?.status === "saved" ? "new" : "saved" });
      else if (!guest && e.key === "i") setStatus.mutate({ id: current.id, status: current.action?.status === "ignored" ? "new" : "ignored" });
      else if (!guest && e.key === "a") setStatus.mutate({ id: current.id, status: "applied" });
      else if ((e.key === "o" || e.key === "Enter") && current.url) window.open(current.url, "_blank", "noopener");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [items, current, setStatus, guest]);

  const newest = loaded.reduce<string | null>((m, o) => (!m || o.first_seen > m ? o.first_seen : m), null);
  const sinceLabel = new Date(LAST_VISIT).toLocaleString(undefined, { weekday: "short", hour: "numeric", minute: "2-digit" });
  const nf = new Intl.NumberFormat();
  const headline = counts
    ? [`${nf.format(summary.data!.you.total)} for you`, `${nf.format(summary.data!.everything.total)} found`, newCount > 0 && `${newLabel} new since ${sinceLabel}`].filter(Boolean).join(" · ")
    : "";
  const blurb = filters.scope === "all" ? "Everything your sources found, matching your profile or not." : "Roles that match your profile.";
  const moreCount = activeCount(filters) - (roomy ? [filters.level, filters.track, filters.posted].filter(Boolean).length : 0); // the pills show their own state
  const chip = "pointer-coarse:h-11 rounded-full px-3.5";
  const detail = current && (
    <Detail
      key={current.id}
      o={current}
      onStatus={guest ? undefined : (status) => setStatus.mutate({ id: current.id, status })}
      onNotes={guest ? undefined : (notes) => setStatus.mutate({ id: current.id, notes })}
    />
  );

  const withCount = (name: string, n: number | undefined) => (n === undefined ? name : `${name} (${nf.format(n)})`);
  const pills = (
    <>
      <PillSelect
        label="Level"
        value={filters.level}
        onChange={(v) => update({ level: v as Filters["level"] })}
        options={[["", "Any"], ...LEVELS.map((l): [string, string] => [l, withCount(LEVEL_LABEL[l], counts?.level[l])])]}
      />
      <PillSelect
        label="Track"
        value={filters.track}
        onChange={(v) => update({ track: v })}
        options={[["", "Any"], ...TRACKS.map((t): [string, string] => [t, withCount(t, counts?.track[t] ?? (counts ? 0 : undefined))])]}
      />
      <PillSelect
        label="Posted"
        value={filters.posted}
        onChange={(v) => update({ posted: v as Filters["posted"] })}
        options={POSTED_OPTIONS}
      />
    </>
  );
  const filterBody = (
    <div className="flex flex-col gap-5 pt-2">
      {!roomy && <div className="flex flex-col gap-3 [&_select]:h-11 [&_select]:w-full">{pills}</div>}
      <div className="flex flex-col gap-2">
        <label htmlFor="location" className="text-sm font-semibold">
          Location
        </label>
        <Input
          id="location"
          type="search"
          value={filters.location}
          onChange={(e) => update({ location: e.target.value }, true)}
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
          onValueChange={(v) => v && update({ sort: v as Filters["sort"] })}
          className="flex w-full flex-col"
        >
          {SORTS.map((id) => (
            <ToggleGroupItem key={id} value={id} className="w-full justify-start pointer-coarse:h-11">
              {SORT_LABEL[id]}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      </div>
      {(
        [
          ["usOnly", "US only", "Hide roles outside the United States."],
          ["closingSoon", "Closing soon", "Deadline within 14 days."],
          ["dropsOnly", "Drops only", "Only roles found after your sources started watching them."],
        ] as const
      ).map(([key, label, hint]) => (
        <div key={key} className="flex items-center justify-between gap-4">
          <label htmlFor={key} className="flex flex-col">
            <span className="text-sm font-semibold">{label}</span>
            <span className="text-sm text-muted-foreground">{hint}</span>
          </label>
          <Switch id={key} checked={filters[key]} onCheckedChange={(v) => update({ [key]: v })} />
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
            Jobs
          </h1>
          <p className="text-sm text-muted-foreground">{blurb}</p>
          <p className="stamp text-muted-foreground">
            {[headline || (me.data && `${me.data.sources} sources watched`), newest && Date.now() - Date.parse(newest) > 6 * 3600e3 && `nothing found for ${ago(newest).replace(/ ago$/, "")}`].filter(Boolean).join(" · ") || "Watching your sources"}
          </p>
        </header>

        <div className="flex flex-col gap-3">
          <ToggleGroup
            type="single"
            variant="outline"
            aria-label="Scope"
            value={filters.scope}
            onValueChange={(v) => v && update({ scope: v as Filters["scope"] })}
            className="self-start"
          >
            {SCOPES.map((id) => (
              <ToggleGroupItem key={id} value={id} className={`${chip} px-5`}>
                {SCOPE_LABEL[id]}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
          <div className="flex gap-2">
            <div className="relative min-w-0 flex-1">
              <Search aria-hidden className="pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                ref={search}
                type="search"
                value={filters.q}
                onChange={(e) => update({ q: e.target.value }, true)}
                placeholder="Search role or company"
                aria-label="Search role or company"
                name="q"
                className="h-11 rounded-full bg-card pl-10 text-base sm:h-10 sm:text-sm"
              />
            </div>
            <Button variant="outline" size="lg" className="rounded-full sm:h-10" onClick={() => setFilterSheet(true)}>
              <SlidersHorizontal data-icon="inline-start" />
              {roomy ? "More" : "Filters"}
              {moreCount > 0 && <Badge className="ml-0.5">{moreCount}</Badge>}
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
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="outline"
              aria-pressed={Boolean(filters.fresh)}
              disabled={!filters.fresh && newCount === 0}
              onClick={() => update({ fresh: !filters.fresh })}
              className={`${chip} h-10 ${filters.fresh ? "border-foreground bg-foreground text-background hover:bg-foreground/90 hover:text-background" : newCount > 0 ? "border-foreground bg-stock-fresh" : ""}`}
            >
              New {newLabel || 0}
            </Button>
            {roomy && pills}
          </div>
        </div>

        {unseen.length > 0 && noSearch && (
          <div className="sticky top-3 z-10 flex justify-center">
            <Button size="lg" onClick={showIncoming} className="rounded-full shadow-lg">
              <ArrowUp data-icon="inline-start" />
              {unseen.length} new {unseen.length === 1 ? "drop" : "drops"}
            </Button>
          </div>
        )}

        {feed.isPending ? (
          <ListSkeleton label="Loading jobs" />
        ) : feed.isError ? (
          <ErrorNote error={feed.error} retry={() => feed.refetch()} />
        ) : items.length === 0 ? (
          <Empty className="rounded-xl border border-dashed border-border">
            <EmptyHeader>
              <EmptyTitle>{isPlain(filters) && filters.scope === "you" ? "No matches yet" : "Nothing here"}</EmptyTitle>
              <EmptyDescription>
                {isPlain(filters) && filters.scope === "you" ? (
                  <>
                    Postings that match your profile land here the moment a source finds them, and buzz your phone once alerts are on.{" "}
                    <button type="button" className="underline" onClick={() => update({ scope: "all" })}>
                      See everything
                    </button>
                    .
                  </>
                ) : (
                  <>
                    Nothing matches these filters.{" "}
                    <button type="button" className="underline" onClick={() => update({ ...DEFAULTS, scope: filters.scope, fresh: false })}>
                      Clear filters
                    </button>
                    .
                  </>
                )}
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          <ol className="flex flex-col gap-2.5">
            {items.map((o) => {
              const more = (twins.get(twinKey(o)) ?? []).slice(1);
              const card = (r: Opportunity) => (
                <RoleCard
                  ref={(el) => {
                    if (el) rows.current.set(r.id, el);
                    else rows.current.delete(r.id);
                  }}
                  opportunity={r}
                  selected={wide && r.id === current?.id}
                  fresh={pinned.has(r.id)}
                  compact={compact}
                  onOpen={() => openRole(r)}
                  onStatus={guest ? undefined : (status) => setStatus.mutate({ id: r.id, status })}
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
                      {open.has(o.id) ? "Show fewer" : `+${more.length} more posting${more.length === 1 ? "" : "s"} of this role`}
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
          <kbd>j</kbd>/<kbd>k</kbd> move · {!guest && (<><kbd>s</kbd> save · <kbd>i</kbd> hide · <kbd>a</kbd> applied · </>)}<kbd>o</kbd> open · <kbd>/</kbd> search
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
              <SheetDescription>Narrow the list. Your profile still decides what is For you.</SheetDescription>
            </SheetHeader>
            {filterBody}
          </SheetContent>
        </Sheet>
      ) : (
        <Drawer open={filterSheet} onOpenChange={setFilterSheet}>
          <DrawerContent className="max-h-[88dvh]">
            <DrawerHeader>
              <DrawerTitle>Filters</DrawerTitle>
              <DrawerDescription>Narrow the list. Your profile still decides what is For you.</DrawerDescription>
            </DrawerHeader>
            <div className="overflow-y-auto px-4 pb-[max(1.5rem,env(safe-area-inset-bottom))]">{filterBody}</div>
          </DrawerContent>
        </Drawer>
      )}
    </div>
  );
}
