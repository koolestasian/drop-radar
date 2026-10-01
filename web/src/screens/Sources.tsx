import { useQuery } from "@tanstack/react-query";
import { api, type Metrics, type SourceHealth } from "../api/client";
import { Badge, Empty, ErrorNote, Spinner } from "../components/ui";
import { ago, duration, sourceLabel } from "../format";

function state(h: SourceHealth) {
  if (h.disabled) return { label: "disabled", tone: "red" as const };
  if (h.fail_count > 0) return { label: `${h.fail_count} failing`, tone: "amber" as const };
  if (h.last_ok) return { label: "ok", tone: "green" as const };
  return { label: "first poll pending", tone: "neutral" as const };
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

  if (health.isPending) return <Spinner label="Checking your sources" />;
  if (health.isError) return <ErrorNote error={health.error} retry={() => health.refetch()} />;

  const rows = [...health.data].sort((a, b) => Number(b.disabled) - Number(a.disabled) || b.fail_count - a.fail_count);
  const problems = rows.filter((h) => h.disabled || h.fail_count > 0).length;
  const days = Object.entries(metrics.data?.items_per_day ?? {});
  const peak = Math.max(1, ...days.map(([, n]) => n));

  return (
    <section aria-labelledby="sources-title" className="space-y-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 id="sources-title" className="text-lg font-semibold">
          Your sources
        </h1>
        <p className="text-sm text-zinc-500">
          {rows.length} watched · {problems ? `${problems} need attention` : "all healthy"}
        </p>
      </div>

      {metrics.data && (
        <div className="grid gap-4 md:grid-cols-2">
          <div className="rounded-xl border border-zinc-200 p-4 dark:border-zinc-800">
            <h2 className="text-sm font-semibold">Drop latency (posted → your phone)</h2>
            {metrics.data.latency.length === 0 ? (
              <p className="mt-2 text-sm text-zinc-500">No alerts sent yet.</p>
            ) : (
              <table className="mt-2 w-full text-sm">
                <thead className="text-left text-xs text-zinc-500">
                  <tr>
                    <th className="py-1 font-medium">Source</th>
                    <th className="py-1 font-medium">p50</th>
                    <th className="py-1 font-medium">p95</th>
                    <th className="py-1 font-medium">n</th>
                  </tr>
                </thead>
                <tbody>
                  {metrics.data.latency.map((l) => (
                    <tr key={l.source} className="border-t border-zinc-100 dark:border-zinc-800">
                      <td className="py-1">{sourceLabel(l.source)} <span className="text-zinc-500">{slug(l.source)}</span></td>
                      <td className="py-1">{duration(l.p50 * 1000)}</td>
                      <td className="py-1">{duration(l.p95 * 1000)}</td>
                      <td className="py-1 text-zinc-500">{l.n}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
          <div className="rounded-xl border border-zinc-200 p-4 dark:border-zinc-800">
            <h2 className="text-sm font-semibold">New items, last 7 days</h2>
            {days.length === 0 ? (
              <p className="mt-2 text-sm text-zinc-500">Nothing new yet — boards are seeded on their first poll.</p>
            ) : (
              <ul className="mt-3 flex h-24 items-end gap-2" aria-label="Items per day">
                {days.map(([day, n]) => (
                  <li key={day} className="flex flex-1 flex-col items-center gap-1" title={`${day}: ${n}`}>
                    <span className="w-full rounded-t bg-indigo-500/80" style={{ height: `${(n / peak) * 72}px` }} />
                    <span className="text-[10px] text-zinc-500">{day.slice(5)}</span>
                  </li>
                ))}
              </ul>
            )}
            <p className="mt-3 text-xs text-zinc-500">
              AI enrichment today: {metrics.data.llm_tokens_today.toLocaleString()} of{" "}
              {metrics.data.llm_daily_budget.toLocaleString()} tokens (shared)
            </p>
          </div>
        </div>
      )}

      {rows.length === 0 ? (
        <Empty title="No sources yet">Add companies in Settings → Watchlist.</Empty>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-zinc-200 dark:border-zinc-800">
          <table className="w-full min-w-[36rem] text-sm">
            <thead className="bg-zinc-50 text-left text-xs text-zinc-500 dark:bg-zinc-900">
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
                  <tr key={h.name} className="border-t border-zinc-100 dark:border-zinc-800">
                    <td className="px-3 py-2">
                      <span className="font-medium">{slug(h.name)}</span>{" "}
                      <span className="text-zinc-500">{sourceLabel(h.name)}</span>
                    </td>
                    <td className="px-3 py-2">
                      <Badge tone={s.tone}>{s.label}</Badge>
                    </td>
                    <td className="px-3 py-2 text-zinc-600 dark:text-zinc-400">{ago(h.last_ok) || "—"}</td>
                    <td className="px-3 py-2">{h.items_24h}</td>
                    <td className="max-w-xs truncate px-3 py-2 text-zinc-500" title={h.last_error ?? ""}>
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
