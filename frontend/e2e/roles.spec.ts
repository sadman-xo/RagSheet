import { expect, test, type Page } from "@playwright/test";

// One smoke test for each demo user: sign in with the demo card, check the landing page, the sidebar pages,
// the scope badge, and that the landing page shows data. The server enforces the rules; this checks the UI.

const FINANCIAL_PAGES = ["profitability", "customers"];
const COMMON_PAGES = ["overview", "trends", "geography", "products", "operations", "compare", "explorer", "orders", "assistant", "data-notes"];

type DemoUser = { username: string; landing: string; financial: boolean; admin?: boolean; badge: RegExp };

const USERS: DemoUser[] = [
  { username: "admin", landing: "/overview", financial: true, admin: true, badge: /all data/i },
  { username: "exec", landing: "/overview", financial: true, badge: /all data/i },
  { username: "analyst", landing: "/explorer", financial: true, badge: /masked|pseudonym/i },
  { username: "ops", landing: "/operations", financial: false, badge: /hidden|financial/i },
  { username: "rm.namerica", landing: "/overview", financial: true, badge: /North America/ },
  { username: "rm.europe", landing: "/overview", financial: true, badge: /Europe/ },
  { username: "rm.asia", landing: "/overview", financial: true, badge: /Asia/ },
  { username: "rm.mideast", landing: "/overview", financial: true, badge: /Middle East/ },
  { username: "cm.electronics", landing: "/overview", financial: true, badge: /Electronics/ },
  { username: "cm.clothing", landing: "/overview", financial: true, badge: /Clothing/ },
  { username: "cm.home", landing: "/overview", financial: true, badge: /Home & Kitchen/ },
  { username: "cm.books", landing: "/overview", financial: true, badge: /Books & Media/ },
  { username: "cm.beauty", landing: "/overview", financial: true, badge: /Beauty & Health/ },
];

async function signIn(page: Page, username: string) {
  await page.goto("/login");
  await page.getByTestId(`demo-${username}`).click();
  await page.getByTestId("login-submit").click();
  await expect(page.getByTestId("sidebar")).toBeVisible();
}

for (const u of USERS) {
  test(`${u.username}: landing page, pages, and scope`, async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await signIn(page, u.username);
    await expect(page).toHaveURL(new RegExp(`${u.landing}(\\?|$)`));
    await expect(page.getByTestId("scope-badges")).toContainText(u.badge);

    for (const id of COMMON_PAGES) await expect(page.getByTestId(`nav-${id}`)).toHaveCount(1);
    for (const id of FINANCIAL_PAGES) await expect(page.getByTestId(`nav-${id}`)).toHaveCount(u.financial ? 1 : 0);
    await expect(page.getByTestId("nav-admin")).toHaveCount(u.admin ? 1 : 0);

    // The landing page shows data (KPI cards or a chart) and no error message.
    await expect(page.locator('[data-testid^="kpi-"], canvas, table').first()).toBeVisible();
    await expect(page.getByText(/something went wrong/i)).toHaveCount(0);
    expect(errors).toEqual([]);
  });
}

test("ops: a page with financial data is not available", async ({ page }) => {
  await signIn(page, "ops");
  await page.goto("/profitability");
  await expect(page.getByText("This page is not available for your role")).toBeVisible();
});

test("rm.europe: an order of another region is not found", async ({ page, context }) => {
  // An executive finds a North America order (works with every dataset), then rm.europe asks for it.
  await signIn(page, "exec");
  const orderId = await page.evaluate(async () => {
    const r = await fetch("/api/orders/search", {
      method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ limit: 1, with_total: false, filters: { regions: ["North America"] } }),
    });
    return (await r.json()).rows[0].order_id as string;
  });
  await context.clearCookies();
  await signIn(page, "rm.europe");
  const status = await page.evaluate(async (id) => (await fetch(`/api/orders/${id}`, { credentials: "include" })).status, orderId);
  expect(status).toBe(404);
});

test("exec: the assistant answers a metric question with an exact number", async ({ page }) => {
  await signIn(page, "exec");
  await page.goto("/assistant");
  await page.getByTestId("chat-input").fill("What was the gross revenue in 2023?");
  await page.getByTestId("chat-send").click();
  await expect(page.getByTestId("chat-answer").last()).toContainText(/Gross revenue for 2023 is [\d,]+\.\d{2}/, { timeout: 30_000 });
  await expect(page.getByTestId("chat-result").first()).toBeVisible();
});

test("rm.asia: the user menu opens on a click and signs out", async ({ page }) => {
  await signIn(page, "rm.asia");
  await page.getByTestId("user-menu").click();
  const signOut = page.getByTestId("logout");
  await expect(signOut).toBeVisible();
  // The header must not clip the menu: the whole button is inside the viewport and not covered.
  await signOut.click({ trial: true });
  await signOut.click();
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByTestId("login-submit")).toBeVisible();
});
