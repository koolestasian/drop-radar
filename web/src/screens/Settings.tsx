import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { api, type CompanyConfig, type Me, type ProfileConfig, type WatchlistConfig } from "../api/client";
import { ArrowRight, ExternalLink, X } from "lucide-react";
import { ErrorNote, ListSkeleton } from "../components/common";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

const ATS = ["greenhouse", "lever", "ashby", "smartrecruiters", "workday", "workable", "oracle", "eightfold", "amazon", "google", "apple", "avature", "sitemap"];
const SLUG_HINT: Record<string, string> = {
  workday: "tenant.wd5/site",
  oracle: "jpmc.fa/CX_1001",
  eightfold: "host/domain.com",
  amazon: "amazon",
  google: "google",
  apple: "internships-STDNT-INTRN",
  avature: "host/careers/SearchJobs",
  sitemap: "www.example.com/career-sitemap.xml",
};
const TIERS = ["S", "A", "B", "C"];
// Native selects: they open the OS picker on a phone, which is what you want there.
const select = "h-11 w-full rounded-lg border border-input bg-card px-3 text-base sm:h-9 sm:text-sm";

function Tags({ label, help, value, onChange }: { label: string; help: string; value: string[]; onChange: (v: string[]) => void }) {
  const [draft, setDraft] = useState("");
  const add = () => {
    const parts = draft.split(",").map((s) => s.trim()).filter(Boolean);
    if (parts.length) onChange([...value, ...parts.filter((p) => !value.includes(p))]);
    setDraft("");
  };
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="text-sm font-semibold">{label}</legend>
      <p className="text-sm text-muted-foreground">{help}</p>
      <ul className="flex flex-wrap gap-1.5">
        {value.map((t) => (
          <li key={t}>
            <Badge variant="secondary" className="h-8 gap-1 pr-1 pl-3 text-sm">
              {t}
              <button
                type="button"
                aria-label={`Remove ${t}`}
                onClick={() => onChange(value.filter((x) => x !== t))}
                className="grid size-6 place-items-center rounded-full text-muted-foreground hover:bg-background hover:text-foreground"
              >
                <X aria-hidden className="size-3.5" />
              </button>
            </Badge>
          </li>
        ))}
      </ul>
      <Input
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
        className="h-11 text-base sm:h-9 sm:text-sm"
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
      className="flex flex-col gap-5"
    >
      <Tags label="Roles you want" help="A title needs one of these… e.g. software engineer, investment banking." value={p.roles ?? []} onChange={set("roles")} />
      <Tags label="Level keywords" help="…and one of these. e.g. intern, new grad, summer analyst." value={p.keywords ?? []} onChange={set("keywords")} />
      <Tags label="Exclude" help="Any of these in a title rules it out. e.g. senior, phd." value={p.exclude ?? []} onChange={set("exclude")} />
      <Tags label="Locations" help="“United States” accepts any US city; “Remote” accepts remote roles. Empty = anywhere." value={p.locations ?? []} onChange={set("locations")} />
      <label className="flex flex-col gap-1.5">
        <span className="text-sm font-semibold">Target season year</span>
        <Input
          type="number"
          min={2000}
          max={2100}
          value={p.grad_year ?? ""}
          onChange={(e) => setP((x) => ({ ...x, grad_year: e.target.value ? Number(e.target.value) : null }))}
          className="h-11 w-32 text-base sm:h-9 sm:text-sm"
        />
        <span className="text-sm text-muted-foreground">“Summer 2027” passes 2027. Leave empty for any year.</span>
      </label>
      {save.isError && <ErrorNote error={save.error} />}
      <div className="flex items-center gap-3">
        <Button type="submit" size="lg" disabled={save.isPending}>
          {save.isPending ? "Saving…" : "Save profile"}
        </Button>
        {save.isSuccess && <span role="status" className="text-sm font-medium text-live">Saved — live now.</span>}
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
    <div className="flex flex-col gap-4">
      <ul className="divide-y divide-border rounded-xl border border-border bg-card">
        {companies.map((c, i) => (
          <li key={`${c.ats}:${c.slug}`} className="flex items-center gap-3 px-3 py-1.5 text-sm">
            <span className="min-w-0 flex-1 truncate">
              <span className="font-medium">{c.name}</span> <span className="text-muted-foreground">{c.ats} · {c.slug}</span>
            </span>
            <span className="stamp text-muted-foreground">tier {c.tier}</span>
            <Button variant="ghost" size="icon" aria-label={`Remove ${c.name}`} onClick={() => setCompanies(companies.filter((_, j) => j !== i))}>
              <X />
            </Button>
          </li>
        ))}
        {companies.length === 0 && <li className="px-3 py-4 text-sm text-muted-foreground">No companies yet.</li>}
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
        <Input aria-label="Company name" placeholder="Company" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} className="h-11 text-base sm:h-9 sm:text-sm" />
        <select aria-label="Job board" value={draft.ats} onChange={(e) => setDraft({ ...draft, ats: e.target.value })} className={select}>
          {ATS.map((a) => (
            <option key={a}>{a}</option>
          ))}
        </select>
        <Input
          aria-label="Board slug"
          placeholder={SLUG_HINT[draft.ats] ?? "board slug"}
          value={draft.slug}
          onChange={(e) => setDraft({ ...draft, slug: e.target.value })}
          className="h-11 text-base sm:h-9 sm:text-sm"
        />
        <select aria-label="Tier" value={draft.tier} onChange={(e) => setDraft({ ...draft, tier: e.target.value })} className={select}>
          {TIERS.map((t) => (
            <option key={t}>{t}</option>
          ))}
        </select>
        <Button type="submit" variant="outline" size="lg" className="sm:h-9">Add</Button>
      </form>
      <p className="text-sm text-muted-foreground [overflow-wrap:anywhere]">
        The slug is in the board's URL: boards.greenhouse.io/<b>stripe</b>, jobs.lever.co/<b>palantir</b>, or for Workday
        https://<b>nvidia.wd5</b>.myworkdayjobs.com/<b>NVIDIAExternalCareerSite</b> <ArrowRight className="inline size-3.5" aria-label="becomes" /> <b>nvidia.wd5/NVIDIAExternalCareerSite</b>.
        {others.length > 0 && ` Also watching: ${others.join(", ")} (edit those in the YAML).`}
      </p>
      {save.isError && <ErrorNote error={save.error} />}
      <div className="flex items-center gap-3">
        <Button size="lg" disabled={save.isPending} onClick={() => save.mutate({ ...initial, companies })}>
          {save.isPending ? "Saving…" : "Save watchlist"}
        </Button>
        {save.isSuccess && <span role="status" className="text-sm font-medium text-live">Saved — polling now.</span>}
      </div>
    </div>
  );
}

