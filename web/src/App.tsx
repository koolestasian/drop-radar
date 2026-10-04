import { useQuery, useQueryClient } from "@tanstack/react-query";
import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { Activity, BellOff, CircleUser, KanbanSquare, List, LogOut, Moon, Sun, Settings as SettingsIcon, type LucideIcon } from "lucide-react";
import { cn } from "cn";
import { api, authHeaders, setUnauthorizedHandler, token, type Me, type Opportunity } from "./api/client";
import { openStream, type StreamStatus } from "./api/stream";
import { patchCachedOpportunity, useTheme, type Theme } from "./hooks";
import { Feed } from "./screens/Feed";
import { Login } from "./screens/Login";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuRadioGroup, DropdownMenuRadioItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";
import { Welcome } from "./components/Welcome";
import { ListSkeleton } from "./components/common";
import { HideFeedback } from "./components/HideFeedback";

// Screens you don't open first load on demand, so the feed's first paint ships less code.
const Board = lazy(() => import("./screens/Board").then((m) => ({ default: m.Board })));
const Settings = lazy(() => import("./screens/Settings").then((m) => ({ default: m.Settings })));
const Sources = lazy(() => import("./screens/Sources").then((m) => ({ default: m.Sources })));

const ROUTES: { id: string; label: string; icon: LucideIcon }[] = [
  { id: "jobs", label: "Jobs", icon: List },
  { id: "tracker", label: "Tracker", icon: KanbanSquare },
  { id: "sources", label: "Sources", icon: Activity },
  { id: "settings", label: "Settings", icon: SettingsIcon },
];
type Route = "jobs" | "tracker" | "sources" | "settings" | "login";
const GUEST_ROUTES: Route[] = ["jobs"]; // what a visitor who is not signed in can open
const JOBS = "#/jobs?scope=you";
const hrefOf = (id: string) => (id === "jobs" ? JOBS : `#/${id}`);

// "/settings" typed or bookmarked: the app routes on the hash, so move the path there
if (window.location.pathname !== "/" && !window.location.hash) window.history.replaceState(null, "", `/#${window.location.pathname}`);

