import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { api, type CompanyConfig, type Me, type ProfileConfig, type WatchlistConfig } from "../api/client";
import { Button, ErrorNote, Spinner } from "../components/ui";

const ATS = ["greenhouse", "lever", "ashby", "smartrecruiters", "workday"];
const TIERS = ["S", "A", "B", "C"];
const input =
  "min-h-10 rounded-lg border border-zinc-300 bg-white px-3 text-sm dark:border-zinc-700 dark:bg-zinc-900";

function Tags({ label, help, value, onChange }: { label: string; help: string; value: string[]; onChange: (v: string[]) => void }) {
  const [draft, setDraft] = useState("");
  const add = () => {
    const parts = draft.split(",").map((s) => s.trim()).filter(Boolean);
    if (parts.length) onChange([...value, ...parts.filter((p) => !value.includes(p))]);
    setDraft("");
  };
  return (
    <fieldset className="space-y-2">
      <legend className="text-sm font-semibold">{label}</legend>
      <p className="text-xs text-zinc-500">{help}</p>
      <ul className="flex flex-wrap gap-1.5">
        {value.map((t) => (
          <li key={t} className="flex items-center gap-1 rounded-full bg-zinc-100 py-1 pr-1 pl-3 text-sm dark:bg-zinc-800">
            {t}
            <button
              type="button"
              aria-label={`Remove ${t}`}
              onClick={() => onChange(value.filter((x) => x !== t))}
              className="flex size-6 items-center justify-center rounded-full text-zinc-500 hover:bg-zinc-200 dark:hover:bg-zinc-700"
            >
              ×
            </button>
          </li>
        ))}
      </ul>
      <input
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === ",") {
            e.preventDefault();
            add();
          }
        }}
        onBlur={add}
        aria-label={`Add to ${label}`}
        placeholder="Type and press Enter"
        className={`${input} w-full`}
      />
    </fieldset>
  );
}

function ProfileForm({ initial }: { initial: ProfileConfig }) {
  const qc = useQueryClient();
  const [p, setP] = useState<ProfileConfig>(initial);
  const save = useMutation({
    mutationFn: (body: ProfileConfig) => api<ProfileConfig>("/api/config/profile", { method: "PUT", body: JSON.stringify(body) }),
    onSuccess: (saved) => {
      qc.setQueryData(["config", "profile"], saved);
      qc.invalidateQueries({ queryKey: ["opportunities"] });
    },
  });
  const set = (k: keyof ProfileConfig) => (v: string[]) => setP((x) => ({ ...x, [k]: v }));
  return (
    <form
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        save.mutate(p);
      }}
      className="space-y-5"
    >
      <Tags label="Roles (the track)" help="A title needs one of these… e.g. software engineer, investment banking." value={p.roles ?? []} onChange={set("roles")} />
      <Tags label="Level keywords" help="…and one of these. e.g. intern, new grad, summer analyst." value={p.keywords ?? []} onChange={set("keywords")} />
      <Tags label="Exclude" help="Any of these in a title rules it out. e.g. senior, phd." value={p.exclude ?? []} onChange={set("exclude")} />
      <Tags label="Locations" help="“United States” accepts any US city; “Remote” accepts remote roles. Empty = anywhere." value={p.locations ?? []} onChange={set("locations")} />
      <label className="block space-y-1">
        <span className="text-sm font-semibold">Target season year</span>
        <input
          type="number"
          min={2000}
          max={2100}
          value={p.grad_year ?? ""}
          onChange={(e) => setP((x) => ({ ...x, grad_year: e.target.value ? Number(e.target.value) : null }))}
          className={`${input} block w-32`}
        />
        <span className="block text-xs text-zinc-500">“Summer 2027” passes 2027. Leave empty for any year.</span>
      </label>
      {save.isError && <ErrorNote error={save.error} />}
      <div className="flex items-center gap-3">
        <Button type="submit" variant="primary" disabled={save.isPending}>
          {save.isPending ? "Saving…" : "Save profile"}
        </Button>
        {save.isSuccess && <span role="status" className="text-sm text-emerald-600 dark:text-emerald-400">Saved — live now.</span>}
      </div>
    </form>
  );
}

