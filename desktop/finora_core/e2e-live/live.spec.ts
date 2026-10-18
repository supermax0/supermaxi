import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";

const credsPath = process.env.FC_E2E_CREDS;
if (!credsPath)
  throw new Error("FC_E2E_CREDS must point at the JSON written by provision_finora_core_e2e.py");
const creds = JSON.parse(readFileSync(credsPath, "utf8")) as { users: Record<string, string> };
const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");

async function signIn(page: Page, username: string, password = creds.users[username] ?? "") {
  await page.goto("/");
  await page.getByLabel("اسم المستخدم").fill(username);
  await page.getByLabel("كلمة المرور").fill(password);
  await page.getByRole("button", { name: /دخول/ }).click();
}

const openOrb = async (page: Page) => {
  await page.locator(".orb-hit").click();
  await expect(page.locator(".workspace:not(.is-closed)")).toBeVisible();
};

test("wrong password is rejected with a clear message", async ({ page }) => {
  await signIn(page, "fc_e2e_admin", "definitely-wrong");
  await expect(page.getByRole("alert")).toContainText("بيانات الدخول غير صحيحة");
  await expect(page.getByLabel("كلمة المرور")).toHaveValue("");
});

test("operator signs in and sees real server state", async ({ page }) => {
  await signIn(page, "fc_e2e_admin");
  await expect(page.locator(".status-bubble")).toContainText("بإنتظار الرسائل الجديدة");
  await expect(page.locator(".live-pill")).toContainText("Live");
  await expect(page.getByText("DEV DATA")).toHaveCount(0); // real backend, not development fixtures
  await openOrb(page);
  const rows = page.getByRole("list", { name: "المحادثات" }).getByRole("button");
  await expect(rows).toHaveCount(3);
  // The most recent conversation is pre-selected (order depends on real activity, e.g. earlier live runs).
  const firstName = (await rows.first().locator(".cl-name").innerText()).trim();
  await expect(page.locator(".chat-head h2")).toHaveText(firstName);
  await rows.filter({ hasText: "أحمد علي" }).click();
  await expect(page.locator(".msg.is-in").first()).toContainText("عندي عيادة أسنان");
});

/** Put a conversation back under FINORA CORE control through the real API (tests own their state). */
async function resumeByName(name: string) {
  const api = process.env.FC_E2E_API ?? "http://127.0.0.1:5018";
  const login = await fetch(`${api}/api/v1/finora-core/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: "fc_e2e_admin", password: creds.users.fc_e2e_admin }),
  });
  const { accessToken } = (await login.json()) as { accessToken: string };
  const auth = { Authorization: `Bearer ${accessToken}` };
  const list = (await (await fetch(`${api}/api/v1/finora-core/conversations`, { headers: auth })).json()) as {
    items: { id: string; customerName: string }[];
  };
  const conv = list.items.find((c) => c.customerName === name);
  if (!conv) throw new Error(`conversation ${name} not provisioned`);
  await fetch(`${api}/api/v1/finora-core/conversations/${conv.id}/resume`, { method: "POST", headers: auth });
}

test("takeover, manual reply over the real API, then resume", async ({ page }) => {
  await resumeByName("د. سارة");
  await signIn(page, "fc_e2e_admin");
  await openOrb(page);
  await page
    .getByRole("list", { name: "المحادثات" })
    .getByRole("button")
    .filter({ hasText: "د. سارة" })
    .click();
  await expect(page.locator(".chat-head h2")).toHaveText("د. سارة");
  await page.getByRole("button", { name: /استلام المحادثة/ }).click();
  const box = page.getByLabel("نص الرسالة");
  const text = `رد مباشر ${Date.now()}`;
  await box.fill(text);
  await box.press("Enter");
  const sent = page.locator(".msg.from-human").filter({ hasText: text });
  await expect(sent).toBeVisible();
  await expect(sent.getByLabel("أُرسلت")).toBeVisible();
  await page.getByRole("button", { name: /إعادة تشغيل FINORA CORE/ }).click();
  await expect(page.locator(".composer.is-locked")).toBeVisible();
  // persisted server-side: survives a reload
  await page.reload();
  await openOrb(page);
  await page
    .getByRole("list", { name: "المحادثات" })
    .getByRole("button")
    .filter({ hasText: "د. سارة" })
    .click();
  await expect(page.locator(".msg.from-human").filter({ hasText: text })).toBeVisible();
});

test("a new customer message arrives live over SSE without reloading", async ({ page }) => {
  await signIn(page, "fc_e2e_admin");
  await openOrb(page);
  await expect(page.getByRole("list", { name: "المحادثات" }).getByRole("button")).toHaveCount(3);
  await page.waitForTimeout(1500); // let the stream connect
  const text = `سؤال جديد ${Date.now()}`;
  execFileSync("python", ["scripts/provision_finora_core_e2e.py", "inject", text], {
    cwd: REPO,
    stdio: "ignore",
  });
  const row = page.getByRole("list", { name: "المحادثات" }).getByRole("button").first();
  await expect(row).toContainText("Al-Rashed Co.", { timeout: 15_000 }); // moved to the top by real activity
  await expect(row).toContainText(text);
});

test("read-only operator cannot send, take over or pause automation", async ({ page }) => {
  await signIn(page, "fc_e2e_reader");
  await openOrb(page);
  await expect(page.locator(".composer.is-locked")).toBeVisible();
  await expect(page.getByRole("button", { name: /استلام المحادثة/ })).toHaveCount(0);
  await page.getByRole("button", { name: "العودة إلى FINORA CORE" }).click();
  await page.locator(".stage-btn.is-right").click();
  await expect(page.getByRole("button", { name: /إيقاف كل الأتمتة/ })).toHaveCount(0);
  await page.getByRole("button", { name: "الحساب", exact: true }).click();
  await expect(page.locator(".settings")).toContainText("عرض فقط");
});

test("sign out returns to the login screen and revokes the session", async ({ page }) => {
  await signIn(page, "fc_e2e_admin");
  await expect(page.locator(".status-bubble")).toBeVisible();
  await page.locator(".stage-btn.is-right").click();
  await page.getByRole("button", { name: "الحساب", exact: true }).click();
  await page.getByRole("button", { name: /تسجيل الخروج/ }).click();
  await expect(page.getByRole("heading", { name: "تسجيل الدخول" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: "تسجيل الدخول" })).toBeVisible();
});

test("login screen", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "تسجيل الدخول" })).toBeVisible();
  await page.waitForTimeout(700);
  await page.screenshot({ path: "test-results/live-login.png" });
});
