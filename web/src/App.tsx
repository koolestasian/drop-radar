import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";
import { api, setUnauthorizedHandler, token, type Me, type Opportunity } from "./api/client";
import { openStream, type StreamStatus } from "./api/stream";
import { patchCachedOpportunity } from "./hooks";
import { Board } from "./screens/Board";
import { Feed } from "./screens/Feed";
import { Login } from "./screens/Login";
import { Settings } from "./screens/Settings";
import { Sources } from "./screens/Sources";

const ROUTES = [
  { id: "feed", label: "Feed", icon: "◉" },
  { id: "jobs", label: "All jobs", icon: "☰" },
  { id: "board", label: "Board", icon: "▦" },
  { id: "sources", label: "Sources", icon: "≋" },
  { id: "settings", label: "Settings", icon: "⚙" },
] as const;
type Route = (typeof ROUTES)[number]["id"];

function currentRoute(): Route {
  const id = window.location.hash.replace(/^#\/?/, "");
  return (ROUTES.find((r) => r.id === id)?.id ?? "feed") as Route;
}

const STATUS_DOT: Record<StreamStatus, { color: string; label: string }> = {
  live: { color: "bg-emerald-500", label: "Live" },
  connecting: { color: "bg-zinc-400", label: "Connecting" },
  reconnecting: { color: "bg-amber-500", label: "Reconnecting" },
};

export function App() {
  const qc = useQueryClient();
  const [signedIn, setSignedIn] = useState(() => Boolean(token.get()));
  const [route, setRoute] = useState<Route>(currentRoute);
  const [stream, setStream] = useState<StreamStatus>("connecting");
  const [incoming, setIncoming] = useState<Opportunity[]>([]);

  const signOut = useCallback(() => {
    token.clear();
    qc.clear();
    setIncoming([]);
    setSignedIn(false);
  }, [qc]);

  useEffect(() => setUnauthorizedHandler(signOut), [signOut]);
  useEffect(() => {
    const onHash = () => setRoute(currentRoute());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    if (!signedIn) return;
    return openStream((event, data) => {
      const o = data as Opportunity;
      if (event === "opportunity") setIncoming((list) => (list.some((x) => x.id === o.id) ? list : [o, ...list]));
      if (event === "action") {
        patchCachedOpportunity(qc, o.id, () => o);
        qc.invalidateQueries({ queryKey: ["opportunities", "board"] });
      }
    }, (status) => {
      setStream(status);
      if (status === "live") qc.invalidateQueries({ queryKey: ["opportunities"] });
    });
  }, [signedIn, qc]);

  const me = useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/api/me"), enabled: signedIn, refetchInterval: 60_000 });

  if (!signedIn)
    return (
      <Login
        onSignedIn={(m) => {
          qc.setQueryData(["me"], m);
          setSignedIn(true);
        }}
      />
    );

  const dot = STATUS_DOT[stream];
  const nav = (className: string) => (
    <nav aria-label="Main" className={className}>
      {ROUTES.map((r) => (
        <a
          key={r.id}
          href={`#/${r.id}`}
          aria-current={route === r.id ? "page" : undefined}
          className={`flex flex-1 flex-col items-center gap-0.5 rounded-full px-3 py-1.5 text-xs font-medium whitespace-nowrap sm:flex-row sm:gap-1.5 sm:text-sm ${
            route === r.id
              ? "text-zinc-950 sm:bg-zinc-950 sm:text-white dark:text-white sm:dark:bg-white sm:dark:text-zinc-950"
              : "text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
          }`}
        >
          <span aria-hidden className="text-base sm:text-sm">
            {r.icon}
          </span>
          {r.label}
          {r.id === "feed" && incoming.length > 0 && route !== "feed" && (
            <span className="rounded-full bg-zinc-950 px-1.5 text-[10px] text-white">{incoming.length}</span>
          )}
        </a>
      ))}
    </nav>
  );

  return (
    <div className="min-h-dvh pb-20 sm:pb-8">
      <header className="sticky top-0 z-20 border-b border-zinc-200 bg-white/85 backdrop-blur dark:border-zinc-800 dark:bg-zinc-950/85">
        <div className="mx-auto flex h-14 max-w-6xl items-center gap-4 px-4">
          <a href="#/feed" className="flex items-center gap-2 text-lg font-black tracking-tight">
            <img src="/icon.svg" alt="" className="size-7" />
            Drop Radar
          </a>
          <span className="flex items-center gap-1.5 text-xs text-zinc-500" role="status" title="Live updates">
            <span className={`size-2 rounded-full ${dot.color} ${stream === "live" ? "animate-pulse" : ""}`} aria-hidden />
            {dot.label}
          </span>
          {nav("ml-auto hidden gap-1 sm:flex")}
          <span className="hidden text-sm text-zinc-500 lg:inline">{me.data?.user}</span>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6 sm:py-8">
        {me.data?.alerts_enabled === false && route !== "settings" && (
          <p role="status" className="mx-auto mb-5 max-w-3xl rounded-xl border border-amber-200 bg-amber-50 px-4 py-2.5 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/60 dark:text-amber-200">
            Phone alerts are off. <a href="#/settings" className="underline">Check notification setup</a>; live updates reach this page while it is open.
          </p>
        )}
        {route === "feed" && <Feed incoming={incoming} clearIncoming={() => setIncoming([])} />}
        {route === "jobs" && <Feed key="jobs" screen="jobs" />}
        {route === "board" && <Board />}
        {route === "sources" && <Sources />}
        {route === "settings" && <Settings onSignOut={signOut} />}
      </main>
      {nav(
        "fixed inset-x-0 bottom-0 z-20 flex border-t border-zinc-200 bg-white/95 px-2 pt-1 pb-[max(0.25rem,env(safe-area-inset-bottom))] backdrop-blur sm:hidden dark:border-zinc-800 dark:bg-zinc-950/95",
      )}
    </div>
  );
}
