import { expect, test, type Page, type Route } from "@playwright/test";

const TOKEN = "test-token-kevin-0123456789";
const GLOBE = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAGUlEQVR4nGNoaGj4TwlmGDVg1IBRA4aLAQCJj38fETZOLAAAAABJRU5ErkJggg==", "base64");
const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAAK0lEQVR4nO3OIQEAAAwEoetfeovxBoGn6sYEBAQEBAQEBAQEBAQEBAS2gQe3tfwuZanJ7gAAAABJRU5ErkJggg==", "base64"); // 32px: real icons are bigger than Google's 16px "no icon" globe

/** `format.ts`'s deadline() parses "YYYY-MM-DD" as a *local* midnight and diffs
 * against local "today". Date.now() + Nd then .toISOString() is UTC, so near a
 * local midnight (any timezone behind UTC, e.g. the evening in US timezones)
 * it lands on the wrong calendar day and "due in 2d" becomes "due in 3d" --
 * compute the string the same local way the app does. */
function localDateDaysFromNow(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

type Opp = Record<string, unknown> & { id: string; action: { status: string; notes: string } | null };

function opp(id: string, company: string, title: string, extra: Partial<Opp> = {}): Opp {
  return {
    id, company, title, location: "San Francisco, CA", url: `https://example.com/${id}`, deadline: "",
    status: "New", first_seen: new Date(Date.now() - 3_600_000).toISOString(),
    published_at: new Date(Date.now() - 3_900_000).toISOString(), category: "Internship", role_track: "", season: "Summer 2027",
    sources: ["ats.greenhouse.stripe"], match: { ok: true, reasons: ["role: 'software engineer'", "level: 'intern'"] },
    action: null, backfill: false, ...extra,
  };
}

async function mockApi(page: Page, more: Opp[] = []) {
  const state: Opp[] = [
    opp("o1", "Stripe", "Software Engineer, Intern (Summer 2027)", { deadline: localDateDaysFromNow(2), company_domain: "stripe.com" }),
    opp("o2", "NVIDIA", "Systems Software Engineer - New College Grad 2026", { sources: ["ats.workday.nvidia.wd5/NVIDIAExternalCareerSite"],
      published_at: `${new Date().toISOString().slice(0, 10)}T00:00:00+00:00` }), // Workday gives a date only
    opp("o3", "Airbnb", "Software Engineer, New Grad", { sources: ["github_repo.SimplifyJobs/New-Grad-Positions"], backfill: true }),
    ...more,
  ];
  const fresh = opp("o9", "Ramp", "Software Engineer Intern - Summer 2027", { first_seen: new Date().toISOString() });
  let published = false; // the streamed drop is on the server once a test says so
  const json = (route: Route, body: unknown, status = 200) =>
    route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

  // logos come from Google's favicon service; tests stay offline
  await page.route("**/s2/favicons**", (route) => route.fulfill({ contentType: "image/png", body: PNG }));
  await page.route("**/api/**", async (route) => {
    const req = route.request();
    if (req.headers()["authorization"] !== `Bearer ${TOKEN}`) return json(route, { detail: "missing or invalid bearer token" }, 401);
    const url = new URL(req.url());
    const path = url.pathname;
    if (path === "/api/me") return json(route, { user: "kevin", sources: 3, alerts_enabled: false, notification_url: null });
    if (path === "/api/stream")
      return route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: `retry: 5000\n\nevent: opportunity\ndata: ${JSON.stringify(fresh)}\n\n`,
      });
    if (path === "/api/opportunities") {
      const action = url.searchParams.get("action");
      const all = published && !state.includes(fresh) ? [fresh, ...state] : state;
      const items = action
        ? all.filter((o) => (o.action?.status ?? "new") === action)
        : all.filter((o) => o.action?.status !== "ignored");
      const backfill = url.searchParams.get("backfill");
      return json(route, { items: backfill ? items.filter((o) => String(o.backfill) === backfill) : items, next_cursor: null });
    }
    const m = path.match(/^\/api\/opportunities\/(.+)$/);
    if (m && req.method() === "PATCH") {
      const body = req.postDataJSON() as { status?: string; notes?: string };
      const o = [...state, fresh].find((x) => x.id === m[1])!;
      o.action = { status: body.status ?? o.action?.status ?? "new", notes: body.notes ?? o.action?.notes ?? "" };
      if (!state.includes(o)) state.unshift(o);
      return json(route, o);
    }
    if (path === "/api/sources/health")
      return json(route, [{ name: "ats.greenhouse.stripe", disabled: false, running: false, next_run: new Date().toISOString(),
        last_ok: new Date().toISOString(), fail_count: 0, last_error: null, items_24h: 2 }]);
    if (path === "/api/metrics")
      return json(route, { latency: [{ source: "ats.greenhouse.stripe", n: 4, p50: 42, p95: 180 }],
        items_per_day: { [new Date().toISOString().slice(0, 10)]: 3 }, llm_tokens_today: 1200, llm_daily_budget: 200000 });
    if (path === "/api/config/profile")
      return json(route, { roles: ["software engineer"], keywords: ["intern", "new grad"], exclude: ["senior"], grad_year: 2027,
        locations: ["Remote", "United States"], company_tiers: {} });
    if (path === "/api/config/watchlist")
      return json(route, { companies: [{ name: "Stripe", ats: "greenhouse", slug: "stripe", tier: "S" }], instagram: [], feeds: [], repos: [] });
    return json(route, { detail: "not found" }, 404);
  });
  return { publish: () => { published = true; } };
}

