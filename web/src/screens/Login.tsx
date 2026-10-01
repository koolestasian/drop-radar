import { useState, type FormEvent } from "react";
import { ApiError, token, type Me } from "../api/client";
import { Button } from "../components/ui";

export function Login({ onSignedIn }: { onSignedIn: (me: Me) => void }) {
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
    <main className="mx-auto flex min-h-dvh max-w-sm flex-col justify-center px-4">
      <div className="mb-8 flex items-center gap-3">
        <img src="/icon.svg" alt="" className="size-10" />
        <div>
          <h1 className="text-xl font-semibold">Drop Radar</h1>
          <p className="text-sm text-zinc-500">New roles, the moment they go live.</p>
        </div>
      </div>
      <form onSubmit={submit} className="space-y-3">
        <label className="block space-y-1">
          <span className="text-sm font-medium">Your access token</span>
          <input
            type="password"
            autoComplete="current-password"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            required
            className="min-h-11 w-full rounded-lg border border-zinc-300 bg-white px-3 dark:border-zinc-700 dark:bg-zinc-900"
          />
        </label>
        {error && (
          <p role="alert" className="text-sm text-red-600 dark:text-red-400">
            {error}
          </p>
        )}
        <Button type="submit" variant="primary" disabled={busy || !value.trim()} className="w-full">
          {busy ? "Checking…" : "Sign in"}
        </Button>
      </form>
      <p className="mt-6 text-xs text-zinc-500">
        Your token is the secret after your name in the server's <code>API_TOKENS</code>. It stays on this device.
      </p>
    </main>
  );
}
