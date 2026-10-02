import { forwardRef, useState } from "react";
import type { ActionStatus, Opportunity } from "../api/client";
import { ago, deadline, posted, shortLocation, sourceLabel, STATUS_LABEL } from "../format";
import { Badge, CompanyLogo } from "./ui";

const DEADLINE_TONE = { urgent: "red", soon: "amber", normal: "neutral", past: "neutral" } as const;
const action = "rounded-md px-1.5 py-0.5 hover:bg-zinc-100 hover:text-zinc-900 dark:hover:bg-zinc-800 dark:hover:text-zinc-100";

type Props = {
  opportunity: Opportunity;
  selected?: boolean;
  fresh?: boolean;
  onStatus: (status: ActionStatus) => void;
  onSelect?: () => void;
};

/** One role in the feed, digest-style: who, what, where and when, and one way to apply. */
export const FeedRow = forwardRef<HTMLElement, Props>(function FeedRow({ opportunity: o, selected, fresh, onStatus, onSelect }, ref) {
  const title = o.title || "Untitled opportunity";
  const status = o.action?.status ?? "new";
  const due = deadline(o.deadline);
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
      if (!(error instanceof DOMException && error.name === "AbortError")) setShareStatus("Couldn't share. Copy the Apply link.");
    }
  }

  const meta = [shortLocation(o.location), posted(o.published_at)].filter(Boolean);

  return (
    <article
      ref={ref}
      tabIndex={-1}
      aria-label={`${o.company ? `${o.company}: ` : ""}${title}`}
      aria-current={selected ? "true" : undefined}
      onClick={onSelect}
      className={`flex gap-3 px-4 py-4 outline-none sm:px-5 ${selected ? "bg-zinc-50 shadow-[inset_3px_0_0] shadow-zinc-900 dark:bg-zinc-800/40 dark:shadow-zinc-100" : ""} ${
        fresh ? "animate-[flash_1.6s_ease-out]" : ""
      }`}
    >
      <CompanyLogo name={o.company || "?"} domain={o.company_domain} />
      <div className="min-w-0 flex-1">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="truncate text-[13px] font-medium text-zinc-600 dark:text-zinc-400">{o.company || "Unknown company"}</p>
            <h3 className="font-semibold leading-snug text-zinc-950 [overflow-wrap:anywhere] dark:text-zinc-50">{title}</h3>
          </div>
          {o.url ? (
            <a
              href={o.url}
              target="_blank"
              rel="noopener noreferrer"
              onClick={(e) => e.stopPropagation()}
              className="inline-flex h-9 shrink-0 items-center rounded-lg bg-zinc-950 px-3.5 text-sm font-semibold text-white hover:bg-zinc-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-900 dark:bg-white dark:text-zinc-950 dark:hover:bg-zinc-200"
            >
              Apply
            </a>
          ) : (
            <span className="shrink-0 text-xs text-zinc-500">No link yet</span>
          )}
        </div>
        <p title={o.location} className="mt-1.5 font-mono text-xs leading-relaxed text-zinc-500 dark:text-zinc-400">{meta.join(" · ")}</p>
        <div className="mt-2 flex flex-wrap items-center gap-1 text-xs text-zinc-500 dark:text-zinc-400">
          {due && <Badge tone={DEADLINE_TONE[due.tone]}>{due.label}</Badge>}
          {status !== "new" && status !== "saved" && status !== "ignored" && <Badge>{STATUS_LABEL[status] ?? status}</Badge>}
          <button
            type="button"
            aria-pressed={status === "saved"}
            onClick={(e) => {
              e.stopPropagation();
              onStatus(status === "saved" ? "new" : "saved");
            }}
            className={`${action} ${status === "saved" ? "font-semibold text-zinc-900 dark:text-zinc-100" : ""}`}
          >
            {status === "saved" ? "Saved" : "Save"}
          </button>
          {o.url && (
            <button type="button" onClick={(e) => { e.stopPropagation(); void share(); }} className={action}>
              Share
            </button>
          )}
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onStatus(status === "ignored" ? "new" : "ignored");
            }}
            className={action}
          >
            {status === "ignored" ? "Unignore" : "Ignore"}
          </button>
          {shareStatus && <span role="status" className="ml-1">{shareStatus}</span>}
          <span className="ml-auto font-mono text-[11px] text-zinc-400 dark:text-zinc-500">
            found {ago(o.first_seen)} · {o.sources.map(sourceLabel).join(", ")}
          </span>
        </div>
      </div>
    </article>
  );
});
