import type { ActionStatus, Opportunity } from "./api/client";

export const BOARD_COLUMNS: { status: ActionStatus; label: string }[] = [
  { status: "saved", label: "Saved" },
  { status: "applied", label: "Applied" },
  { status: "interview", label: "Interview" },
  { status: "offer", label: "Offer" },
  { status: "rejected", label: "Rejected" },
];

export const STATUS_LABEL: Record<string, string> = {
  new: "New",
  saved: "Saved",
  applied: "Applied",
  interview: "Interview",
  offer: "Offer",
  rejected: "Rejected",
  ignored: "Ignored",
  actioned: "Actioned",
};

/** "ats.greenhouse.stripe" -> "Greenhouse"; "instagram.zero2sudo" -> "@zero2sudo". */
export function sourceLabel(source: string): string {
  const [kind, sub, ...rest] = source.split(".");
  if (kind === "instagram") return `@${[sub, ...rest].join(".")}`;
  if (kind === "github_repo") return sub?.includes("New-Grad") || rest.join(".").includes("New-Grad") ? "Simplify new grad" : "Simplify list";
  if (kind === "ats" && sub) return sub === "smartrecruiters" ? "SmartRecruiters" : sub[0].toUpperCase() + sub.slice(1);
  return source;
}

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

export function ago(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "";
  const ms = now - new Date(iso).getTime();
  if (Number.isNaN(ms)) return "";
  if (ms < MINUTE) return "just now";
  if (ms < HOUR) return `${Math.floor(ms / MINUTE)}m ago`;
  if (ms < DAY) return `${Math.floor(ms / HOUR)}h ago`;
  return `${Math.floor(ms / DAY)}d ago`;
}

export function duration(ms: number): string {
  if (ms < MINUTE) return `${Math.max(0, Math.round(ms / 1000))}s`;
  if (ms < HOUR) return `${Math.round(ms / MINUTE)}m`;
  if (ms < DAY) return `${Math.round(ms / HOUR)}h`;
  return `${Math.round(ms / DAY)}d`;
}

/** How long after the source published it we saw it -- the drop latency the radar exists to cut. */
export function seenAfterPosted(o: Opportunity): string | null {
  if (!o.published_at) return null;
  const ms = new Date(o.first_seen).getTime() - new Date(o.published_at).getTime();
  return Number.isNaN(ms) || ms < 0 ? null : `seen ${duration(ms)} after posted`;
}

export type Deadline = { label: string; tone: "urgent" | "soon" | "normal" | "past" };

export function deadline(value: string, now = new Date()): Deadline | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value ?? "");
  if (!match) return value ? { label: `due ${value}`, tone: "normal" } : null;
  const due = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const days = Math.round((due.getTime() - today.getTime()) / DAY);
  if (days < 0) return { label: "deadline passed", tone: "past" };
  if (days === 0) return { label: "due today", tone: "urgent" };
  if (days <= 3) return { label: `due in ${days}d`, tone: "urgent" };
  if (days <= 14) return { label: `due in ${days}d`, tone: "soon" };
  return { label: `due ${due.toLocaleDateString(undefined, { month: "short", day: "numeric" })}`, tone: "normal" };
}
