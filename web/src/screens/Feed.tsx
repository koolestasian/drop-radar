import {
  useInfiniteQuery,
  useQuery,
  useQueryClient,
  type InfiniteData,
} from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  query,
  type Me,
  type Opportunity,
  type Page,
} from "../api/client";
import { FeedRow } from "../components/FeedRow";
import { Button, Empty, ErrorNote, Spinner } from "../components/ui";
import { ago } from "../format";
import { useSetStatus } from "../hooks";

type View = "new" | "open" | "all";
type Filters = {
  q: string;
  view: View;
  closingSoon: boolean;
  ignored: boolean;
};

const VIEWS: { id: View; label: string }[] = [
  { id: "new", label: "New" },
  { id: "open", label: "Already open" },
  { id: "all", label: "All jobs" },
];

// "Internships" before "New grad", like a digest; anything else last.
const GROUPS = ["Internships", "New grad", "Other roles"] as const;
const INTERN = /\b(intern(ship)?s?|co-?op)\b/i;
const NEW_GRAD =
  /\b(new (college )?grad(uate)?s?|graduate|early career|entry[- ]level|university|campus|junior)\b/i;
function group(o: Opportunity): (typeof GROUPS)[number] {
  // The title says it best; the enriched category only breaks a tie.
  for (const text of [o.title, o.category]) {
    if (INTERN.test(text)) return "Internships";
    if (NEW_GRAD.test(text)) return "New grad";
  }
  return "Other roles";
}

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

