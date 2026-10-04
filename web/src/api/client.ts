import type { components } from "./schema";

type S = components["schemas"];
export type Opportunity = S["Opportunity"];
export type Page = S["Page"];
export type Me = S["Me"];
export type Summary = S["Summary"];
export type Metrics = S["Metrics"];
export type SourceHealth = S["SourceHealth"];
export type ProfileConfig = S["ProfileConfig"];
export type WatchlistConfig = S["WatchlistConfig"];
export type CompanyConfig = S["CompanyConfig"];
export type ActionStatus = NonNullable<S["ActionPatch"]["status"]>;

const TOKEN_KEY = "radar.token";

// localStorage can throw (private mode, blocked storage); the app still works for the session.
let memoryToken: string | null = null;
export const token = {
  get(): string | null {
    try {
      return localStorage.getItem(TOKEN_KEY) ?? memoryToken;
    } catch {
      return memoryToken;
    }
  },
  set(value: string) {
    memoryToken = value;
    try {
      localStorage.setItem(TOKEN_KEY, value);
    } catch {
      /* session-only */
    }
  },
  clear() {
    memoryToken = null;
    try {
      localStorage.removeItem(TOKEN_KEY);
    } catch {
      /* nothing stored */
    }
  },
};

// One-tap sign-in: opening a link ending in #token=<secret> signs this device in. The fragment
// never reaches the server, and it is wiped from the address bar straight away.
const linked = new URLSearchParams(location.hash.slice(1)).get("token");
if (linked) {
  token.set(linked);
  history.replaceState(null, "", location.pathname + location.search);
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

let onUnauthorized = () => {};
export function setUnauthorizedHandler(handler: () => void) {
  onUnauthorized = handler;
}
export function signalUnauthorized() {
  onUnauthorized();
}

export function authHeaders(): Record<string, string> {
  const t = token.get(); // no token: the server serves the read-only guest view
  return t ? { Authorization: `Bearer ${t}` } : {};
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...authHeaders(), ...init.headers },
  });
  if (res.status === 401) {
    signalUnauthorized();
    throw new ApiError(401, "Your token was not accepted. Sign in again.");
  }
  if (!res.ok) {
    let detail = res.statusText || `HTTP ${res.status}`;
    try {
      const body = await res.json();
      detail =
        typeof body.detail === "string"
          ? body.detail
          : (body.detail ?? []).map((d: { loc?: string[]; msg: string }) => `${(d.loc ?? []).slice(1).join(".")}: ${d.msg}`).join("; ");
    } catch {
      /* keep the status text */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export function query(params: Record<string, string | number | boolean | undefined | null>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
  const s = q.toString();
  return s ? `?${s}` : "";
}

export function setStatus(id: string, patch: { status?: ActionStatus; notes?: string }) {
  return api<Opportunity>(`/api/opportunities/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}
