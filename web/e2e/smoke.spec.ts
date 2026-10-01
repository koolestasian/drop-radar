import { expect, test, type Page, type Route } from "@playwright/test";

const TOKEN = "test-token-kevin-0123456789";

type Opp = Record<string, unknown> & { id: string; action: { status: string; notes: string } | null };

function opp(id: string, company: string, title: string, extra: Partial<Opp> = {}): Opp {
  return {
    id, company, title, location: "San Francisco, CA", url: `https://example.com/${id}`, deadline: "",
    status: "New", first_seen: new Date(Date.now() - 3_600_000).toISOString(),
    published_at: new Date(Date.now() - 3_900_000).toISOString(), category: "Internship", role_track: "", season: "Summer 2027",
    sources: ["ats.greenhouse.stripe"], match: { ok: true, reasons: ["role: 'software engineer'", "level: 'intern'"] },
    action: null, ...extra,
  };
}

async function mockApi(page: Page) {
  const state: Opp[] = [
    opp("o1", "Stripe", "Software Engineer, Intern (Summer 2027)", { deadline: new Date(Date.now() + 2 * 86_400_000).toISOString().slice(0, 10) }),
    opp("o2", "NVIDIA", "Systems Software Engineer - New College Grad 2026", { sources: ["ats.workday.nvidia.wd5/NVIDIAExternalCareerSite"] }),
    opp("o3", "Airbnb", "Software Engineer, New Grad", { sources: ["github_repo.SimplifyJobs/New-Grad-Positions"] }),
  ];
  const fresh = opp("o9", "Ramp", "Software Engineer Intern - Summer 2027", { first_seen: new Date().toISOString() });
  const json = (route: Route, body: unknown, status = 200) =>
    route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

  await page.route("**/api/**", async (route) => {
    const req = route.request();
    if (req.headers()["authorization"] !== `Bearer ${TOKEN}`) return json(route, { detail: "missing or invalid bearer token" }, 401);
    const url = new URL(req.url());
    const path = url.pathname;
    if (path === "/api/me") return json(route, { user: "kevin", sources: 3 });
    if (path === "/api/stream")
      return route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: `retry: 5000\n\nevent: opportunity\ndata: ${JSON.stringify(fresh)}\n\n`,
      });
    if (path === "/api/opportunities") {
      const action = url.searchParams.get("action");
      const items = action
        ? state.filter((o) => (o.action?.status ?? "new") === action)
        : state.filter((o) => o.action?.status !== "ignored");
      return json(route, { items, next_cursor: null });
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
}

test("sign in, catch a live drop, save it, move it along the board", async ({ page }, info) => {
  await mockApi(page);
  await page.goto("/");
  await page.getByLabel("Your access token").fill("wrong-token-0123456789xx");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert")).toContainText("wasn't accepted");
  await page.getByLabel("Your access token").fill(TOKEN);
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page.getByRole("article")).toHaveCount(3);
  await expect(page.getByText("due in 2d")).toBeVisible();
  await page.screenshot({ path: `test-results/feed-${info.project.name}.png`, fullPage: true });

  await page.getByRole("button", { name: /1 new drop/ }).click();
  await expect(page.getByRole("article").first()).toContainText("Ramp");

  await page.getByRole("article").first().getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("article").first().getByRole("button", { name: "Saved" })).toBeVisible();

  await page.getByRole("link", { name: /Board/ }).last().click();
  const saved = page.getByLabel("Saved column");
  await expect(saved.getByRole("article")).toContainText("Ramp");
  await saved.getByLabel(/Status for/).selectOption("applied");
  await expect(page.getByLabel("Applied column").getByRole("article")).toContainText("Ramp");
  await page.screenshot({ path: `test-results/board-${info.project.name}.png`, fullPage: true });

  for (const screen of ["feed", "board", "sources", "settings"]) {
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
  await expect(page.getByRole("article")).toHaveCount(3);
  await page.screenshot({ path: `test-results/feed-dark-${info.project.name}.png`, fullPage: true });
});
