import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { api, token, type BoardDiscovery, type CompanyConfig, type Me, type ProfileConfig, type WatchlistConfig } from "../api/client";
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
// An account's extra companies: the boards where the server fixes the host, and its cap (keep both in step with radar/api/app.py).
const ACCOUNT_ATS = ["greenhouse", "lever", "ashby", "smartrecruiters", "workday"];
const MAX_EXTRA = 10;

// One tap fills roles, level keywords and excludes; locations and the target year stay as they are.
const LEVEL = ["intern", "internship", "co-op", "new grad", "grad", "graduate", "university", "early career", "entry level", "junior", "summer"];
const NOT = ["senior", "staff", "principal", "director", "high school", "phd"];
const PRESETS: { label: string; roles: string[] }[] = [
  { label: "Software and data", roles: ["software engineer", "software developer", "swe", "backend", "frontend", "full stack", "mobile engineer", "machine learning", "ml engineer", "ai engineer", "data engineer", "data scientist", "data analyst", "platform engineer", "security engineer"] },
  { label: "Quant and trading", roles: ["quantitative", "quant", "trading", "trader", "research engineer", "algorithm"] },
  { label: "Finance", roles: ["investment banking", "private equity", "venture capital", "investment", "markets", "equity research", "research analyst", "asset management", "wealth management", "corporate finance", "finance", "fp&a", "m&a", "credit", "risk", "treasury", "accounting", "audit"] },
  { label: "Business and consulting", roles: ["consulting", "consultant", "strategy", "business analyst", "business operations", "corporate development", "product manager", "marketing", "operations", "sales", "supply chain"] },
];
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
        name={`add-${label.toLowerCase().replace(/\W+/g, "-")}`}
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
  const preset = (roles: string[]) => setP((x) => ({ ...x, roles, keywords: LEVEL, exclude: NOT }));
  return (
    <form
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        save.mutate(p);
      }}
      className="flex flex-col gap-5"
    >
      <fieldset className="flex flex-col gap-2">
        <legend className="text-sm font-semibold">Start from a preset</legend>
        <p className="text-sm text-muted-foreground">Fills the roles and level below, which you can then edit. Nothing changes until you save.</p>
        <div className="flex flex-wrap gap-2">
          {PRESETS.map((x) => (
            <Button key={x.label} type="button" variant="outline" className="rounded-full pointer-coarse:h-11" onClick={() => preset(x.roles)}>
              {x.label}
            </Button>
          ))}
        </div>
      </fieldset>
      <Tags label="Roles you want" help="A title needs one of these… e.g. software engineer, investment banking." value={p.roles ?? []} onChange={set("roles")} />
      <Tags label="Level keywords" help="…and one of these. e.g. intern, new grad, summer analyst." value={p.keywords ?? []} onChange={set("keywords")} />
      <Tags label="Exclude" help="Any of these in a title rules it out. e.g. senior, phd." value={p.exclude ?? []} onChange={set("exclude")} />
      <Tags label="Locations" help="“United States” accepts any US city; “Remote” accepts remote roles. Empty = anywhere." value={p.locations ?? []} onChange={set("locations")} />
      <label className="flex flex-col gap-1.5">
        <span className="text-sm font-semibold">Target season year</span>
        <Input
          type="number"
          name="grad_year"
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

