import { useState } from "react";
import { ArrowUpRight, EyeOff, Eye, Share2 } from "lucide-react";
import type { ActionStatus, Opportunity } from "../api/client";
import { ago, deadline, posted, seenAfterPosted, sourceLabel } from "../format";
import { stockOf } from "../stock";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { CompanyLogo, WorkModelBadge } from "./common";
import { shareLink } from "./RoleCard";

const TRACKED: { status: ActionStatus; label: string }[] = [
  { status: "saved", label: "Saved" },
  { status: "applied", label: "Applied" },
  { status: "interview", label: "Interview" },
  { status: "offer", label: "Offer" },
  { status: "rejected", label: "Rejected" },
];

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[5.5rem_1fr] gap-3 py-2 text-sm">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 [overflow-wrap:anywhere]">{children}</dd>
    </div>
  );
}

/** Everything the radar knows about one posting, plus its status and your notes. Used in the desktop pane and the phone sheet. */
export function Detail({ o, onStatus, onNotes }: { o: Opportunity; onStatus?: (status: ActionStatus) => void; onNotes?: (notes: string) => void }) {
  const status = o.action?.status ?? "new";
  const stock = stockOf(o);
  const due = deadline(o.deadline);
  const [notes, setNotes] = useState(o.action?.notes ?? "");
  const [shareStatus, setShareStatus] = useState("");
  const places = o.location.split("; ").filter(Boolean); // one line per country: "A, B - United States"
  const after = seenAfterPosted(o);

  return (
    <div className="flex flex-col gap-5">
      <div className="flex gap-3">
        <CompanyLogo name={o.company || "?"} domain={o.company_domain} className="size-12" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-muted-foreground">{o.company || "Unknown company"}</p>
          <h2 className="text-xl leading-snug font-semibold [overflow-wrap:anywhere]">{o.title || "Untitled opportunity"}</h2>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {stock.label && (
              <Badge variant="outline" className="bg-background/60">
                {stock.label}
              </Badge>
            )}
            <WorkModelBadge o={o} className="bg-background/60" />
          </div>
        </div>
      </div>

      {o.url ? (
        <Button asChild size="lg" className="w-full">
          <a href={o.url} target="_blank" rel="noopener noreferrer">
            Apply on the company site
            <ArrowUpRight data-icon="inline-end" />
          </a>
        </Button>
      ) : (
        <p className="text-sm text-muted-foreground">No apply link yet.</p>
      )}

      {!onStatus || !onNotes ? (
        <p className="rounded-xl border border-border bg-muted px-3.5 py-3 text-sm">
          <a href="#/login" className="font-medium underline">Sign in</a> to save this role, keep notes and get alerts for roles like it.
        </p>
      ) : (
      <section aria-labelledby="your-status" className="flex flex-col gap-2">
        <h3 id="your-status" className="text-sm font-semibold">
          Your status
        </h3>
        <ToggleGroup
          type="single"
          variant="outline"
          value={TRACKED.some((t) => t.status === status) ? status : ""}
          onValueChange={(v) => onStatus?.((v || "new") as ActionStatus)}
          className="grid w-full grid-cols-3 gap-1.5"
        >
          {TRACKED.map((t) => (
            <ToggleGroupItem key={t.status} value={t.status} className="w-full pointer-coarse:h-11">
              {t.label}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
        <label htmlFor="notes" className="mt-1 text-sm font-semibold">
          Notes
        </label>
        <Textarea
          id="notes"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          onBlur={() => notes !== (o.action?.notes ?? "") && onNotes?.(notes)}
          placeholder="Referral, recruiter, what to prep. Saved when you leave the box."
          className="min-h-24"
        />
      </section>
      )}

      <section aria-labelledby="why" className="flex flex-col gap-2">
        <h3 id="why" className="text-sm font-semibold">
          Why it matched
        </h3>
        {o.match.reasons.length > 0 ? (
          <ul className="flex flex-wrap gap-1.5">
            {o.match.reasons.map((r) => (
              <li key={r}>
                <Badge variant="secondary">{r}</Badge>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">Added without a profile match (for example, from All jobs).</p>
        )}
      </section>

      <dl className="divide-y divide-border border-y border-border">
        <Fact label="Where">{places.length > 1 ? places.map((p) => <span key={p} className="block">{p}</span>) : o.location || "Location not listed"}</Fact>
        <Fact label="Posted">{posted(o.published_at)?.replace(/^posted /, "") ?? "Unknown"}</Fact>
        <Fact label="Found">
          {ago(o.first_seen)}
          {after && <span className="text-muted-foreground"> ({after})</span>}
        </Fact>
        {due && <Fact label="Deadline">{due.label}</Fact>}
        {o.pay && <Fact label="Pay">{o.pay}</Fact>}
        {o.season && <Fact label="Season">{o.season}</Fact>}
        <Fact label="Seen on">{o.sources.map(sourceLabel).join(", ")}</Fact>
      </dl>

      <div className="flex flex-wrap items-center gap-2">
        {o.url && (
          <Button variant="outline" onClick={() => void shareLink(o).then(setShareStatus)}>
            <Share2 data-icon="inline-start" />
            Share
          </Button>
        )}
        {onStatus && (
          <Button variant="outline" onClick={() => onStatus(status === "ignored" ? "new" : "ignored")}>
            {status === "ignored" ? <Eye data-icon="inline-start" /> : <EyeOff data-icon="inline-start" />}
            {status === "ignored" ? "Unignore" : "Ignore"}
          </Button>
        )}
        {shareStatus && (
          <span role="status" className="text-xs text-muted-foreground">
            {shareStatus}
          </span>
        )}
      </div>
    </div>
  );
}
