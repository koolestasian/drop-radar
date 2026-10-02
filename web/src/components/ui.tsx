import { useState, type ButtonHTMLAttributes, type ReactNode } from "react";

type Variant = "primary" | "ghost" | "danger" | "quiet";

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-zinc-950 text-white hover:bg-zinc-800 dark:bg-white dark:text-zinc-950 dark:hover:bg-zinc-200 disabled:opacity-50",
  ghost:
    "border border-zinc-300 bg-white text-zinc-800 hover:bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:hover:bg-zinc-800",
  danger: "border border-red-300 text-red-700 hover:bg-red-50 dark:border-red-800 dark:text-red-300 dark:hover:bg-red-950",
  quiet: "text-zinc-600 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-800",
};

export function Button({
  variant = "ghost",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      type="button"
      className={`inline-flex min-h-9 items-center justify-center gap-1.5 rounded-lg px-3 text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-900 dark:focus-visible:outline-zinc-100 disabled:cursor-not-allowed ${VARIANTS[variant]} ${className}`}
      {...props}
    />
  );
}

const TONES = {
  neutral: "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300",
  green: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  amber: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  red: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
};

export function Badge({ tone = "neutral", children, title }: { tone?: keyof typeof TONES; children: ReactNode; title?: string }) {
  return (
    <span title={title} className={`inline-flex shrink-0 items-center rounded-md px-1.5 py-0.5 text-xs font-medium whitespace-nowrap ${TONES[tone]}`}>
      {children}
    </span>
  );
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center justify-center gap-2 py-12 text-sm text-zinc-500">
      <span className="size-4 animate-spin rounded-full border-2 border-zinc-300 border-t-zinc-900 dark:border-t-white" aria-hidden />
      {label}…
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-zinc-300 px-6 py-12 text-center dark:border-zinc-700">
      <p className="font-medium text-zinc-800 dark:text-zinc-100">{title}</p>
      {children && <div className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">{children}</div>}
    </div>
  );
}

export function ErrorNote({ error, retry }: { error: unknown; retry?: () => void }) {
  const message = error instanceof Error ? error.message : String(error);
  return (
    <div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/50 dark:text-red-200">
      <span>{message}</span>
      {retry && (
        <Button variant="danger" onClick={retry}>
          Try again
        </Button>
      )}
    </div>
  );
}

const MONOGRAM = ["bg-zinc-900", "bg-sky-700", "bg-emerald-700", "bg-amber-700", "bg-rose-700", "bg-violet-700", "bg-teal-700"];

/** The company's icon (by its looked-up domain), or a lettered tile when there is none or it fails to load. */
export function CompanyLogo({ name, domain }: { name: string; domain?: string | null }) {
  const [failed, setFailed] = useState(false);
  if (domain && !failed)
    return (
      <img
        src={`https://www.google.com/s2/favicons?domain=${encodeURIComponent(domain)}&sz=128`}
        alt=""
        loading="lazy"
        onError={() => setFailed(true)}
        className="size-8 shrink-0 rounded-lg border border-zinc-200 bg-white object-contain p-0.5 dark:border-zinc-700"
      />
    );
  let h = 0;
  for (const c of name) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return (
    <span aria-hidden className={`grid size-8 shrink-0 place-items-center rounded-lg text-sm font-bold text-white ${MONOGRAM[h % MONOGRAM.length]}`}>
      {(name.trim()[0] ?? "?").toUpperCase()}
    </span>
  );
}
