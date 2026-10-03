import { useState } from "react";
import { Building2, CircleAlert, House, Split } from "lucide-react";
import { workModel } from "../workModel";
import type { Opportunity } from "../api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

export function ListSkeleton({ rows = 5, label = "Loading" }: { rows?: number; label?: string }) {
  return (
    <div role="status" aria-label={label} className="flex flex-col gap-2.5">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-28 rounded-xl" />
      ))}
    </div>
  );
}

export function ErrorNote({ error, retry }: { error: unknown; retry?: () => void }) {
  const message = error instanceof Error ? error.message : String(error);
  return (
    <div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive">
      <span className="flex items-center gap-2">
        <CircleAlert className="size-4 shrink-0" aria-hidden />
        {message}
      </span>
      {retry && (
        <Button variant="outline" size="sm" onClick={retry}>
          Try again
        </Button>
      )}
    </div>
  );
}

const MONOGRAM = ["bg-zinc-800", "bg-sky-800", "bg-emerald-800", "bg-amber-800", "bg-rose-800", "bg-violet-800", "bg-teal-800"];

/** The company's icon (by its looked-up domain), or a lettered tile when there is none or it fails to load.
 * Google answers an unknown icon with a 16px globe (status 404, which browsers still draw), so tiny counts as none. */
export function CompanyLogo({ name, domain, className = "size-10" }: { name: string; domain?: string | null; className?: string }) {
  const [failed, setFailed] = useState(false);
  if (domain && !failed)
    return (
      <img
        src={`https://www.google.com/s2/favicons?domain=${encodeURIComponent(domain)}&sz=128`}
        alt=""
        loading="lazy"
        onError={() => setFailed(true)}
        onLoad={(e) => e.currentTarget.naturalWidth <= 16 && setFailed(true)}
        className={`${className} shrink-0 rounded-lg border border-stock-line bg-white object-contain p-1`}
      />
    );
  let h = 0;
  for (const c of name) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return (
    <span aria-hidden className={`${className} grid shrink-0 place-items-center rounded-lg text-base font-bold text-white ${MONOGRAM[h % MONOGRAM.length]}`}>
      {(name.trim()[0] ?? "?").toUpperCase()}
    </span>
  );
}

const WORK_ICON = { Remote: House, Hybrid: Split, "On site": Building2 };

/** Remote / Hybrid / On site when the posting says so (most do not, so most cards show nothing). */
export function WorkModelBadge({ o, className }: { o: Pick<Opportunity, "location" | "title"> & { location_raw?: string }; className?: string }) {
  const m = workModel(o);
  if (!m) return null;
  const Icon = WORK_ICON[m];
  return (
    <Badge variant="outline" className={className}>
      <Icon data-icon="inline-start" aria-hidden />
      {m}
    </Badge>
  );
}