// Old links: "#/feed" and an empty address are the For you list; "#/board" is the Tracker. A bare "#/jobs" stays as it is (it was All jobs).
function currentRoute(): Route {
  const id = window.location.hash.replace(/^#\/?/, "").split("?")[0];
  const known = id === "board" ? "tracker" : id;
  const route = (known === "login" ? "login" : ROUTES.find((r) => r.id === known)?.id ?? "jobs") as Route;
  if (route === "jobs" && id !== "jobs") window.history.replaceState(null, "", JOBS);
  return route;
}

const STATUS_DOT: Record<StreamStatus, { color: string; label: string }> = {
  live: { color: "bg-live", label: "Live" },
  connecting: { color: "bg-muted-foreground", label: "Connecting" },
  reconnecting: { color: "bg-destructive", label: "Reconnecting" },
};

export function App() {
  const qc = useQueryClient();
  const [theme, setTheme, dark] = useTheme();
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
    if (signedIn && route === "login") window.location.hash = JOBS;
  }, [signedIn, route]);

  const me = useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/api/me"), refetchInterval: 60_000 });

  const guest = !signedIn;
  if (guest && !GUEST_ROUTES.includes(route))
    return (
      <Login
        gated={route !== "login"}
        onGuest={() => {
          window.location.hash = JOBS;
        }}
        onSignedIn={(m) => {
          qc.clear();
          qc.setQueryData(["me"], m);
          setSignedIn(true);
          window.location.hash = JOBS;
        }}
      />
    );
  const routes = guest ? ROUTES.filter((r) => GUEST_ROUTES.includes(r.id as Route)) : ROUTES;

  const dot = guest ? { color: "bg-muted-foreground", label: "Guest view" } : STATUS_DOT[stream];
  const badge = (r: { id: string }) =>
    r.id === "jobs" && incoming.length > 0 && route !== "jobs" ? (
      <span className="stamp rounded-full bg-primary px-1.5 text-primary-foreground">{incoming.length}</span>
    ) : null;
  const link = "relative flex items-center rounded-full font-medium whitespace-nowrap";

  return (
    <div className="min-h-dvh pb-24 sm:pb-8">
      {!guest && <HideFeedback key={me.data?.user} />}
      <header className="sticky top-0 z-20 border-b border-border bg-background">
        <div className="mx-auto flex h-14 max-w-6xl items-center gap-2 px-4 sm:gap-4">
          <a href={JOBS} className="flex items-center gap-2 text-lg font-bold tracking-tight">
            <img src="/icon.svg" alt="" className="size-7" />
            Drop Radar
          </a>
          <span className="stamp flex items-center gap-1.5 text-muted-foreground" role="status" aria-label={dot.label} title="Live updates">
            <span className={cn("size-2 rounded-full", dot.color, stream === "live" && "animate-pulse")} aria-hidden />
            <span className="hidden sm:inline">{dot.label}</span>
          </span>
          <nav aria-label="Main" className="ml-auto hidden gap-1 sm:flex">
            {routes.map((r) => (
              <a
                key={r.id}
                href={hrefOf(r.id)}
                aria-label={r.label}
                title={r.label}
                aria-current={route === r.id ? "page" : undefined}
                className={cn(link, "h-10 gap-1.5 px-3.5 text-sm", route === r.id ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground")}
              >
                <r.icon aria-hidden className="size-4" />
                <span className="hidden lg:inline">{r.label}</span>
                {badge(r)}
              </a>
            ))}
          </nav>
          <div className="ml-auto flex shrink-0 items-center gap-1 sm:ml-0">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon-lg" aria-label={`Appearance: ${theme[0].toUpperCase()}${theme.slice(1)}`} title="Change appearance">
                  {dark ? <Moon aria-hidden /> : <Sun aria-hidden />}
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuLabel>Appearance</DropdownMenuLabel>
                <DropdownMenuRadioGroup value={theme} onValueChange={(value) => setTheme(value as Theme)}>
                  <DropdownMenuRadioItem value="light" className="min-h-11">Light</DropdownMenuRadioItem>
                  <DropdownMenuRadioItem value="dark" className="min-h-11">Dark</DropdownMenuRadioItem>
                  <DropdownMenuRadioItem value="system" className="min-h-11">System</DropdownMenuRadioItem>
                </DropdownMenuRadioGroup>
              </DropdownMenuContent>
            </DropdownMenu>
          {guest ? (
            <Button asChild className="h-10 px-4 pointer-coarse:h-11">
              <a href="#/login">Sign in</a>
            </Button>
          ) : (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" className="h-10 gap-1.5 px-2.5 pointer-coarse:h-11" aria-label={`Account${me.data ? `: ${me.data.username ?? me.data.user}` : ""}`}>
                <CircleUser aria-hidden className="size-5" />
                <span className="hidden text-sm lg:inline">{me.data?.username ?? me.data?.user}</span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="min-w-48">
              {me.data && <DropdownMenuLabel className="font-normal text-muted-foreground">Signed in as {me.data.username ?? me.data.user}</DropdownMenuLabel>}
              <DropdownMenuItem asChild>
                <a href="#/settings"><SettingsIcon aria-hidden /> Settings</a>
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                variant="destructive"
                onSelect={() => {
                  // end the server session too (a configured token has none); then forget it here
                  void fetch("/api/auth/logout", { method: "POST", headers: authHeaders() }).catch(() => {});
                  signOut();
                }}
              >
                <LogOut aria-hidden /> Sign out
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          )}
          </div>
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
        {route === "jobs" && <Feed guest={guest} incoming={incoming} clearIncoming={() => setIncoming([])} />}
        <Suspense fallback={<ListSkeleton rows={3} />}>
          {route === "tracker" && <Board />}
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
            href={hrefOf(r.id)}
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
