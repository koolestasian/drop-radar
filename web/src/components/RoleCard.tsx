import { forwardRef } from "react";
import { ArrowUpRight, Bookmark, BookmarkCheck, EyeOff, Eye } from "lucide-react";
import { cn } from "cn";
import type { ActionStatus, Opportunity } from "../api/client";
import { ago, deadline, LEVEL_LABEL, posted, shortLocation } from "../format";
import { stockOf } from "../stock";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { CompanyLogo, WorkModelBadge } from "./common";

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
  compact?: boolean;
  onStatus?: (status: ActionStatus) => void; // absent for a guest: no Save or Hide
  onOpen?: () => void;
};

/** One role as an index card: the stock colour is its state, the Apply button is always at the same edge. */
export const RoleCard = forwardRef<HTMLElement, Props>(function RoleCard({ opportunity: o, selected, fresh, compact, onStatus, onOpen }, ref) {
  const title = o.title || "Untitled opportunity";
  const status = o.action?.status ?? "new";
  const stock = stockOf(o);
  const due = deadline(o.deadline);
  const shownPay = o.pay || o.pay_estimate;
  const meta = [shortLocation(o.location), posted(o.published_at) ?? `found ${ago(o.first_seen)}`].filter(Boolean).join(" · "); // one date: posted, or found when the posting gives none
  const level = o.level && (
    <Badge variant="outline" className="bg-background/60">
      {LEVEL_LABEL[o.level]}
    </Badge>
  );
  const stop = (fn: () => void) => (e: React.MouseEvent) => {
    e.stopPropagation();
    fn();
  };

  if (compact)
    return (
      <article
        ref={ref}
        tabIndex={-1}
        aria-label={`${o.company ? `${o.company}: ` : ""}${title}`}
        aria-current={selected ? "true" : undefined}
        onClick={onOpen}
        className={cn(
          "flex cursor-pointer items-center gap-2.5 rounded-lg border border-stock-line px-3 py-1.5 outline-none",
          stock.bg,
          selected && "ring-2 ring-foreground",
          fresh && "animate-[pin-in_0.55s_cubic-bezier(0.16,1,0.3,1)]",
        )}
      >
        <CompanyLogo name={o.company || "?"} domain={o.company_domain} className="size-7 shrink-0" />
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-[15px] leading-tight font-semibold">
            <button type="button" onClick={stop(() => onOpen?.())} className="max-w-full truncate text-left hover:underline">
              {title}
            </button>
          </h3>
          <p title={o.location} className="stamp truncate text-muted-foreground">
            {[o.company, meta].filter(Boolean).join(" · ")}
          </p>
        </div>
        {stock.label && (
          <Badge variant="outline" className="hidden bg-background/60 sm:inline-flex">
            {stock.label}
          </Badge>
        )}
        {o.level && <span className="hidden sm:inline-flex">{level}</span>}
        <WorkModelBadge o={o} className="hidden bg-background/60 md:inline-flex" />
        {shownPay && <span className="stamp hidden shrink-0 font-medium tabular-nums md:inline">{o.pay ? "" : "Est. "}{shownPay}</span>}
        {due && <span className={cn("stamp hidden font-medium sm:inline", DEADLINE_TONE[due.tone])}>{due.label}</span>}
        {onStatus && (
          <Button
            variant="ghost"
            size="icon"
            aria-pressed={status === "saved"}
            aria-label={status === "saved" ? "Saved: tap to unsave" : "Save"}
            onClick={stop(() => onStatus(status === "saved" ? "new" : "saved"))}
          >
            {status === "saved" ? <BookmarkCheck /> : <Bookmark />}
          </Button>
        )}
        {o.url && (
          <Button asChild size="icon" onClick={(e: React.MouseEvent) => e.stopPropagation()}>
            <a href={o.url} target="_blank" rel="noopener noreferrer" aria-label={`Apply: ${o.company ? `${o.company}, ` : ""}${title}`}>
              <ArrowUpRight />
            </a>
          </Button>
        )}
      </article>
    );

  return (
    <article
      ref={ref}
      tabIndex={-1}
      aria-label={`${o.company ? `${o.company}: ` : ""}${title}`}
      aria-current={selected ? "true" : undefined}
      onClick={onOpen}
      className={cn(
        "flex cursor-pointer flex-col gap-2.5 rounded-xl border border-stock-line p-3.5 shadow-[0_2px_0_var(--stock-line)] outline-none sm:p-4",
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
          <Button asChild size="lg" className="hidden shrink-0 self-start sm:inline-flex" onClick={(e: React.MouseEvent) => e.stopPropagation()}>
            <a href={o.url} target="_blank" rel="noopener noreferrer" aria-label={`Apply: ${o.company ? `${o.company}, ` : ""}${title}`}>
              Apply
              <ArrowUpRight data-icon="inline-end" />
            </a>
          </Button>
        ) : (
          <span className="hidden shrink-0 self-start text-xs text-muted-foreground sm:inline">No link yet</span>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 border-t border-stock-line pt-2.5">
        {stock.label && (
          <Badge variant="outline" className="bg-background/60">
            {stock.label}
          </Badge>
        )}
        {level}
        <WorkModelBadge o={o} className="bg-background/60" />
        {shownPay && <span className="stamp font-medium tabular-nums">{o.pay ? "" : "Est. "}{shownPay}</span>}
        {due && <span className={cn("stamp font-medium", DEADLINE_TONE[due.tone])}>{due.label}</span>}
        {onStatus && (
        <div className="ml-auto flex items-center">
          <Button
            variant="ghost"
            size="icon"
            aria-pressed={status === "saved"}
            aria-label={status === "saved" ? "Saved: tap to unsave" : "Save"}
            onClick={stop(() => onStatus(status === "saved" ? "new" : "saved"))}
          >
            {status === "saved" ? <BookmarkCheck /> : <Bookmark />}
          </Button>
          <Button
            variant="ghost"
            size="icon"
            aria-label={status === "ignored" ? "Unhide" : "Hide"}
            onClick={stop(() => onStatus(status === "ignored" ? "new" : "ignored"))}
          >
            {status === "ignored" ? <Eye /> : <EyeOff />}
          </Button>
        </div>
        )}
      </div>
      {o.url && (
        <Button asChild size="lg" className="w-full sm:hidden" onClick={(e: React.MouseEvent) => e.stopPropagation()}>
          <a href={o.url} target="_blank" rel="noopener noreferrer" aria-label={`Apply: ${o.company ? `${o.company}, ` : ""}${title}`}>
            Apply
            <ArrowUpRight data-icon="inline-end" />
          </a>
        </Button>
      )}
    </article>
  );
});