function WatchlistForm({ initial, account }: { initial: WatchlistConfig; account: boolean }) {
  const qc = useQueryClient();
  const [companies, setCompanies] = useState<CompanyConfig[]>(initial.companies ?? []);
  const [draft, setDraft] = useState<CompanyConfig>({ name: "", ats: "greenhouse", slug: "" });
  const [careersURL, setCareersURL] = useState("");
  const check = useMutation({
    mutationFn: (url: string) => api<BoardDiscovery>("/api/config/watchlist/discover", { method: "POST", body: JSON.stringify({ url }) }),
    onSuccess: (board) => setDraft((previous) => ({ name: previous.name, ats: board.ats, slug: board.slug })),
  });
  const save = useMutation({
    mutationFn: (body: WatchlistConfig) =>
      api<WatchlistConfig>("/api/config/watchlist", { method: "PUT", body: JSON.stringify(body) }),
    onSuccess: (saved) => {
      qc.setQueryData(["config", "watchlist"], saved);
      qc.invalidateQueries({ queryKey: ["sources"] });
    },
  });
  const boards = account ? ACCOUNT_ATS : ATS;
  const full = account && companies.length >= MAX_EXTRA;
  const others = account ? [] : [
    initial.instagram?.length && `${initial.instagram.length} Instagram`,
    initial.repos?.length && `${initial.repos.length} community lists`,
    initial.feeds?.length && `${initial.feeds.length} feeds`,
  ].filter(Boolean);

  return (
    <div className="flex flex-col gap-4">
      <form className="flex flex-col gap-2" onSubmit={(e) => { e.preventDefault(); check.mutate(careersURL.trim()); }}>
        <label htmlFor="careers-url" className="text-sm font-semibold">Careers URL</label>
        <div className="flex flex-col gap-2 sm:flex-row">
          <Input id="careers-url" type="url" required disabled={check.isPending} value={careersURL} onChange={(e) => { setCareersURL(e.target.value); check.reset(); }}
            placeholder="https://company.com/careers" className="h-11 min-w-0 text-base sm:text-sm" aria-describedby="careers-help" aria-invalid={check.isError} />
          <Button type="submit" size="lg" variant="outline" disabled={full || check.isPending || !careersURL.trim()}>{check.isPending ? "Checking…" : "Check careers URL"}</Button>
        </div>
        <p id="careers-help" className="text-sm text-muted-foreground">Paste a careers page or job-board link. Review the detected board below, give it a company name, then add and save.</p>
        {check.isError && <ErrorNote error={check.error} />}
        {check.isSuccess && <p role="status" className="text-sm text-muted-foreground">Verified {check.data.ats} board · {check.data.postings} open postings. Nothing added yet.</p>}
      </form>
      <form
        className="grid gap-2 sm:grid-cols-[1fr_9rem_1fr_auto]"
        onSubmit={(e) => {
          e.preventDefault();
          if (!draft.name.trim() || !draft.slug.trim()) return;
          if (companies.some((c) => c.ats === draft.ats && c.slug.toLowerCase() === draft.slug.trim().toLowerCase())) return;
          setCompanies([...companies, { ...draft, name: draft.name.trim(), slug: draft.slug.trim() }]);
          setDraft({ ...draft, name: "", slug: "" });
        }}
      >
        <Input name="company" autoComplete="off" aria-label="Company name" placeholder="Company" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} className="h-11 text-base sm:h-9 sm:text-sm" />
        <select name="ats" aria-label="Job board" value={draft.ats} onChange={(e) => setDraft({ ...draft, ats: e.target.value })} className={select}>
          {boards.map((a) => (
            <option key={a}>{a}</option>
          ))}
        </select>
        <Input
          name="slug"
          aria-label="Board slug"
          placeholder={SLUG_HINT[draft.ats] ?? "board slug"}
          value={draft.slug}
          onChange={(e) => setDraft({ ...draft, slug: e.target.value })}
          className="h-11 text-base sm:h-9 sm:text-sm"
        />
        <Button type="submit" variant="outline" size="lg" className="sm:h-9" disabled={full}>Add</Button>
      </form>
      <p className="text-sm text-muted-foreground [overflow-wrap:anywhere]">
        The slug is in the board's URL: boards.greenhouse.io/<b>stripe</b>, jobs.lever.co/<b>palantir</b>, or for Workday
        https://<b>nvidia.wd5</b>.myworkdayjobs.com/<b>NVIDIAExternalCareerSite</b> <ArrowRight className="inline size-3.5" aria-label="becomes" /> <b>nvidia.wd5/NVIDIAExternalCareerSite</b>.
        {others.length > 0 && ` Also watching: ${others.join(", ")} (edit those in the YAML).`}
      </p>
      {account && <p className="stamp text-muted-foreground">{companies.length} of {MAX_EXTRA} extra companies</p>}
      {save.isError && <ErrorNote error={save.error} />}
      <div className="flex items-center gap-3">
        <Button size="lg" disabled={save.isPending} onClick={() => save.mutate({ ...initial, companies })}>
          {save.isPending ? "Checking and saving…" : account ? "Save extra companies" : "Save watchlist"}
        </Button>
        {save.isSuccess && <span role="status" className="text-sm font-medium text-live">Saved — polling now.</span>}
      </div>
      <ul className="divide-y divide-border rounded-xl border border-border bg-card">
        {companies.map((c, i) => (
          <li key={`${c.ats}:${c.slug}`} className="flex items-center gap-3 px-3 py-1.5 text-sm">
            <span className="min-w-0 flex-1 truncate">
              <span className="font-medium">{c.name}</span> <span className="text-muted-foreground">{c.ats} · {c.slug}</span>
            </span>
            <Button variant="ghost" size="icon" aria-label={`Remove ${c.name}`} onClick={() => setCompanies(companies.filter((_, j) => j !== i))}>
              <X />
            </Button>
          </li>
        ))}
        {companies.length === 0 && <li className="px-3 py-4 text-sm text-muted-foreground">{account ? "No extra companies yet." : "No companies yet."}</li>}
      </ul>
    </div>
  );
}

