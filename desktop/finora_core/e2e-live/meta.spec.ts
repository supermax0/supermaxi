import { createHmac } from "node:crypto";
import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";

/**
 * Phase 7 live: a Meta-signed Messenger webhook hits the REAL server (ai_sales pipeline, house tenant) and the open
 * desktop shows the normalized message over SSE. Fully offline: the kill switch is on, so no AI reply or Meta call.
 */
const credsPath = process.env.FC_E2E_CREDS;
if (!credsPath)
  throw new Error("FC_E2E_CREDS must point at the JSON written by provision_finora_core_e2e.py");
const creds = JSON.parse(readFileSync(credsPath, "utf8")) as {
  server: string;
  house: string;
  users: Record<string, string>;
  meta: { webhook_key: string; app_secret: string; page_id: string };
};
const API = process.env.FC_E2E_API ?? "http://127.0.0.1:5018";
const WEBHOOK = `${API}/api/v1/ai-sales/webhooks/meta/${creds.house}/${creds.meta.webhook_key}`;

async function apiToken(): Promise<string> {
  const res = await fetch(`${API}/api/v1/finora-core/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: "fc_e2e_admin", password: creds.users.fc_e2e_admin }),
  });
  return ((await res.json()) as { accessToken: string }).accessToken;
}

async function setAutomation(paused: boolean) {
  const token = await apiToken();
  const res = await fetch(`${API}/api/v1/finora-core/automation`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ paused, reason: "live e2e: no automatic replies" }),
  });
  expect(res.status).toBe(200);
}

function messengerEvent(mid: string, text: string) {
  const ts = Date.now();
  return {
    object: "page",
    entry: [
      {
        id: creds.meta.page_id,
        time: ts,
        messaging: [
          {
            sender: { id: "e2e-1" },
            recipient: { id: creds.meta.page_id },
            timestamp: ts,
            message: { mid, text },
          },
        ],
      },
    ],
  };
}

async function postWebhook(payload: unknown, secret = creds.meta.app_secret) {
  const body = JSON.stringify(payload);
  const signature = "sha256=" + createHmac("sha256", secret).update(body).digest("hex");
  return fetch(WEBHOOK, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Hub-Signature-256": signature },
    body,
  });
}

async function signIn(page: Page) {
  await page.goto("/");
  await page.getByLabel("اسم المستخدم").fill("fc_e2e_admin");
  await page.getByLabel("كلمة المرور").fill(creds.users.fc_e2e_admin ?? "");
  await page.getByRole("button", { name: /دخول/ }).click();
  await page.locator(".orb-hit").click();
  await expect(page.locator(".workspace:not(.is-closed)")).toBeVisible();
}

test.beforeAll(async () => setAutomation(true));
test.afterAll(async () => setAutomation(false));

test("a signed Meta webhook appears live on the desktop", async ({ page }) => {
  await signIn(page);
  await page.waitForTimeout(1500); // let the event stream connect
  const text = `رسالة Meta حقيقية ${Date.now()}`;
  const res = await postWebhook(messengerEvent(`m_live_${Date.now()}`, text));
  expect(res.status).toBe(200);
  const row = page.getByRole("list", { name: "المحادثات" }).getByRole("button").first();
  await expect(row).toContainText("د. سارة", { timeout: 15_000 });
  await expect(row).toContainText(text);
  await row.click();
  await expect(page.locator(".msg.is-in").last()).toContainText(text);
});

test("a webhook with a forged signature is rejected and never shown", async ({ page }) => {
  await signIn(page);
  const text = `مزورة ${Date.now()}`;
  const res = await postWebhook(messengerEvent(`m_forged_${Date.now()}`, text), "f".repeat(32));
  expect(res.status).toBe(403);
  await page.waitForTimeout(3000);
  await expect(page.getByText(text)).toHaveCount(0);
});

test("Meta retrying the same delivery does not duplicate the message", async ({ page }) => {
  await signIn(page);
  const mid = `m_retry_${Date.now()}`;
  const text = `مكررة ${Date.now()}`;
  const payload = messengerEvent(mid, text);
  expect((await postWebhook(payload)).status).toBe(200);
  expect((await postWebhook(payload)).status).toBe(200);
  const row = page.getByRole("list", { name: "المحادثات" }).getByRole("button").first();
  await expect(row).toContainText(text, { timeout: 15_000 });
  await row.click();
  await expect(page.locator(".msg.is-in").filter({ hasText: text })).toHaveCount(1);
});
