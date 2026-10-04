import { useQueries } from "@tanstack/react-query";
import { useState } from "react";
import { ArrowUpRight, Kanban } from "lucide-react";
import { cn } from "cn";
import { api, query, type ActionStatus, type Opportunity, type Page } from "../api/client";
import { CompanyLogo, ErrorNote, ListSkeleton } from "../components/common";
import { Button } from "@/components/ui/button";
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { Textarea } from "@/components/ui/textarea";
import { ago, BOARD_COLUMNS, deadline, posted, shortLocation, STATUS_LABEL } from "../format";
import { useSetStatus } from "../hooks";
import { stockOf } from "../stock";

const STATUSES: ActionStatus[] = ["new", "saved", "applied", "interview", "offer", "rejected", "ignored"];

/** A card on the board: drag it between columns, or pick a status (the picker is the touch and keyboard route). */
function BoardCard({ o, onStatus, onNotes }: { o: Opportunity; onStatus: (status: ActionStatus) => void; onNotes: (notes: string) => void }) {
  const title = o.title || "Untitled opportunity";
  const status = o.action?.status ?? "new";
  const stock = stockOf(o);
  const due = deadline(o.deadline);
  const saved = o.action?.notes ?? "";
  const [draft, setDraft] = useState(saved);
  return (
    <article
      aria-label={`${o.company ? `${o.company}: ` : ""}${title}`}
      draggable
      onDragStart={(e) => e.dataTransfer.setData("text/opportunity-id", o.id)}
      className={cn(
        "flex cursor-grab flex-col gap-2.5 rounded-xl border border-stock-line p-3 shadow-[0_2px_0_var(--stock-line)] active:cursor-grabbing",
        stock.bg,
      )}
    >
      <div className="flex items-start gap-3">
        <CompanyLogo name={o.company || "?"} domain={o.company_domain} className="size-9" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-muted-foreground">{o.company || "Unknown company"}</p>
          <h3 className="leading-snug font-semibold [overflow-wrap:anywhere]">{title}</h3>
        </div>
      </div>
      <p className="stamp text-muted-foreground">
        {[shortLocation(o.location), posted(o.published_at), `found ${ago(o.first_seen)}`, due?.label].filter(Boolean).join(" · ")}
      </p>
      <div className="flex flex-wrap items-center gap-2">
        {o.url ? (
          <Button asChild>
            <a href={o.url} target="_blank" rel="noopener noreferrer" aria-label={`Apply: ${o.company ? `${o.company}, ` : ""}${title}`}>
              Apply
              <ArrowUpRight data-icon="inline-end" />
            </a>
          </Button>
        ) : (
          <span className="text-xs text-muted-foreground">No link yet</span>
        )}
        <label className="ml-auto min-w-0 max-w-full">
          <span className="sr-only">Status for {title}</span>
          <select
            value={STATUSES.includes(status as ActionStatus) ? status : "new"}
            onChange={(e) => onStatus(e.target.value as ActionStatus)}
            className="h-11 max-w-full rounded-lg border border-input bg-background/70 px-2 text-base sm:h-9 sm:text-sm"
          >
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {STATUS_LABEL[s]}
              </option>
            ))}
          </select>
        </label>
      </div>
      <label>
        <span className="sr-only">Notes for {title}</span>
        <Textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => draft !== saved && onNotes(draft)}
          rows={draft ? 3 : 1}
          placeholder="Notes (saved when you leave the box)"
          className="min-h-0 bg-background/70 text-base sm:text-sm"
        />
      </label>
    </article>
  );
}

export function Board() {
  const setStatus = useSetStatus();
  const [over, setOver] = useState<ActionStatus | null>(null);
  const columns = useQueries({
    queries: [...BOARD_COLUMNS.map((c) => c.status), "ignored" as const].map((status) => ({
      queryKey: ["opportunities", "board", status],
      queryFn: () => api<Page>(`/api/opportunities${query({ action: status, include: "all", limit: 200 })}`),
    })),
  });
  const hidden = columns[BOARD_COLUMNS.length].data?.items ?? [];

  if (columns.some((c) => c.isPending)) return <ListSkeleton rows={3} label="Loading your board" />;
  const failed = columns.find((c) => c.isError);
  if (failed) return <ErrorNote error={failed.error} retry={() => columns.forEach((c) => c.refetch())} />;
  if (columns.every((c) => !c.data?.items.length))
    return (
      <Empty className="rounded-xl border border-dashed border-border">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <Kanban />
          </EmptyMedia>
          <EmptyTitle>Your board is empty</EmptyTitle>
          <EmptyDescription>
            Save something from Jobs (or press <kbd>s</kbd> on it) and it lands here. Move it along as you apply.
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    );

  const drop = (status: ActionStatus) => (e: React.DragEvent) => {
    e.preventDefault();
    setOver(null);
    const id = e.dataTransfer.getData("text/opportunity-id");
    if (id) setStatus.mutate({ id, status });
  };

  return (
    <section aria-labelledby="board-title" className="flex flex-col gap-4">
      <h1 id="board-title" className="text-3xl font-bold tracking-tight">
        Tracker
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
              className={cn(
                "w-[85%] max-w-sm shrink-0 snap-start rounded-2xl border border-border p-2 sm:w-80 lg:w-auto",
                over === column.status ? "bg-accent" : "bg-muted/60",
              )}
            >
              <h2 className="flex items-center justify-between px-2 py-1.5 text-sm font-semibold">
                {column.label}
                <span className="stamp font-normal text-muted-foreground">{items.length}</span>
              </h2>
              <ol className="mt-1 flex flex-col gap-2.5">
                {items.map((o) => (
                  <li key={o.id}>
                    <BoardCard o={o} onStatus={(status) => setStatus.mutate({ id: o.id, status })} onNotes={(notes) => setStatus.mutate({ id: o.id, notes })} />
                  </li>
                ))}
                {items.length === 0 && <li className="px-2 py-6 text-center text-sm text-muted-foreground">Drop cards here</li>}
              </ol>
            </div>
          );
        })}
      </div>
      <details className="rounded-2xl border border-border bg-muted/60 p-3">
        <summary className="cursor-pointer text-sm font-semibold">Hidden ({hidden.length})</summary>
        <ol className="mt-3 flex flex-col gap-2">
          {hidden.map((o) => (
            <li key={o.id} className="flex items-center gap-3 rounded-lg border border-border bg-card px-3 py-2">
              <p className="min-w-0 flex-1 truncate text-sm">
                <span className="font-medium">{o.company || "Unknown company"}</span> · {o.title || "Untitled opportunity"}
              </p>
              <Button variant="outline" onClick={() => setStatus.mutate({ id: o.id, status: "new" })} aria-label={`Unhide ${o.title || "role"}`}>
                Unhide
              </Button>
            </li>
          ))}
          {hidden.length === 0 && <li className="text-sm text-muted-foreground">Roles you hide on Jobs wait here, out of your lists.</li>}
        </ol>
      </details>
    </section>
  );
}
