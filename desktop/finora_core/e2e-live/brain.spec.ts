import { createHmac } from "node:crypto";
import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";

/**
 * Phase 8 live: a Meta-signed customer message reaches the real server, the FINORA CORE brain (rules planner —
 * FINORA_CORE_AI_PROVIDER=off, no model calls) understands it, updates memory + CRM, and its reply appears on the
 * desktop. Replies go through the development loopback, so nothing is sent to Meta.
 */
const credsPath = process.env.FC_E2E_CREDS;
if (!credsPath)
  throw new Error("FC_E2E_CREDS must point at the JSON written by provision_finora_core_e2e.py");
const creds = JSON.parse(readFileSync(credsPath, "utf8")) as {
  house: string;
  users: Record<string, string>;
  meta: { webhook_key: string; app_secret: string; page_id: string };
};
const API = process.env.FC_E2E_API ?? "http://127.0.0.1:5018";

async function token(): Promise<string> {
  const res = await fetch(`${API}/api/v1/finora-core/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: "fc_e2e_admin", password: creds.users.fc_e2e_admin }),
  });
  return ((await res.json()) as { accessToken: string }).accessToken;
}

async function prepare() {
  const auth = { Authorization: `Bearer ${await token()}`, "Content-Type": "application/json" };
  await fetch(`${API}/api/v1/finora-core/automation`, {
    method: "POST",
    headers: auth,
    body: JSON.stringify({ paused: false, reason: "" }),
  });
  const list = (await (await fetch(`${API}/api/v1/finora-core/conversations`, { headers: auth })).json()) as {
    items: { id: string; customerName: string }[];
  };
  const sara = list.items.find((c) => c.customerName === "د. سارة");
  if (!sara) throw new Error("conversation not provisioned");
  await fetch(`${API}/api/v1/finora-core/conversations/${sara.id}/resume`, { method: "POST", headers: auth });
}

async function customerSays(text: string) {
  const ts = Date.now();
  const body = JSON.stringify({
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
            message: { mid: `m_brain_${ts}`, text },
          },
        ],
      },
    ],
  });
  const signature = "sha256=" + createHmac("sha256", creds.meta.app_secret).update(body).digest("hex");
  const res = await fetch(`${API}/api/v1/ai-sales/webhooks/meta/${creds.house}/${creds.meta.webhook_key}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Hub-Signature-256": signature },
    body,
  });
  expect(res.status).toBe(200);
}

test("the brain answers a real Meta message and the desktop shows reply + profile live", async ({ page }) => {
  await prepare();
  await page.goto("/");
  await page.getByLabel("اسم المستخدم").fill("fc_e2e_admin");
  await page.getByLabel("كلمة المرور").fill(creds.users.fc_e2e_admin ?? "");
  await page.getByRole("button", { name: /دخول/ }).click();
  await page.locator(".orb-hit").click();
  await expect(page.locator(".workspace:not(.is-closed)")).toBeVisible();
  const row = page
    .getByRole("list", { name: "المحادثات" })
    .getByRole("button")
    .filter({ hasText: "د. سارة" });
  await row.click();
  await expect(page.locator(".chat-head h2")).toHaveText("د. سارة");
  await page.waitForTimeout(1500); // let the event stream connect
  const coreBubbles = page.locator(".msg.from-core");
  const before = await coreBubbles.count();

  await customerSays("السلام عليكم عندي عيادة اسنان واريد نظام");
  // A new FINORA CORE reply arrives live (wording depends on what the brain already knows about this customer).
  await expect(coreBubbles).toHaveCount(before + 1, { timeout: 20_000 });
  await expect(page.locator(".cp-facts")).toContainText("أسنان", { timeout: 10_000 });

  await customerSays("عدنا 3 اطباء و2 موظفين وفرع واحد");
  await expect(coreBubbles).toHaveCount(before + 2, { timeout: 20_000 });
  await expect(coreBubbles.last()).not.toContainText("كم طبيب"); // never re-asks what it was just told
  await expect(page.locator(".cp-facts")).toContainText("3", { timeout: 10_000 });
});
