import { useQuery, useQueryClient } from "@tanstack/react-query";
import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { Activity, BellOff, CircleUser, Inbox, KanbanSquare, List, LogOut, Settings as SettingsIcon, type LucideIcon } from "lucide-react";
import { cn } from "cn";
import { api, setUnauthorizedHandler, token, type Me, type Opportunity } from "./api/client";
import { openStream, type StreamStatus } from "./api/stream";
import { patchCachedOpportunity } from "./hooks";
import { Feed } from "./screens/Feed";
import { Login } from "./screens/Login";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";
import { Welcome } from "./components/Welcome";
import { ListSkeleton } from "./components/common";

// Screens you don't open first load on demand, so the feed's first paint ships less code.
const Board = lazy(() => import("./screens/Board").then((m) => ({ default: m.Board })));
const Settings = lazy(() => import("./screens/Settings").then((m) => ({ default: m.Settings })));
const Sources = lazy(() => import("./screens/Sources").then((m) => ({ default: m.Sources })));

const ROUTES: { id: string; label: string; icon: LucideIcon }[] = [
  { id: "feed", label: "Feed", icon: Inbox },
  { id: "jobs", label: "All jobs", icon: List },
  { id: "board", label: "Board", icon: KanbanSquare },
  { id: "sources", label: "Sources", icon: Activity },
  { id: "settings", label: "Settings", icon: SettingsIcon },
];
type Route = "feed" | "jobs" | "board" | "sources" | "settings" | "login";
const GUEST_ROUTES: Route[] = ["feed", "jobs"]; // what a visitor who is not signed in can open

function currentRoute(): Route {
  const id = window.location.hash.replace(/^#\/?/, "");
  return (id === "login" ? "login" : ROUTES.find((r) => r.id === id)?.id ?? "feed") as Route;
}

const STATUS_DOT: Record<StreamStatus, { color: string; label: string }> = {
  live: { color: "bg-live", label: "Live" },
  connecting: { color: "bg-muted-foreground", label: "Connecting" },
  reconnecting: { color: "bg-destructive", label: "Reconnecting" },
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

  useEffect(() => {
    if (signedIn && route === "login") window.location.hash = "#/feed";
  }, [signedIn, route]);

  const me = useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/api/me"), refetchInterval: 60_000 });

  const guest = !signedIn;
  if (guest && !GUEST_ROUTES.includes(route))
    return (
      <Login
        gated={route !== "login"}
        onGuest={() => {
          window.location.hash = "#/feed";
        }}
        onSignedIn={(m) => {
          qc.clear();
          qc.setQueryData(["me"], m);
          setSignedIn(true);
          window.location.hash = "#/feed";
        }}
      />
    );
  const routes = guest ? ROUTES.filter((r) => GUEST_ROUTES.includes(r.id as Route)) : ROUTES;

  const dot = guest ? { color: "bg-muted-foreground", label: "Guest view" } : STATUS_DOT[stream];
  const badge = (r: { id: string }) =>
    r.id === "feed" && incoming.length > 0 && route !== "feed" ? (
      <span className="stamp rounded-full bg-primary px-1.5 text-primary-foreground">{incoming.length}</span>
    ) : null;
  const link = "relative flex items-center rounded-full font-medium whitespace-nowrap";

  return (
    <div className="min-h-dvh pb-24 sm:pb-8">
      <header className="sticky top-0 z-20 border-b border-border bg-background">
        <div className="mx-auto flex h-14 max-w-6xl items-center gap-4 px-4">
          <a href="#/feed" className="flex items-center gap-2 text-lg font-bold tracking-tight">
            <img src="/icon.svg" alt="" className="size-7" />
            Drop Radar
          </a>
          <span className="stamp flex items-center gap-1.5 text-muted-foreground" role="status" title="Live updates">
            <span className={cn("size-2 rounded-full", dot.color, stream === "live" && "animate-pulse")} aria-hidden />
            {dot.label}
          </span>
          <nav aria-label="Main" className="ml-auto hidden gap-1 sm:flex">
            {routes.map((r) => (
              <a
                key={r.id}
                href={`#/${r.id}`}
                aria-current={route === r.id ? "page" : undefined}
                className={cn(link, "h-10 gap-1.5 px-3.5 text-sm", route === r.id ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground")}
              >
                <r.icon aria-hidden className="size-4" />
                {r.label}
                {badge(r)}
              </a>
            ))}
          </nav>
          {guest ? (
            <Button asChild className="h-10 px-4 max-sm:ml-auto pointer-coarse:h-11">
              <a href="#/login">Sign in</a>
            </Button>
          ) : (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" className="h-10 gap-1.5 px-2.5 max-sm:ml-auto pointer-coarse:h-11" aria-label={`Account${me.data ? `: ${me.data.user}` : ""}`}>
                <CircleUser aria-hidden className="size-5" />
                <span className="hidden text-sm lg:inline">{me.data?.user}</span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="min-w-48">
              {me.data && <DropdownMenuLabel className="font-normal text-muted-foreground">Signed in as {me.data.user}</DropdownMenuLabel>}
              <DropdownMenuItem asChild>
                <a href="#/settings"><SettingsIcon aria-hidden /> Settings</a>
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem variant="destructive" onSelect={signOut}>
                <LogOut aria-hidden /> Sign out
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          )}
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6 sm:py-8">
        {guest && (
          <p role="status" className="mb-5 rounded-xl border border-border bg-muted px-4 py-3 text-sm">
            You are browsing as a guest. <a href="#/login" className="font-medium underline">Sign in</a> for your own feed, saved roles and phone alerts.
          </p>
        )}
        {!guest && me.data?.alerts_enabled === false && route !== "settings" && (
          <p role="status" className="mb-5 flex items-start gap-2 rounded-xl border border-border bg-muted px-4 py-3 text-sm">
            <BellOff aria-hidden className="mt-0.5 size-4 shrink-0" />
            <span>
              Phone alerts are off. <a href="#/settings" className="font-medium underline">Check notification setup</a>; live updates reach this page while it is open.
            </span>
          </p>
        )}
        {me.data && <Welcome key={me.data.user} user={me.data.user} sources={me.data.sources} guest={guest} />}
        {route === "feed" && <Feed guest={guest} incoming={incoming} clearIncoming={() => setIncoming([])} />}
        {route === "jobs" && <Feed key="jobs" guest={guest} screen="jobs" />}
        <Suspense fallback={<ListSkeleton rows={3} />}>
          {route === "board" && <Board />}
          {route === "sources" && <Sources />}
          {route === "settings" && <Settings />}
        </Suspense>
      </main>
      <nav
        aria-label="Main"
        className="fixed inset-x-0 bottom-0 z-20 flex border-t border-border bg-background/95 px-1 pt-1 pb-[max(0.25rem,env(safe-area-inset-bottom))] backdrop-blur sm:hidden"
      >
        {routes.map((r) => (
          <a
            key={r.id}
            href={`#/${r.id}`}
            aria-current={route === r.id ? "page" : undefined}
            className={cn(link, "min-h-14 flex-1 flex-col justify-center gap-0.5 text-[11px]", route === r.id ? "text-foreground" : "text-muted-foreground")}
          >
            <span className={cn("relative grid h-7 w-12 place-items-center rounded-full", route === r.id && "bg-stock-fresh")}>
              <r.icon aria-hidden className="size-5" />
              {badge(r) && <span className="absolute -top-1 -right-0.5">{badge(r)}</span>}
            </span>
            {r.label}
          </a>
        ))}
      </nav>
    </div>
  );
}