function AlertsPanel({ me }: { me: Me }) {
  const qc = useQueryClient();
  const toggle = useMutation({
    mutationFn: (on: boolean) => api<Me>(`/api/alerts/${on ? "enable" : "disable"}`, { method: "POST" }),
    onSuccess: (m) => qc.setQueryData(["me"], m),
  });
  const test = useMutation({ mutationFn: () => api<void>("/api/alerts/test", { method: "POST" }) });
  if (!me.alerts_enabled)
    return me.account ? (
      <>
        <p className="text-sm text-muted-foreground">Get a push on your phone the moment a role that matches your profile appears. It uses the free ntfy app; no account there is needed.</p>
        {toggle.isError && <ErrorNote error={toggle.error} />}
        <Button size="lg" className="self-start" disabled={toggle.isPending} onClick={() => toggle.mutate(true)}>
          {toggle.isPending ? "Turning on…" : "Turn on phone alerts"}
        </Button>
      </>
    ) : (
      <p role="status" className="text-sm text-muted-foreground">Phone alerts are off for your account. The live feed works while open; phone delivery needs to be enabled on the server.</p>
    );
  return (
    <>
      <ol className="list-decimal space-y-1 pl-5 text-sm text-muted-foreground">
        <li>Install the free ntfy app on your phone.</li>
        <li>Open your private link below on that phone and subscribe.</li>
        <li>Allow notifications, then send a test push to check it arrives.</li>
      </ol>
      <div className="flex flex-wrap gap-2">
        {me.notification_url && (
          <Button asChild variant="outline">
            <a href={me.notification_url} target="_blank" rel="noopener noreferrer">
              Open your private notification topic <ExternalLink className="size-4" aria-hidden />
            </a>
          </Button>
        )}
        <Button variant="outline" disabled={test.isPending} onClick={() => test.mutate()}>
          {test.isPending ? "Sending…" : "Send a test push"}
        </Button>
        {me.account && (
          <Button variant="ghost" disabled={toggle.isPending} onClick={() => toggle.mutate(false)}>
            Turn off
          </Button>
        )}
      </div>
      <p className="text-xs text-muted-foreground">The link is private to you: anyone who has it can read your alerts, so don't share it.</p>
      {test.isSuccess && <p role="status" className="text-sm font-medium text-live">Sent. If nothing arrives, check the ntfy app's subscription.</p>}
      {test.isError && <ErrorNote error={test.error} />}
      {toggle.isError && <ErrorNote error={toggle.error} />}
    </>
  );
}

function AccountForm({ me }: { me: Me }) {
  const qc = useQueryClient();
  const [username, setUsername] = useState(me.username ?? (me.account ? "" : me.user));
  const [password, setPassword] = useState("");
  const save = useMutation({
    mutationFn: () =>
      api<{ token: string; me: Me }>("/api/auth/credentials", { method: "PUT", body: JSON.stringify({ username: username.trim(), password }) }),
    onSuccess: (res) => {
      token.set(res.token); // the old session was ended; this one replaces it
      qc.setQueryData(["me"], res.me);
      setPassword("");
    },
  });
  return (
    <form
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        save.mutate();
      }}
      className="flex flex-col gap-3"
    >
      <p className="text-sm text-muted-foreground">
        {me.username ? `You sign in as ${me.username}. Set a new password below to change it; other devices are signed out.` : "Choose a username and password so you can sign in on any device without the long access token."}
      </p>
      <label className="flex flex-col gap-1.5">
        <span className="text-sm font-semibold">Username</span>
        <Input name="username" autoComplete="username" autoCapitalize="none" spellCheck={false} value={username} onChange={(e) => setUsername(e.target.value)} required className="h-11 text-base sm:h-9 sm:text-sm" />
      </label>
      <label className="flex flex-col gap-1.5">
        <span className="text-sm font-semibold">{me.username ? "New password" : "Password"}</span>
        <Input name="new-password" type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} required className="h-11 text-base sm:h-9 sm:text-sm" />
        <span className="text-sm text-muted-foreground">At least 10 characters.</span>
      </label>
      {save.isError && <ErrorNote error={save.error} />}
      <div className="flex items-center gap-3">
        <Button type="submit" size="lg" disabled={save.isPending || !username.trim() || !password}>
          {save.isPending ? "Saving…" : me.username ? "Change password" : "Save sign-in"}
        </Button>
        {save.isSuccess && <span role="status" className="text-sm font-medium text-live">Saved.</span>}
      </div>
    </form>
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
          <ProfileForm key={me.data?.user} initial={profile.data} />
        )}
      </section>

      <section aria-labelledby="alerts-title" className="flex flex-col gap-3 rounded-2xl border border-border bg-card p-5">
        <h2 id="alerts-title" className={h2}>Phone alerts</h2>
        {me.data ? <AlertsPanel me={me.data} /> : me.isError ? <ErrorNote error={me.error} retry={() => me.refetch()} /> : <ListSkeleton rows={1} />}
      </section>

      <section aria-labelledby="signin-title" className="flex flex-col gap-3 rounded-2xl border border-border bg-card p-5">
        <h2 id="signin-title" className={h2}>Sign-in details</h2>
        {me.data ? <AccountForm me={me.data} /> : me.isError ? <ErrorNote error={me.error} retry={() => me.refetch()} /> : <ListSkeleton rows={1} />}
      </section>

      <section aria-labelledby="watchlist-title" className="flex flex-col gap-4">
        <div>
          <h2 id="watchlist-title" className={h2}>{me.data?.account ? "Extra companies" : "Watchlist"}</h2>
          <p className="text-sm text-muted-foreground">
            {me.data?.account
              ? "You already see every company the radar watches. Add more job boards here, up to 10. Each one is checked once before it is saved."
              : "The boards the radar polls for you. A board someone else also watches is polled once for both of you."}
          </p>
        </div>
        {watchlist.isPending ? <ListSkeleton rows={2} /> : watchlist.isError ? <ErrorNote error={watchlist.error} retry={() => watchlist.refetch()} /> : (
          <WatchlistForm key={me.data?.user} initial={watchlist.data} account={Boolean(me.data?.account)} />
        )}
      </section>

    </div>
  );
}