export function Feed({
  incoming,
  clearIncoming,
}: {
  incoming: Opportunity[];
  clearIncoming: () => void;
}) {
  const [filters, setFilters] = useState<Filters>({
    q: "",
    view: "new",
    closingSoon: false,
    ignored: false,
  });
  const q = useDebounced(filters.q);
  const active = useMemo(() => ({ ...filters, q }), [filters, q]);
  const qc = useQueryClient();
  const setStatus = useSetStatus();
  const me = useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/api/me") });
  const [selected, setSelected] = useState(0);
  const [fresh, setFresh] = useState<Set<string>>(new Set());
  const search = useRef<HTMLInputElement>(null);
  const rows = useRef<(HTMLElement | null)[]>([]);

  const feed = useInfiniteQuery({
    queryKey: feedKey(active),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      api<Page>(
        `/api/opportunities${query({
          include: active.view === "all" ? "all" : "matches",
          backfill: active.view === "all" ? undefined : active.view === "open",
          q: active.q,
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

  const loaded = useMemo(
    () => feed.data?.pages.flatMap((p) => p.items) ?? [],
    [feed.data],
  );
  // Grouped display order; j/k walk it top to bottom.
  const items = useMemo(
    () => GROUPS.flatMap((g) => loaded.filter((o) => group(o) === g)),
    [loaded],
  );
  const unseen = incoming.filter((o) => !loaded.some((i) => i.id === o.id));
  const plainFeed =
    active.view === "new" &&
    !active.q &&
    !active.closingSoon &&
    !active.ignored;

  function showIncoming() {
    qc.setQueryData<InfiniteData<Page>>(feedKey(active), (data) =>
      data
        ? {
            ...data,
            pages: [
              { ...data.pages[0], items: [...unseen, ...data.pages[0].items] },
              ...data.pages.slice(1),
            ],
          }
        : data,
    );
    setFresh(new Set(unseen.map((o) => o.id)));
    clearIncoming();
    setSelected(0);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (
        e.metaKey ||
        e.ctrlKey ||
        e.altKey ||
        target.closest("input, textarea, select")
      )
        return;
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
      else if (e.key === "a")
        setStatus.mutate({ id: current.id, status: "applied" });
      else if ((e.key === "o" || e.key === "Enter") && current.url)
        window.open(current.url, "_blank", "noopener");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [items, selected, setStatus]);

  const toggle = (key: "closingSoon" | "ignored") =>
    setFilters((f) => ({ ...f, [key]: !f[key] }));
  const count = `${loaded.length}${feed.hasNextPage ? "+" : ""}`;
  const heading = active.ignored
    ? "Ignored"
    : {
        new: `${count} new ${loaded.length === 1 ? "role" : "roles"}`,
        open: `${count} already open`,
        all: `${count} jobs`,
      }[active.view];
  const newest = loaded.reduce<string | null>(
    (m, o) => (!m || o.first_seen > m ? o.first_seen : m),
    null,
  );
  const pill = (on: boolean) =>
    `min-h-8 rounded-full px-3.5 text-sm font-medium transition-colors ${
      on
        ? "bg-zinc-950 text-white dark:bg-white dark:text-zinc-950"
        : "text-zinc-600 hover:text-zinc-950 dark:text-zinc-400 dark:hover:text-white"
    }`;

  let index = 0;
  return (
    <section
      aria-labelledby="feed-title"
      className="mx-auto max-w-3xl space-y-5"
    >
      <header className="space-y-3">
        <p className="inline-flex items-center gap-2 rounded-full border border-zinc-200 bg-white px-3 py-1 font-mono text-xs text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-400">
          <span className="size-1.5 rounded-full bg-emerald-500" aria-hidden />
          {[
            me.data && `${me.data.sources} sources watched`,
            newest && `newest found ${ago(newest)}`,
          ]
            .filter(Boolean)
            .join(" · ") || "Watching your sources"}
        </p>
        <h1
          id="feed-title"
          className="text-3xl font-black tracking-tight text-zinc-950 sm:text-4xl dark:text-white"
        >
          {feed.isPending ? "Your feed" : heading}
        </h1>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          {active.view === "new" &&
            "Roles that match your profile, posted since the radar started watching. Newest first."}
          {active.view === "open" &&
            "Matching roles that were already up when the radar first looked. Still worth a pass."}
          {active.view === "all" &&
            "Everything your sources found, matching or not."}
        </p>
      </header>

      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <div className="-mx-4 flex items-center gap-1 overflow-x-auto px-4 sm:mx-0 sm:px-0">
          <div
            role="group"
            aria-label="Show"
            className="flex shrink-0 rounded-full border border-zinc-200 bg-white p-1 dark:border-zinc-800 dark:bg-zinc-900"
          >
            {VIEWS.map((v) => (
              <button
                key={v.id}
                type="button"
                aria-pressed={filters.view === v.id}
                onClick={() => setFilters((f) => ({ ...f, view: v.id }))}
                className={pill(filters.view === v.id)}
              >
                {v.label}
              </button>
            ))}
          </div>
          <button
            type="button"
            aria-pressed={filters.closingSoon}
            onClick={() => toggle("closingSoon")}
            className={`${pill(filters.closingSoon)} shrink-0`}
          >
            Closing soon
          </button>
          <button
            type="button"
            aria-pressed={filters.ignored}
            onClick={() => toggle("ignored")}
            className={`${pill(filters.ignored)} shrink-0`}
          >
            Ignored
          </button>
        </div>
        <input
          ref={search}
          type="search"
          value={filters.q}
          onChange={(e) => setFilters((f) => ({ ...f, q: e.target.value }))}
          placeholder="Search title or company  ( / )"
          aria-label="Search title or company"
          className="min-h-10 w-full min-w-0 rounded-full border border-zinc-200 bg-white px-4 text-sm sm:ml-auto sm:w-64 dark:border-zinc-800 dark:bg-zinc-900"
        />
      </div>

      {unseen.length > 0 && plainFeed && (
        <div className="sticky top-16 z-10 flex justify-center">
          <Button
            variant="primary"
            onClick={showIncoming}
            className="rounded-full shadow-lg"
          >
            ↑ {unseen.length} new {unseen.length === 1 ? "drop" : "drops"}
          </Button>
        </div>
      )}

      {feed.isPending ? (
        <Spinner label="Loading your feed" />
      ) : feed.isError ? (
        <ErrorNote error={feed.error} retry={() => feed.refetch()} />
      ) : items.length === 0 ? (
        <Empty title={plainFeed ? "No new roles yet" : "Nothing here"}>
          {plainFeed ? (
            <>
              New postings that match your profile land here the moment a source
              finds them, and buzz your phone once alerts are on.{" "}
              <button
                type="button"
                className="underline"
                onClick={() => setFilters((f) => ({ ...f, view: "open" }))}
              >
                See what's already open
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
                    return (
                      <li key={o.id}>
                        <FeedRow
                          ref={(el) => {
                            rows.current[i] = el;
                          }}
                          opportunity={o}
                          selected={i === selected}
                          fresh={fresh.has(o.id)}
                          onSelect={() => setSelected(i)}
                          onStatus={(status) =>
                            setStatus.mutate({ id: o.id, status })
                          }
                        />
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
          <Button
            onClick={() => feed.fetchNextPage()}
            disabled={feed.isFetchingNextPage}
            className="rounded-full"
          >
            {feed.isFetchingNextPage ? "Loading…" : "Load more"}
          </Button>
        </div>
      )}
      {setStatus.isError && <ErrorNote error={setStatus.error} />}
      <p className="hidden text-center text-xs text-zinc-500 sm:block">
        <kbd>j</kbd>/<kbd>k</kbd> move · <kbd>s</kbd> save · <kbd>i</kbd> ignore
        · <kbd>a</kbd> applied · <kbd>o</kbd> open · <kbd>/</kbd> search
      </p>
    </section>
  );
}