test("sign in, catch a live drop, save it, move it along the board", async ({ page }, info) => {
  const mock = await mockApi(page);
  await page.goto("/");
  await page.getByLabel("Your access token").fill("wrong-token-0123456789xx");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert")).toContainText("wasn't accepted");
  await page.getByLabel("Your access token").fill(TOKEN);
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page.getByRole("article")).toHaveCount(2);
  await expect(page.getByRole("heading", { name: "2 new roles" })).toBeVisible();
  await expect(page.getByText("due in 2d")).toBeVisible();
  // posted (by the employer) and found (by us) are two different clocks
  await expect(page.getByRole("article", { name: /^Stripe/ })).toContainText("San Francisco, CA · posted 1h ago");
  await expect(page.getByRole("article", { name: /^Stripe/ })).toContainText("found 1h ago · Greenhouse");
  await expect(page.getByRole("article", { name: /^NVIDIA/ })).toContainText("posted <1d ago"); // date only: whole days
  await expect(page.getByRole("region", { name: "Internships" }).getByRole("article")).toContainText("Stripe");
  await expect(page.getByRole("region", { name: "New grad" }).getByRole("article")).toContainText("NVIDIA");
  await page.screenshot({ path: `test-results/feed-${info.project.name}.png`, fullPage: true });

  mock.publish();
  await page.getByRole("button", { name: /1 new drop/ }).click();
  await expect(page.getByRole("article").first()).toContainText("Ramp");
  await expect(page.getByRole("button", { name: /new drop/ })).toHaveCount(0);

  await page.getByRole("button", { name: "All matches" }).click(); // new and already-open alike
  await expect(page.getByRole("article")).toHaveCount(4);
  await expect(page.getByRole("article", { name: /^Airbnb/ })).toBeVisible();
  await page.getByRole("button", { name: "New", exact: true }).click();

  await page.getByRole("article").first().getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("article").first().getByRole("button", { name: "Saved" })).toBeVisible();

  await page.getByRole("link", { name: /Board/ }).last().click();
  const saved = page.getByLabel("Saved column");
  await expect(saved.getByRole("article")).toContainText("Ramp");
  await saved.getByLabel(/Status for/).selectOption("applied");
  await expect(page.getByLabel("Applied column").getByRole("article")).toContainText("Ramp");
  await page.screenshot({ path: `test-results/board-${info.project.name}.png`, fullPage: true });

  for (const screen of ["feed", "jobs", "board", "sources", "settings"]) {
    await page.goto(`/#/${screen}`);
    await page.reload();
    await expect(page.locator("main").first()).toBeVisible();
    await page.waitForLoadState("networkidle");
    await page.screenshot({ path: `test-results/${screen}-${info.project.name}.png`, fullPage: true });
    // An absolutely positioned label inside a horizontally scrolling board once
    // widened the whole page on phones; nothing may make the page scroll sideways.
    const width = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth, document.documentElement.clientWidth]);
    expect(width[0], `${screen} scrolls sideways`).toBeLessThanOrEqual(width[2]);
    expect(width[1], `${screen} widened the layout viewport`).toBeLessThanOrEqual(width[2]);
  }
});

