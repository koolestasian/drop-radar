import { forwardRef, useState } from "react";
import type { ActionStatus, Opportunity } from "../api/client";
import { ago, deadline, seenAfterPosted, sourceLabel, STATUS_LABEL } from "../format";
import { Badge, Button } from "./ui";

const DEADLINE_TONE = { urgent: "red", soon: "amber", normal: "neutral", past: "neutral" } as const;
const STATUSES: ActionStatus[] = ["new", "saved", "applied", "interview", "offer", "rejected", "ignored"];

function reasonLabel(reason: string): string {
  return reason.replace(/^(role|level): '(.*)'$/, "$2").replace(/^insider source: /, "");
}

type Props = {
  opportunity: Opportunity;
  selected?: boolean;
  fresh?: boolean;
  compact?: boolean;
  onStatus: (status: ActionStatus) => void;
  onSelect?: () => void;
  draggable?: boolean;
};

export const OpportunityCard = forwardRef<HTMLElement, Props>(function OpportunityCard(
  { opportunity: o, selected, fresh, compact, onStatus, onSelect, draggable },
  ref,
) {
  const due = deadline(o.deadline);
  const status = o.action?.status ?? "new";
  const seen = o.backfill ? null : seenAfterPosted(o);
  const title = o.title || "Untitled opportunity";
  const [shareStatus, setShareStatus] = useState("");

  async function share() {
    setShareStatus("");
    try {
      if (navigator.share) await navigator.share({ title: `${o.company}: ${title}`, url: o.url });
      else {
        await navigator.clipboard.writeText(o.url);
        setShareStatus("Link copied");
      }
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError"))
        setShareStatus("Couldn't share. Copy the Apply link.");
    }
  }

  return (
    <article
      ref={ref}
      tabIndex={-1}
      aria-label={`${o.company ? `${o.company}: ` : ""}${title}`}
      aria-current={selected ? "true" : undefined}
      onClick={onSelect}
      draggable={draggable}
      onDragStart={(e) => e.dataTransfer.setData("text/opportunity-id", o.id)}
      className={`group relative rounded-xl border bg-white p-4 shadow-sm outline-none transition-[box-shadow,border-color] dark:bg-zinc-900 ${
        selected
          ? "border-indigo-400 ring-2 ring-indigo-400/40 dark:border-indigo-500"
          : "border-zinc-200 dark:border-zinc-800"
      } ${fresh ? "animate-[flash_1.6s_ease-out]" : ""} ${draggable ? "cursor-grab active:cursor-grabbing" : ""}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-xs font-semibold tracking-wide text-zinc-500 uppercase dark:text-zinc-400">
            {o.company || "Unknown company"}
          </p>
          <h3 className="mt-0.5 font-semibold text-zinc-900 [overflow-wrap:anywhere] dark:text-zinc-50">{title}</h3>
          <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
            {[o.location, o.season].filter(Boolean).join(" · ") || "Location not listed"}
          </p>
        </div>
        {due && <Badge tone={DEADLINE_TONE[due.tone]}>{due.label}</Badge>}
      </div>

      {!compact && (
        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          {o.match.ok &&
            o.match.reasons
              .filter((r) => !r.startsWith("location unverified"))
              .map((r) => (
                <Badge key={r} tone="indigo" title={r}>
                  {reasonLabel(r)}
                </Badge>
              ))}
          {!o.match.ok && <Badge title={o.match.reasons.join("; ")}>not a match</Badge>}
          {o.status !== "New" && o.status !== "Open" && <Badge tone="amber">{o.status}</Badge>}
          {o.backfill && (
            <Badge title="It was already open when your sources first looked, so it never alerted your phone.">
              already open
            </Badge>
          )}
        </div>
      )}

      <p className="mt-3 text-xs text-zinc-500 dark:text-zinc-400">
        {o.sources.map(sourceLabel).join(", ")} · first seen {ago(o.first_seen)}
        {seen && ` · ${seen}`}
      </p>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        {o.url ? (
          <a
            href={o.url}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="inline-flex min-h-9 items-center rounded-lg bg-indigo-600 px-3 text-sm font-medium text-white hover:bg-indigo-500 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-500 dark:bg-indigo-500 dark:hover:bg-indigo-400"
          >
            Apply ↗
          </a>
        ) : (
          <span className="text-xs text-zinc-500">No apply link yet</span>
        )}
        {!compact && (
          <>
            {o.url && <Button variant="quiet" onClick={(e) => { e.stopPropagation(); void share(); }}>Share</Button>}
            <Button
              variant={status === "saved" ? "primary" : "ghost"}
              aria-pressed={status === "saved"}
              onClick={(e) => {
                e.stopPropagation();
                onStatus(status === "saved" ? "new" : "saved");
              }}
            >
              {status === "saved" ? "Saved" : "Save"}
            </Button>
            <Button
              variant="quiet"
              onClick={(e) => {
                e.stopPropagation();
                onStatus(status === "ignored" ? "new" : "ignored");
              }}
            >
              {status === "ignored" ? "Unignore" : "Ignore"}
            </Button>
          </>
        )}
        <label className="ml-auto flex items-center gap-1.5 text-xs text-zinc-500" onClick={(e) => e.stopPropagation()}>
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
      {shareStatus && <p role="status" className="mt-2 text-xs text-zinc-500">{shareStatus}</p>}
    </article>
  );
});