function WatchlistForm({ initial }: { initial: WatchlistConfig }) {
  const qc = useQueryClient();
  const [companies, setCompanies] = useState<CompanyConfig[]>(initial.companies ?? []);
  const [draft, setDraft] = useState<CompanyConfig>({ name: "", ats: "greenhouse", slug: "", tier: "B" });
  const save = useMutation({
    mutationFn: (body: WatchlistConfig) =>
      api<WatchlistConfig>("/api/config/watchlist", { method: "PUT", body: JSON.stringify(body) }),
    onSuccess: (saved) => {
      qc.setQueryData(["config", "watchlist"], saved);
      qc.invalidateQueries({ queryKey: ["sources"] });
    },
  });
  const others = [
    initial.instagram?.length && `${initial.instagram.length} Instagram`,
    initial.repos?.length && `${initial.repos.length} community lists`,
    initial.feeds?.length && `${initial.feeds.length} feeds`,
  ].filter(Boolean);

  return (
    <div className="space-y-4">
      <ul className="divide-y divide-zinc-100 rounded-xl border border-zinc-200 dark:divide-zinc-800 dark:border-zinc-800">
        {companies.map((c, i) => (
          <li key={`${c.ats}:${c.slug}`} className="flex items-center gap-3 px-3 py-2 text-sm">
            <span className="min-w-0 flex-1 truncate">
              <span className="font-medium">{c.name}</span> <span className="text-zinc-500">{c.ats} · {c.slug}</span>
            </span>
            <span className="text-xs text-zinc-500">tier {c.tier}</span>
            <button
              type="button"
              aria-label={`Remove ${c.name}`}
              onClick={() => setCompanies(companies.filter((_, j) => j !== i))}
              className="flex size-8 items-center justify-center rounded-lg text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800"
            >
              ×
            </button>
          </li>
        ))}
        {companies.length === 0 && <li className="px-3 py-4 text-sm text-zinc-500">No companies yet.</li>}
      </ul>
      <form
        className="grid gap-2 sm:grid-cols-[1fr_9rem_1fr_5rem_auto]"
        onSubmit={(e) => {
          e.preventDefault();
          if (!draft.name.trim() || !draft.slug.trim()) return;
          setCompanies([...companies, { ...draft, name: draft.name.trim(), slug: draft.slug.trim() }]);
          setDraft({ ...draft, name: "", slug: "" });
        }}
      >
        <input aria-label="Company name" placeholder="Company" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} className={input} />
        <select aria-label="Job board" value={draft.ats} onChange={(e) => setDraft({ ...draft, ats: e.target.value })} className={input}>
          {ATS.map((a) => (
            <option key={a}>{a}</option>
          ))}
        </select>
        <input
          aria-label="Board slug"
          placeholder={draft.ats === "workday" ? "tenant.wd5/site" : "board slug"}
          value={draft.slug}
          onChange={(e) => setDraft({ ...draft, slug: e.target.value })}
          className={input}
        />
        <select aria-label="Tier" value={draft.tier} onChange={(e) => setDraft({ ...draft, tier: e.target.value })} className={input}>
          {TIERS.map((t) => (
            <option key={t}>{t}</option>
          ))}
        </select>
        <Button type="submit">Add</Button>
      </form>
      <p className="text-xs text-zinc-500">
        The slug is in the board's URL: boards.greenhouse.io/<b>stripe</b>, jobs.lever.co/<b>palantir</b>, or for Workday
        https://<b>nvidia.wd5</b>.myworkdayjobs.com/<b>NVIDIAExternalCareerSite</b> → <b>nvidia.wd5/NVIDIAExternalCareerSite</b>.
        {others.length > 0 && ` Also watching: ${others.join(", ")} (edit those in the YAML).`}
      </p>
      {save.isError && <ErrorNote error={save.error} />}
      <div className="flex items-center gap-3">
        <Button variant="primary" disabled={save.isPending} onClick={() => save.mutate({ ...initial, companies })}>
          {save.isPending ? "Saving…" : "Save watchlist"}
        </Button>
        {save.isSuccess && <span role="status" className="text-sm text-emerald-600 dark:text-emerald-400">Saved — polling now.</span>}
      </div>
    </div>
  );
}

export function Settings({ onSignOut }: { onSignOut: () => void }) {
  const me = useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/api/me") });
  const profile = useQuery({ queryKey: ["config", "profile"], queryFn: () => api<ProfileConfig>("/api/config/profile") });
  const watchlist = useQuery({ queryKey: ["config", "watchlist"], queryFn: () => api<WatchlistConfig>("/api/config/watchlist") });

  return (
    <div className="space-y-10">
      <section aria-labelledby="profile-title" className="space-y-4">
        <div>
          <h1 id="profile-title" className="text-lg font-semibold">What you're looking for</h1>
          <p className="text-sm text-zinc-500">Changes apply to your feed and your phone alerts right away.</p>
        </div>
        {profile.isPending ? <Spinner /> : profile.isError ? <ErrorNote error={profile.error} retry={() => profile.refetch()} /> : (
          <ProfileForm key={JSON.stringify(profile.data)} initial={profile.data} />
        )}
      </section>

      <section aria-labelledby="watchlist-title" className="space-y-4">
        <div>
          <h2 id="watchlist-title" className="text-lg font-semibold">Watchlist</h2>
          <p className="text-sm text-zinc-500">The boards the radar polls for you. A board someone else also watches is polled once for both of you.</p>
        </div>
        {watchlist.isPending ? <Spinner /> : watchlist.isError ? <ErrorNote error={watchlist.error} retry={() => watchlist.refetch()} /> : (
          <WatchlistForm key={JSON.stringify(watchlist.data)} initial={watchlist.data} />
        )}
      </section>

      <section aria-labelledby="account-title" className="space-y-2">
        <h2 id="account-title" className="text-lg font-semibold">Account</h2>
        <p className="text-sm text-zinc-500">{me.data ? `Signed in as ${me.data.user}, watching ${me.data.sources} sources.` : " "}</p>
        <Button variant="danger" onClick={onSignOut}>Sign out on this device</Button>
      </section>
    </div>
  );
}