test("dark mode renders", async ({ page }, info) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await mockApi(page);
  await page.goto("/");
  await page.evaluate((t) => localStorage.setItem("radar.token", t), TOKEN);
  await page.reload();
  await expect(page.getByRole("article")).toHaveCount(2);
  await expect(page.getByRole("article", { name: /^Stripe/ }).locator("img")).toHaveAttribute("src", /domain=stripe\.com/);
  await expect(page.getByRole("article", { name: /^NVIDIA/ }).locator("img")).toHaveCount(0); // no domain: letter tile
  await page.screenshot({ path: `test-results/feed-dark-${info.project.name}.png`, fullPage: true });
});

test("an empty New feed points at all matches, without a live-drop button", async ({ page }) => {
  await mockApi(page);
  await page.route("**/api/opportunities?*", (route) => route.fulfill({
    contentType: "application/json",
    body: JSON.stringify({ items: new URL(route.request().url()).searchParams.get("backfill") !== "false"
      ? [opp("old", "Stripe", "Software Engineer Intern", { backfill: true })] : [], next_cursor: null }),
  }));
  await page.route("**/api/stream", (route) => route.fulfill({ contentType: "text/event-stream", body: "retry: 5000\n\n" }));
  await page.addInitScript((t) => localStorage.setItem("radar.token", t), TOKEN);
  await page.goto("/");
  await expect(page.getByText("No new roles yet")).toBeVisible();
  await page.getByRole("button", { name: "See all matches" }).click();
  await expect(page.getByRole("article")).toHaveCount(1);
  await expect(page.getByRole("article")).toContainText("Stripe");
  await expect(page.getByRole("button", { name: /new drop/ })).toHaveCount(0);
});

test("a populated feed reconciles missed drops and shows disabled phone alerts", async ({ page }) => {
  await mockApi(page);
  await page.clock.install();
  let ready = false;
  await page.route("**/api/opportunities?*", (route) => route.fulfill({
    contentType: "application/json",
    body: JSON.stringify({ items: [opp("first", "Stripe", "SWE Intern"),
      ...(ready ? [opp("later", "Airbnb", "Software Engineer Intern")] : [])], next_cursor: null }),
  }));
  await page.route("**/api/stream", (route) => route.abort());
  await page.addInitScript((t) => localStorage.setItem("radar.token", t), TOKEN);
  await page.goto("/");
  await expect(page.getByRole("article")).toHaveCount(1);
  await expect(page.getByText("Phone alerts are off.", { exact: false })).toBeVisible();
  ready = true;
  await page.clock.fastForward(31_000);
  await expect(page.getByRole("article")).toHaveCount(2);
  await expect(page.getByRole("button", { name: /new drop/ })).toHaveCount(0);
});

test("share copies only the public apply link and reports clipboard errors", async ({ page }) => {
  await mockApi(page);
  await page.addInitScript((t) => {
    localStorage.setItem("radar.token", t);
    Object.defineProperty(navigator, "share", { value: undefined, configurable: true });
    Object.defineProperty(navigator.clipboard, "writeText", { value: async (text: string) => {
      document.documentElement.dataset.copied = text;
    }, configurable: true });
  }, TOKEN);
  await page.goto("/");
  const card = page.getByRole("article", { name: /^Stripe/ });
  await card.getByRole("button", { name: "Share", exact: true }).click();
  await expect(card.getByRole("status")).toHaveText("Link copied");
  expect(await page.locator("html").getAttribute("data-copied")).toBe("https://example.com/o1");
  await page.evaluate(() => Object.defineProperty(navigator.clipboard, "writeText", {
    value: async () => { throw new Error("denied"); }, configurable: true,
  }));
  await card.getByRole("button", { name: "Share", exact: true }).click();
  await expect(card.getByRole("status")).toHaveText("Couldn't share. Copy the Apply link.");
});

