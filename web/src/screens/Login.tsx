import { useState, type FormEvent } from "react";
import { ApiError, token, type Me } from "../api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export function Login({ onSignedIn, onGuest, gated = false }: { onSignedIn: (me: Me) => void; onGuest: () => void; gated?: boolean }) {
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/me", { headers: { Authorization: `Bearer ${value.trim()}` } });
      if (res.status === 401) throw new ApiError(401, "That token wasn't accepted.");
      if (!res.ok) throw new ApiError(res.status, `The server answered ${res.status}. Is it running?`);
      token.set(value.trim());
      onSignedIn((await res.json()) as Me);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Can't reach the server.");
    } finally {
      setBusy(false);
    }
  }

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
      <form onSubmit={submit} className="flex flex-col gap-3 rounded-2xl border border-border bg-card p-5">
        <label htmlFor="token" className="text-sm font-semibold">
          Your access token
        </label>
        <Input
          id="token"
          type="password"
          autoComplete="current-password"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          required
          className="h-11 bg-background text-base"
        />
        {error && (
          <p role="alert" className="text-sm font-medium text-destructive">
            {error}
          </p>
        )}
        <Button type="submit" size="lg" disabled={busy || !value.trim()}>
          {busy ? "Checking…" : "Sign in"}
        </Button>
      </form>
      <Button type="button" variant="outline" size="lg" onClick={onGuest}>
        Keep browsing as a guest
      </Button>
      <p className="text-sm text-muted-foreground">
        No token? Ask whoever invited you for your personal link: opening it signs you in. The token stays on this device.
      </p>
    </main>
  );
}
