import { useInfiniteQuery, useQueryClient, type InfiniteData } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, query, type Opportunity, type Page } from "../api/client";
import { OpportunityCard } from "../components/OpportunityCard";
import { Button, Empty, ErrorNote, Spinner } from "../components/ui";
import { useSetStatus } from "../hooks";

type Filters = { q: string; include: "matches" | "all"; closingSoon: boolean; ignored: boolean };

function useDebounced<T>(value: T, ms = 250) {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export function feedKey(f: Filters) {
  return ["opportunities", "feed", f] as const;
}

export function Feed({ incoming, clearIncoming }: { incoming: Opportunity[]; clearIncoming: () => void }) {
  const [filters, setFilters] = useState<Filters>({ q: "", include: "matches", closingSoon: false, ignored: false });
  const q = useDebounced(filters.q);
  const active = useMemo(() => ({ ...filters, q }), [filters, q]);
  const qc = useQueryClient();
  const setStatus = useSetStatus();
  const [selected, setSelected] = useState(0);
  const [fresh, setFresh] = useState<Set<string>>(new Set());
  const search = useRef<HTMLInputElement>(null);
  const cards = useRef<(HTMLElement | null)[]>([]);

  const feed = useInfiniteQuery({
    queryKey: feedKey(active),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      api<Page>(
        `/api/opportunities${query({
          include: active.include,
          q: active.q,
          closing_within: active.closingSoon ? 14 : undefined,
          action: active.ignored ? "ignored" : undefined,
          cursor: pageParam,
          limit: 30,
        })}`,
      ),
    getNextPageParam: (last) => last.next_cursor,
    // Seeds and missed SSE frames also need reconciliation after the feed fills.
    refetchInterval: (q) => q.state.data?.pages.every((p) => p.items.length === 0) ? 5000 : 30_000,
  });

  const items = useMemo(() => feed.data?.pages.flatMap((p) => p.items) ?? [], [feed.data]);
  const unseen = incoming.filter((o) => !items.some((i) => i.id === o.id));
  const plainFeed = active.include === "matches" && !active.q && !active.closingSoon && !active.ignored;

  function showIncoming() {
    qc.setQueryData<InfiniteData<Page>>(feedKey(active), (data) =>
      data ? { ...data, pages: [{ ...data.pages[0], items: [...unseen, ...data.pages[0].items] }, ...data.pages.slice(1)] } : data,
    );
    setFresh(new Set(unseen.map((o) => o.id)));
    clearIncoming();
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
        cards.current[next]?.scrollIntoView({ block: "nearest", behavior: "smooth" });
      };
      if (e.key === "j") move(selected + 1);
      else if (e.key === "k") move(selected - 1);
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
  }, [items, selected, setStatus]);

  const toggle = (key: "closingSoon" | "ignored") => setFilters((f) => ({ ...f, [key]: !f[key] }));

  return (
    <section aria-labelledby="feed-title" className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <h1 id="feed-title" className="sr-only">
          Feed
        </h1>
        <input
          ref={search}
          type="search"
          value={filters.q}
          onChange={(e) => setFilters((f) => ({ ...f, q: e.target.value }))}
          placeholder="Search title or company  ( / )"
          aria-label="Search title or company"
          className="min-h-10 w-full min-w-0 rounded-lg border border-zinc-300 bg-white px-3 text-sm sm:w-auto sm:flex-1 dark:border-zinc-700 dark:bg-zinc-900"
        />
        <div role="group" aria-label="Show" className="flex rounded-lg border border-zinc-300 p-0.5 dark:border-zinc-700">
          {(["matches", "all"] as const).map((mode) => (
            <button
              key={mode}
              type="button"
              aria-pressed={filters.include === mode}
              onClick={() => setFilters((f) => ({ ...f, include: mode }))}
              className={`min-h-8 rounded-md px-3 text-sm ${
                filters.include === mode
                  ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
                  : "text-zinc-600 dark:text-zinc-300"
              }`}
            >
              {mode === "matches" ? "Matches" : "Everything"}
            </button>
          ))}
        </div>
        <Button aria-pressed={filters.closingSoon} variant={filters.closingSoon ? "primary" : "ghost"} onClick={() => toggle("closingSoon")}>
          Closing in 2 wks
        </Button>
        <Button aria-pressed={filters.ignored} variant={filters.ignored ? "primary" : "quiet"} onClick={() => toggle("ignored")}>
          Ignored
        </Button>
      </div>

      {unseen.length > 0 && plainFeed && (
        <div className="sticky top-16 z-10 flex justify-center">
          <Button variant="primary" onClick={showIncoming} className="rounded-full shadow-lg">
            ↑ {unseen.length} new {unseen.length === 1 ? "drop" : "drops"}
          </Button>
        </div>
      )}

      {feed.isPending ? (
        <Spinner label="Loading your feed" />
      ) : feed.isError ? (
        <ErrorNote error={feed.error} retry={() => feed.refetch()} />
      ) : items.length === 0 ? (
        <Empty title={plainFeed ? "No matches yet" : "Nothing matches these filters"}>
          {plainFeed
            ? "Sources load already-open jobs during their first look, which can take a few minutes. This feed refreshes while empty; new matching postings also buzz your phone. Try “Everything” to see all your sources found."
            : "Clear the search or switch filters."}
        </Empty>
      ) : (
        <ol className="space-y-3">
          {items.map((o, i) => (
            <li key={o.id}>
              <OpportunityCard
                ref={(el) => {
                  cards.current[i] = el;
                }}
                opportunity={o}
                selected={i === selected}
                fresh={fresh.has(o.id)}
                onSelect={() => setSelected(i)}
                onStatus={(status) => setStatus.mutate({ id: o.id, status })}
              />
            </li>
          ))}
        </ol>
      )}

      {feed.hasNextPage && (
        <div className="flex justify-center">
          <Button onClick={() => feed.fetchNextPage()} disabled={feed.isFetchingNextPage}>
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