export function Settings() {
  const me = useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/api/me") });
  const profile = useQuery({ queryKey: ["config", "profile"], queryFn: () => api<ProfileConfig>("/api/config/profile") });
  const watchlist = useQuery({ queryKey: ["config", "watchlist"], queryFn: () => api<WatchlistConfig>("/api/config/watchlist") });
  const h2 = "text-xl font-semibold";

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-10">
      <section aria-labelledby="profile-title" className="flex flex-col gap-4">
        <div>
          <h1 id="profile-title" className="text-3xl font-bold tracking-tight">What you're looking for</h1>
          <p className="mt-1 text-sm text-muted-foreground">Changes apply to your feed and your phone alerts right away.</p>
        </div>
        {profile.isPending ? <ListSkeleton rows={2} /> : profile.isError ? <ErrorNote error={profile.error} retry={() => profile.refetch()} /> : (
          <ProfileForm key={JSON.stringify(profile.data)} initial={profile.data} />
        )}
      </section>

      <section aria-labelledby="alerts-title" className="flex flex-col gap-2 rounded-2xl border border-border bg-card p-5">
        <h2 id="alerts-title" className={h2}>Phone alerts</h2>
        {me.data?.alerts_enabled ? (
          <>
            <p className="text-sm text-muted-foreground">Delivery is configured. Subscribe in ntfy on your phone and allow notifications. Device delivery still needs a real notification check.</p>
            {me.data.notification_url && <Button asChild variant="outline" className="self-start"><a href={me.data.notification_url} target="_blank" rel="noopener noreferrer">Open your private notification topic <ExternalLink className="size-4" aria-hidden /></a></Button>}
          </>
        ) : me.data ? (
          <p role="status" className="text-sm text-muted-foreground">Phone alerts are off for your account. The live feed works while open; phone delivery needs to be enabled on the server.</p>
        ) : me.isError ? <ErrorNote error={me.error} retry={() => me.refetch()} /> : <ListSkeleton rows={1} />}
      </section>

      <section aria-labelledby="watchlist-title" className="flex flex-col gap-4">
        <div>
          <h2 id="watchlist-title" className={h2}>Watchlist</h2>
          <p className="text-sm text-muted-foreground">The boards the radar polls for you. A board someone else also watches is polled once for both of you.</p>
        </div>
        {watchlist.isPending ? <ListSkeleton rows={2} /> : watchlist.isError ? <ErrorNote error={watchlist.error} retry={() => watchlist.refetch()} /> : (
          <WatchlistForm key={JSON.stringify(watchlist.data)} initial={watchlist.data} />
        )}
      </section>

    </div>
  );
}
