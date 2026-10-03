import { useState, type FormEvent } from "react";
import { ApiError, token, type Me } from "../api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type Mode = "signin" | "signup" | "token";
type AuthResult = { token: string; me: Me };

async function problemOf(res: Response, fallback: string): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body.detail === "string") return body.detail;
  } catch {
    /* keep the fallback */
  }
  return fallback;
}

export function Login({ onSignedIn, onGuest, gated = false }: { onSignedIn: (me: Me) => void; onGuest: () => void; gated?: boolean }) {
  const [mode, setMode] = useState<Mode>("signin");
  const [username, setUsername] = useState("");
  const [value, setValue] = useState(""); // the password, or an access token in token mode
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === "token") {
        const res = await fetch("/api/me", { headers: { Authorization: `Bearer ${value.trim()}` } });
        if (res.status === 401) throw new ApiError(401, "That token wasn't accepted.");
        if (!res.ok) throw new ApiError(res.status, `The server answered ${res.status}. Is it running?`);
        token.set(value.trim());
        onSignedIn((await res.json()) as Me);
        return;
      }
      const res = await fetch(mode === "signup" ? "/api/auth/signup" : "/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: username.trim(), password: value }),
      });
      if (!res.ok) throw new ApiError(res.status, await problemOf(res, `The server answered ${res.status}. Is it running?`));
      const result = (await res.json()) as AuthResult;
      token.set(result.token);
      onSignedIn(result.me);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Can't reach the server.");
    } finally {
      setBusy(false);
    }
  }

  const pick = (m: Mode) => {
    setMode(m);
    setError(null);
    setValue("");
  };
  const tab = (m: Mode, label: string) => (
    <button
      type="button"
      role="tab"
      aria-selected={mode === m}
      onClick={() => pick(m)}
      className={`h-10 flex-1 rounded-full text-sm font-medium pointer-coarse:h-11 ${mode === m ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted"}`}
    >
      {label}
    </button>
  );

  return (
    <main className="mx-auto flex min-h-dvh max-w-sm flex-col justify-center gap-6 px-4 py-10">
      <div className="flex items-center gap-3">
        <img src="/icon.svg" alt="" className="size-12" />
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Drop Radar</h1>
          <p className="text-sm text-muted-foreground">New roles, the moment they go live.</p>
        </div>
      </div>
      {gated && <p className="text-sm font-medium">That part of Drop Radar is for signed-in users: your own feed, saved roles and alerts.</p>}
      {mode !== "token" && (
        <div role="tablist" aria-label="Account" className="flex rounded-full border border-border bg-card p-1">
          {tab("signin", "Sign in")}
          {tab("signup", "Create account")}
        </div>
      )}
      <form onSubmit={submit} className="flex flex-col gap-3 rounded-2xl border border-border bg-card p-5">
        {mode === "token" ? (
          <>
            <label htmlFor="token" className="text-sm font-semibold">
              Your access token
            </label>
            <Input id="token" name="token" type="password" autoComplete="off" value={value} onChange={(e) => setValue(e.target.value)} required className="h-11 bg-background text-base" />
          </>
        ) : (
          <>
            <label htmlFor="username" className="text-sm font-semibold">
              Username
            </label>
            <Input
              id="username"
              name="username"
              autoComplete="username"
              autoCapitalize="none"
              spellCheck={false}
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              className="h-11 bg-background text-base"
            />
            {mode === "signup" && <p className="-mt-1 text-xs text-muted-foreground">3 to 24 letters, numbers or underscores.</p>}
            <label htmlFor="password" className="text-sm font-semibold">
              Password
            </label>
            <Input
              id="password"
              name="password"
              type="password"
              autoComplete={mode === "signup" ? "new-password" : "current-password"}
              value={value}
              onChange={(e) => setValue(e.target.value)}
              required
              className="h-11 bg-background text-base"
            />
            {mode === "signup" && <p className="-mt-1 text-xs text-muted-foreground">At least 10 characters. A few random words is easy to remember and hard to guess.</p>}
          </>
        )}
        {error && (
          <p role="alert" className="text-sm font-medium text-destructive">
            {error}
          </p>
        )}
        <Button type="submit" size="lg" disabled={busy || !value.trim() || (mode !== "token" && !username.trim())}>
          {busy ? "Checking…" : mode === "signup" ? "Create account" : "Sign in"}
        </Button>
      </form>
      <div className="flex flex-col gap-2">
        <Button type="button" variant="outline" size="lg" onClick={onGuest}>
          Keep browsing as a guest
        </Button>
        <Button type="button" variant="ghost" size="lg" onClick={() => pick(mode === "token" ? "signin" : "token")}>
          {mode === "token" ? "Sign in with a username instead" : "Use an access token instead"}
        </Button>
      </div>
      <p className="text-sm text-muted-foreground">
        Forgot your password? Ask the person who runs this radar to reset it. A personal link from them signs you in too.
      </p>
    </main>
  );
}
