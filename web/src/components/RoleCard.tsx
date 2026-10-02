import { forwardRef } from "react";
import { ArrowUpRight, Bookmark, BookmarkCheck, EyeOff, Eye } from "lucide-react";
import { cn } from "cn";
import type { ActionStatus, Opportunity } from "../api/client";
import { ago, deadline, posted, shortLocation } from "../format";
import { stockOf } from "../stock";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { CompanyLogo } from "./common";

const DEADLINE_TONE = { urgent: "text-destructive", soon: "text-foreground", normal: "text-muted-foreground", past: "text-muted-foreground" } as const;

export async function shareLink(o: Opportunity): Promise<string> {
  const title = o.title || "Untitled opportunity";
  try {
    if (navigator.share) await navigator.share({ title: `${o.company}: ${title}`, url: o.url });
    else {
      await navigator.clipboard.writeText(o.url);
      return "Link copied";
    }
  } catch (error) {
    if (!(error instanceof DOMException && error.name === "AbortError")) return "Couldn't share. Copy the Apply link.";
  }
  return "";
}

type Props = {
  opportunity: Opportunity;
  selected?: boolean;
  fresh?: boolean;
  onStatus: (status: ActionStatus) => void;
  onOpen?: () => void;
};

/** One role as an index card: the stock colour is its state, the Apply button is always at the same edge. */
export const RoleCard = forwardRef<HTMLElement, Props>(function RoleCard({ opportunity: o, selected, fresh, onStatus, onOpen }, ref) {
  const title = o.title || "Untitled opportunity";
  const status = o.action?.status ?? "new";
  const stock = stockOf(o);
  const due = deadline(o.deadline);
  const meta = [shortLocation(o.location), posted(o.published_at)].filter(Boolean).join(" · ");
  const stop = (fn: () => void) => (e: React.MouseEvent) => {
    e.stopPropagation();
    fn();
  };

  return (
    <article
      ref={ref}
      tabIndex={-1}
      aria-label={`${o.company ? `${o.company}: ` : ""}${title}`}
      aria-current={selected ? "true" : undefined}
      onClick={onOpen}
      className={cn(
        "flex cursor-pointer flex-col gap-2.5 rounded-xl border border-stock-line p-3.5 shadow-[0_1px_0_var(--stock-line),0_8px_16px_-12px_rgb(0_0_0/0.4)] outline-none sm:p-4",
        stock.bg,
        selected && "ring-2 ring-foreground",
        fresh && "animate-[pin-in_0.55s_cubic-bezier(0.16,1,0.3,1)]",
      )}
    >
      <div className="flex gap-3">
        <CompanyLogo name={o.company || "?"} domain={o.company_domain} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-muted-foreground">{o.company || "Unknown company"}</p>
          <h3 className="text-[17px] leading-snug font-semibold [overflow-wrap:anywhere]">
            <button type="button" onClick={stop(() => onOpen?.())} className="text-left hover:underline">
              {title}
            </button>
          </h3>
          <p title={o.location} className="stamp mt-1 text-muted-foreground">
            {meta}
          </p>
        </div>
        {o.url ? (
          <Button asChild size="lg" className="shrink-0 self-start" onClick={(e: React.MouseEvent) => e.stopPropagation()}>
            <a href={o.url} target="_blank" rel="noopener noreferrer" aria-label={`Apply: ${o.company ? `${o.company}, ` : ""}${title}`}>
              Apply
              <ArrowUpRight data-icon="inline-end" />
            </a>
          </Button>
        ) : (
          <span className="shrink-0 self-start text-xs text-muted-foreground">No link yet</span>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        {stock.label && (
          <Badge variant="outline" className="bg-background/60">
            {stock.label}
          </Badge>
        )}
        {due && <span className={cn("stamp font-medium", DEADLINE_TONE[due.tone])}>{due.label}</span>}
        <span className="stamp min-w-0 truncate text-muted-foreground">
          found {ago(o.first_seen)}
        </span>
        <div className="ml-auto flex items-center">
          <Button variant="ghost" size="icon" aria-pressed={status === "saved"} aria-label={status === "saved" ? "Saved: tap to unsave" : "Save"} onClick={stop(() => onStatus(status === "saved" ? "new" : "saved"))}>
            {status === "saved" ? <BookmarkCheck /> : <Bookmark />}
          </Button>
          <Button variant="ghost" size="icon" aria-label={status === "ignored" ? "Unignore" : "Ignore"} onClick={stop(() => onStatus(status === "ignored" ? "new" : "ignored"))}>
            {status === "ignored" ? <Eye /> : <EyeOff />}
          </Button>
        </div>
      </div>
    </article>
  );
});