test("settings offers only the signed-in users notification subscription", async ({ page }) => {
  await mockApi(page);
  await page.route("**/api/me", (route) => route.fulfill({ contentType: "application/json",
    body: JSON.stringify({ user: "kevin", sources: 3, alerts_enabled: true, notification_url: "https://ntfy.sh/private-test-k" }) }));
  await page.addInitScript((t) => localStorage.setItem("radar.token", t), TOKEN);
  await page.goto("/#/settings");
  await expect(page.getByRole("link", { name: /Open your private notification topic/ })).toHaveAttribute("href", "https://ntfy.sh/private-test-k");
  await expect(page.getByText(/Device delivery still needs/)).toBeVisible();
});

test("a #token= link signs the device in and leaves the address bar", async ({ page }) => {
  await mockApi(page);
  await page.goto(`/#token=${TOKEN}`);
  await expect(page.getByRole("article")).toHaveCount(2);
  expect(page.url()).not.toContain(TOKEN);
  expect(await page.evaluate(() => localStorage.getItem("radar.token"))).toBe(TOKEN);
});

test("a logo that fails to load becomes a letter; filters and sort reach the server; All jobs has everything", async ({ page }) => {
  await mockApi(page);
  // Google's "no icon": a 16px globe with status 404, which the browser still draws
  await page.route("**/s2/favicons**", (route) => route.fulfill({ status: 404, contentType: "image/png", body: GLOBE })); // registered last, wins
  await page.addInitScript((t) => localStorage.setItem("radar.token", t), TOKEN);
  const asked: URL[] = [];
  page.on("request", (r) => { if (r.url().includes("/api/opportunities?")) asked.push(new URL(r.url())); });
  await page.goto("/");
  const stripe = page.getByRole("article", { name: /^Stripe/ });
  await expect(stripe.locator("img")).toHaveCount(0);
  await expect(stripe.getByText("S", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "US only" }).click();
  await expect.poll(() => asked.some((u) => u.searchParams.get("us_only") === "true")).toBe(true);
  await page.getByLabel("Search role or company").fill("intern");
  await page.getByLabel("Location").fill("san francisco");
  await expect.poll(() => asked.some((u) => u.searchParams.get("q") === "intern" && u.searchParams.get("location") === "san francisco")).toBe(true);
  await page.getByLabel("Sort").selectOption("prestige");
  await expect.poll(() => asked.some((u) => u.searchParams.get("sort") === "prestige")).toBe(true);

  await page.getByRole("link", { name: /All jobs/ }).last().click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText("jobs");
  await expect(page.getByRole("button", { name: "All matches" })).toHaveCount(0); // no profile tabs here
  await expect.poll(() => asked.some((u) => u.searchParams.get("include") === "all" && !u.searchParams.has("backfill"))).toBe(true);
});

test("the same role posted in several places is one row; track chips narrow the feed", async ({ page }, info) => {
  await mockApi(page, [
    opp("n1", "Nokia", "AI R&D Engineer Co-op", { location: "Murray Hill, NJ" }),
    opp("n2", "Nokia", "AI R&D Engineer Co-op", { location: "Dallas, TX" }),
    opp("n3", "Nokia", "AI R&D Engineer Co-op", { location: "Sunnyvale, CA" }),
    opp("q1", "Jane Street", "Quantitative Trader Intern", { location: "New York, NY" }),
  ]);
  await page.addInitScript((t) => localStorage.setItem("radar.token", t), TOKEN);
  await page.goto("/");
  await page.screenshot({ path: `test-results/grouped-${info.project.name}.png`, fullPage: true });
  await expect(page.getByRole("article")).toHaveCount(4); // Stripe, NVIDIA, Nokia once, Jane Street
  await page.getByRole("button", { name: "+2 more postings of this role" }).click();
  await expect(page.getByRole("article")).toHaveCount(6);
  await expect(page.getByRole("article", { name: /^Nokia/ }).nth(2)).toContainText("Sunnyvale, CA");

  await page.getByRole("group", { name: "Track" }).getByRole("button", { name: /^Quant/ }).click();
  await expect(page.getByRole("article")).toHaveCount(1);
  await expect(page.getByRole("article")).toContainText("Jane Street");
});
