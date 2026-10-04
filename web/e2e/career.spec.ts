import { expect, test, type Page } from "@playwright/test";

type RecordData = { id: string; revision: number; kind: string; label: string; text: string; context: string;
  source_note: string; state: string; fact_refs: { id: string; revision: number }[]; created_at: string;
  reusable: boolean; review_reasons: string[] };

async function setup(page: Page, stale = false, conflict = false) {
  const rows: RecordData[] = stale ? [{ id: "answer", revision: 1, kind: "answer", label: "Project answer",
    text: "Built the reader", context: "Project questions", source_note: "Owner reviewed", state: "approved",
    fact_refs: [{ id: "fact", revision: 1 }], created_at: "2026-10-04T00:00:00+00:00", reusable: false,
    review_reasons: ["supporting fact changed or is not approved"] }] : [];
  const history = [...rows];
  await page.addInitScript(() => {
    localStorage.setItem("radar.token", "offline-career-test");
    localStorage.setItem("radar.welcomed.owner", "1");
  });
  await page.route("**/api/**", async route => {
    const request = route.request(), url = new URL(request.url());
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (url.pathname === "/api/me") return json({ user: "owner", sources: 0, alerts_enabled: true, guest: false });
    if (url.pathname === "/api/stream") return route.fulfill({ contentType: "text/event-stream", body: "retry: 5000\n\n" });
    if (url.pathname === "/api/career" && request.method() === "GET") return json({ records: rows, next_after: null });
    if (url.pathname.endsWith("/history")) return json([...history].reverse());
    if (url.pathname.startsWith("/api/career") && ["POST", "PUT"].includes(request.method())) {
      if (conflict) return json({ detail: "record changed; reload before revising" }, 409);
      const body = request.postDataJSON();
      const record = { ...body, id: rows[0]?.id ?? "fact", revision: (body.expected_revision ?? 0) + 1,
        created_at: "2026-10-04T00:00:00+00:00", reusable: body.state === "approved", review_reasons: [] };
      rows.splice(0, rows.length, record);
      history.push(record);
      return json(record, request.method() === "POST" ? 201 : 200);
    }
    return json({ suggestions: [], muted: [] });
  });
  await page.goto("/#/career");
  await expect(page.getByRole("heading", { name: "Career evidence", exact: true })).toBeVisible();
}

test("career fact approval, revision and history preserve reviewed evidence", async ({ page }) => {
  await setup(page);
  await page.getByRole("button", { name: "Add record", exact: true }).click();
  await expect(page.getByLabel("Fact label", { exact: true })).toBeFocused();
  await page.getByLabel("Fact label", { exact: true }).fill("Guarded reader");
  await page.getByRole("textbox", { name: "Fact", exact: true }).fill("Built a guarded job reader.");
  await page.getByLabel("Source or confirmation note").fill("Confirmed contribution in my repository");
  await page.getByLabel("Review state").selectOption("approved");
  await page.getByRole("button", { name: "Save record" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Career record saved" })).toBeVisible();
  await page.getByRole("button", { name: "Revise fact" }).click();
  await expect(page.getByLabel("Review state")).toHaveValue("draft");
  await page.getByRole("textbox", { name: "Fact", exact: true }).fill("Built and maintained the guarded reader.");
  await page.getByRole("button", { name: "Save record" }).click();
  await page.getByRole("button", { name: "Show history" }).click();
  await expect(page.getByText("Revision 1 · approved", { exact: true })).toBeVisible();
  await expect(page.getByText("Revision 2 · draft", { exact: true })).toBeVisible();
  await expect(page.locator("html")).toHaveJSProperty("scrollWidth", await page.locator("html").evaluate(el => el.clientWidth));
});

test("career screen flags changed supporting facts without implying approval", async ({ page }) => {
  await setup(page, true);
  await expect(page.getByText("Needs review", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Revise answer" }).click();
  await expect(page.getByLabel("Where this answer applies")).toHaveValue("Project questions");
  await expect(page.getByText("Supporting fact revision 1 needs review.")).toBeVisible();
  await page.getByRole("button", { name: "Remove outdated reference" }).click();
  await expect(page.getByText("Supporting fact revision 1 needs review.")).toHaveCount(0);
});

test("career conflicts preserve edits and controls support keyboard and touch", async ({ page }) => {
  await setup(page, true, true);
  await page.getByRole("button", { name: "Revise answer" }).click();
  await page.getByRole("textbox", { name: "Answer", exact: true }).fill("My unsaved revised answer");
  const save = page.getByRole("button", { name: "Save record" });
  const box = await save.boundingBox();
  expect(box!.height).toBeGreaterThanOrEqual(44);
  expect(box!.width).toBeGreaterThanOrEqual(44);
  await save.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("alert")).toContainText("record changed");
  await expect(page.getByRole("textbox", { name: "Answer", exact: true })).toHaveValue("My unsaved revised answer");
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(page.getByRole("button", { name: "Add record", exact: true })).toBeFocused();
});
