import { useQuery } from "@tanstack/react-query";
import { cn } from "cn";
import { api, type Metrics, type SourceHealth } from "../api/client";
import { ErrorNote, ListSkeleton } from "../components/common";
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty";
import { ago, duration, sourceLabel } from "../format";

function state(h: SourceHealth) {
  if (h.disabled) return { label: "disabled", bg: "bg-destructive/15 text-destructive" };
  if (h.fail_count > 0) return { label: `${h.fail_count} failing`, bg: "bg-stock-fresh" };
  if (h.stale) return { label: "poll overdue", bg: "bg-stock-fresh" };
  if (h.last_ok) return { label: "ok", bg: "bg-stock-applied" };
  return { label: "first poll pending", bg: "bg-stock-quiet" };
}

function slug(name: string) {
  return name.split(".").slice(2).join(".") || name;
}

export function Sources() {
  const health = useQuery({
    queryKey: ["sources", "health"],
    queryFn: () => api<SourceHealth[]>("/api/sources/health"),
    refetchInterval: 30_000,
  });
  const metrics = useQuery({ queryKey: ["metrics"], queryFn: () => api<Metrics>("/api/metrics"), refetchInterval: 60_000 });

  if (health.isPending) return <ListSkeleton rows={4} label="Checking your sources" />;
  if (health.isError) return <ErrorNote error={health.error} retry={() => health.refetch()} />;

  const rows = [...health.data].sort((a, b) => Number(b.disabled) - Number(a.disabled) || Number(b.stale) - Number(a.stale) || b.fail_count - a.fail_count);
  const problems = rows.filter((h) => h.disabled || h.stale || h.fail_count > 0).length;
  const days = Object.entries(metrics.data?.items_per_day ?? {});
  const peak = Math.max(1, ...days.map(([, n]) => n));

  return (
    <section aria-labelledby="sources-title" className="flex flex-col gap-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 id="sources-title" className="text-3xl font-bold tracking-tight">
          Your sources
        </h1>
        <p className="stamp text-muted-foreground">
          {rows.length} watched · {problems ? `${problems} need attention` : "all healthy"}
        </p>
      </div>

      {metrics.data && (
        <div className="grid gap-4 md:grid-cols-2">
          <div className="rounded-xl border border-border bg-card p-4">
            <h2 className="text-sm font-semibold">Alert speed: posted to push sent</h2>
            <p className="mt-1 text-xs text-muted-foreground">Median (p50) and slow case (p95) per source. Where the post time is unknown, it counts from when we first saw it. This measures when your push was sent, not when your phone received it.</p>
            {metrics.data.latency.length === 0 ? (
              <p className="mt-2 text-sm text-muted-foreground">No alerts sent yet.</p>
            ) : (
              <table className="stamp mt-2 w-full">
                <thead className="text-left text-xs text-muted-foreground">
                  <tr>
                    <th className="py-1 font-medium">Source</th>
                    <th className="py-1 text-right font-medium">p50</th>
                    <th className="py-1 pl-4 text-right font-medium">p95</th>
                    <th className="py-1 pl-4 text-right font-medium">n</th>
                  </tr>
                </thead>
                <tbody>
                  {metrics.data.latency.map((l) => (
                    <tr key={l.source} className="border-t border-border">
                      <td className="py-1 font-sans text-sm">{sourceLabel(l.source)} <span className="text-muted-foreground">{slug(l.source)}</span></td>
                      <td className="py-1 text-right">{duration(l.p50 * 1000)}</td>
                      <td className="py-1 pl-4 text-right">{duration(l.p95 * 1000)}</td>
                      <td className="py-1 pl-4 text-right text-muted-foreground">{l.n}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
          <div className="rounded-xl border border-border bg-card p-4">
            <h2 className="text-sm font-semibold">New items, last 7 days</h2>
            {days.length === 0 ? (
              <p className="mt-2 text-sm text-muted-foreground">Nothing new yet — boards are seeded on their first poll.</p>
            ) : (
              <ul className="mt-3 flex h-24 items-end gap-2" aria-label="Items per day">
                {days.map(([day, n]) => (
                  <li key={day} className="flex flex-1 flex-col items-center gap-1" title={`${day}: ${n}`}>
                    <span className="w-full rounded-t bg-foreground/80" style={{ height: `${(n / peak) * 72}px` }} />
                    <span className="stamp text-[11px] text-muted-foreground">{day.slice(5)}</span>
                  </li>
                ))}
              </ul>
            )}
            <p className="mt-3 text-xs text-muted-foreground">
              AI enrichment today: {metrics.data.llm_tokens_today.toLocaleString()} of{" "}
              {metrics.data.llm_daily_budget.toLocaleString()} tokens (shared)
            </p>
          </div>
        </div>
      )}

      {rows.length === 0 ? (
        <Empty className="rounded-xl border border-dashed border-border">
          <EmptyHeader>
            <EmptyTitle>No sources yet</EmptyTitle>
            <EmptyDescription>Add companies in Settings, then Watchlist.</EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border bg-card">
          <table className="w-full min-w-[36rem] text-sm">
            <thead className="bg-muted text-left text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-medium">Source</th>
                <th className="px-3 py-2 font-medium">State</th>
                <th className="px-3 py-2 font-medium">Last OK</th>
                <th className="px-3 py-2 font-medium">New 24h</th>
                <th className="px-3 py-2 font-medium">Last error</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((h) => {
                const s = state(h);
                return (
                  <tr key={h.name} className="border-t border-border">
                    <td className="px-3 py-2">
                      <span className="font-medium">{slug(h.name)}</span>{" "}
                      <span className="text-muted-foreground">{sourceLabel(h.name)}</span>
                    </td>
                    <td className="px-3 py-2">
                      <span className={cn("inline-flex rounded-full border border-stock-line px-2 py-0.5 text-xs font-medium", s.bg)}>{s.label}</span>
                    </td>
                    <td className="px-3 py-2 text-muted-foreground">{ago(h.last_ok) || "—"}</td>
                    <td className="stamp px-3 py-2">{h.items_24h}</td>
                    <td className="max-w-xs truncate px-3 py-2 text-muted-foreground" title={h.last_error ?? ""}>
                      {h.last_error ?? ""}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
