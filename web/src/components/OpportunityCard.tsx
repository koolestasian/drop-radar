import type { ActionStatus, Opportunity } from "../api/client";
import { ago, deadline, sourceLabel, STATUS_LABEL } from "../format";
import { Badge } from "./ui";

const DEADLINE_TONE = { urgent: "red", soon: "amber", normal: "neutral", past: "neutral" } as const;
const STATUSES: ActionStatus[] = ["new", "saved", "applied", "interview", "offer", "rejected", "ignored"];

/** A Board card: drag it between columns or pick a status. The feed uses FeedRow. */
export function OpportunityCard({ opportunity: o, onStatus }: { opportunity: Opportunity; onStatus: (status: ActionStatus) => void }) {
  const due = deadline(o.deadline);
  const status = o.action?.status ?? "new";
  const title = o.title || "Untitled opportunity";

  return (
    <article
      aria-label={`${o.company ? `${o.company}: ` : ""}${title}`}
      draggable
      onDragStart={(e) => e.dataTransfer.setData("text/opportunity-id", o.id)}
      className="cursor-grab rounded-xl border border-zinc-200 bg-white p-3 shadow-sm active:cursor-grabbing dark:border-zinc-800 dark:bg-zinc-900"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-[13px] font-medium text-zinc-600 dark:text-zinc-400">{o.company || "Unknown company"}</p>
          <h3 className="font-semibold leading-snug text-zinc-950 [overflow-wrap:anywhere] dark:text-zinc-50">{title}</h3>
        </div>
        {due && <Badge tone={DEADLINE_TONE[due.tone]}>{due.label}</Badge>}
      </div>
      <p className="mt-1.5 font-mono text-xs leading-relaxed text-zinc-500 dark:text-zinc-400">
        {[o.location || "Location not listed", o.sources.map(sourceLabel).join(", "), `found ${ago(o.first_seen)}`].join(" · ")}
      </p>
      <div className="mt-3 flex items-center gap-2">
        {o.url ? (
          <a
            href={o.url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex h-9 items-center rounded-lg bg-zinc-950 px-3.5 text-sm font-semibold text-white hover:bg-zinc-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-900 dark:bg-white dark:text-zinc-950 dark:hover:bg-zinc-200"
          >
            Apply
          </a>
        ) : (
          <span className="text-xs text-zinc-500">No link yet</span>
        )}
        <label className="ml-auto flex items-center gap-1.5 text-xs text-zinc-500">
          <span className="sr-only">Status for {title}</span>
          <select
            value={STATUSES.includes(status as ActionStatus) ? status : "new"}
            onChange={(e) => onStatus(e.target.value as ActionStatus)}
            className="min-h-9 rounded-lg border border-zinc-300 bg-white px-2 text-sm text-zinc-800 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
          >
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {STATUS_LABEL[s]}
              </option>
            ))}
          </select>
        </label>
      </div>
    </article>
  );
}
