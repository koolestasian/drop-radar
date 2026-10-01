import { useQueries } from "@tanstack/react-query";
import { useState } from "react";
import { api, query, type ActionStatus, type Opportunity, type Page } from "../api/client";
import { OpportunityCard } from "../components/OpportunityCard";
import { Empty, ErrorNote, Spinner } from "../components/ui";
import { BOARD_COLUMNS } from "../format";
import { useSetStatus } from "../hooks";

function Notes({ opportunity }: { opportunity: Opportunity }) {
  const setStatus = useSetStatus();
  const saved = opportunity.action?.notes ?? "";
  const [draft, setDraft] = useState(saved);
  return (
    <label className="mt-2 block">
      <span className="sr-only">Notes for {opportunity.title}</span>
      <textarea
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => draft !== saved && setStatus.mutate({ id: opportunity.id, notes: draft })}
        rows={draft ? 3 : 1}
        placeholder="Notes (saved when you leave the box)"
        className="w-full resize-y rounded-lg border border-zinc-200 bg-zinc-50 px-2 py-1.5 text-sm dark:border-zinc-800 dark:bg-zinc-950"
      />
    </label>
  );
}

export function Board() {
  const setStatus = useSetStatus();
  const [over, setOver] = useState<ActionStatus | null>(null);
  const columns = useQueries({
    queries: BOARD_COLUMNS.map((c) => ({
      queryKey: ["opportunities", "board", c.status],
      queryFn: () => api<Page>(`/api/opportunities${query({ action: c.status, include: "all", limit: 200 })}`),
    })),
  });

  if (columns.some((c) => c.isPending)) return <Spinner label="Loading your board" />;
  const failed = columns.find((c) => c.isError);
  if (failed) return <ErrorNote error={failed.error} retry={() => columns.forEach((c) => c.refetch())} />;
  if (columns.every((c) => !c.data?.items.length))
    return (
      <Empty title="Your board is empty">
        Save something from the feed (or press <kbd>s</kbd> on it) and it lands here. Move it along as you apply.
      </Empty>
    );

  const drop = (status: ActionStatus) => (e: React.DragEvent) => {
    e.preventDefault();
    setOver(null);
    const id = e.dataTransfer.getData("text/opportunity-id");
    if (id) setStatus.mutate({ id, status });
  };

  return (
    <section aria-labelledby="board-title">
      <h1 id="board-title" className="sr-only">
        Application board
      </h1>
      {setStatus.isError && <ErrorNote error={setStatus.error} />}
      <div className="relative -mx-4 flex snap-x snap-mandatory gap-3 overflow-x-auto px-4 pb-4 lg:mx-0 lg:grid lg:grid-cols-5 lg:overflow-visible lg:px-0">
        {BOARD_COLUMNS.map((column, i) => {
          const items = columns[i].data?.items ?? [];
          return (
            <div
              key={column.status}
              onDragOver={(e) => {
                e.preventDefault();
                setOver(column.status);
              }}
              onDragLeave={() => setOver(null)}
              onDrop={drop(column.status)}
              aria-label={`${column.label} column`}
              className={`w-[85%] max-w-sm shrink-0 snap-start rounded-2xl p-2 sm:w-80 lg:w-auto ${
                over === column.status ? "bg-indigo-50 dark:bg-indigo-950/40" : "bg-zinc-100/70 dark:bg-zinc-900/50"
              }`}
            >
              <h2 className="flex items-center justify-between px-2 py-1 text-sm font-semibold text-zinc-700 dark:text-zinc-300">
                {column.label}
                <span className="text-xs font-normal text-zinc-500">{items.length}</span>
              </h2>
              <ol className="mt-1 space-y-2">
                {items.map((o) => (
                  <li key={o.id}>
                    <OpportunityCard
                      opportunity={o}
                      compact
                      draggable
                      onStatus={(status) => setStatus.mutate({ id: o.id, status })}
                    />
                    <Notes opportunity={o} />
                  </li>
                ))}
                {items.length === 0 && <li className="px-2 py-6 text-center text-xs text-zinc-500">Drop cards here</li>}
              </ol>
            </div>
          );
        })}
      </div>
    </section>
  );
}
