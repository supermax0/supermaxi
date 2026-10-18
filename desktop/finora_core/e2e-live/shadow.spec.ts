import { createHmac } from "node:crypto";
import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";

/**
 * Phase 9 live: Shadow Mode end to end against the real server. A Meta-signed customer message is processed by the
 * full FINORA CORE pipeline, the proposal appears beside the composer, NOTHING is sent by the agent, and the
 * operator's reply (built from the proposal) is recorded as accepted. Rules planner only (no model calls); manual
 * replies go through the development loopback, so nothing reaches Meta.
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

async function auth(): Promise<Record<string, string>> {
  const res = await fetch(`${API}/api/v1/finora-core/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: "fc_e2e_admin", password: creds.users.fc_e2e_admin }),
  });
  const { accessToken } = (await res.json()) as { accessToken: string };
  return { Authorization: `Bearer ${accessToken}`, "Content-Type": "application/json" };
}

async function setShadow(on: boolean) {
  const res = await fetch(`${API}/api/v1/finora-core/automation/flags`, {
    method: "POST",
    headers: await auth(),
    body: JSON.stringify({ AI_SHADOW_MODE: on ? "on" : "off" }),
  });
  expect(res.status).toBe(200);
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
            message: { mid: `m_shadow_${ts}`, text },
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

test.afterEach(async () => {
  await setShadow(false); // never leave the shared dev server in shadow mode
});

test("shadow mode proposes beside the composer, never sends, and records the human's reply", async ({ page }) => {
  await setShadow(true);
  await page.goto("/");
  await page.getByLabel("اسم المستخدم").fill("fc_e2e_admin");
  await page.getByLabel("كلمة المرور").fill(creds.users.fc_e2e_admin ?? "");
  await page.getByRole("button", { name: /دخول/ }).click();
  await expect(page.locator(".live-pill")).toHaveText(/Shadow/);
  await page.locator(".orb-hit").click();
  await expect(page.locator(".workspace:not(.is-closed)")).toBeVisible();
  await page.getByRole("list", { name: "المحادثات" }).getByRole("button").filter({ hasText: "د. سارة" }).click();
  await expect(page.locator(".chat-head h2")).toHaveText("د. سارة");
  await page.waitForTimeout(1500); // let the event stream connect
  const coreBubbles = page.locator(".msg.from-core");
  const before = await coreBubbles.count();

  await customerSays("مرحبا عندي عيادة اسنان وعدنا 4 اطباء");
  const strip = page.getByRole("region", { name: /اقتراح FINORA CORE/ });
  await expect(strip).toBeVisible({ timeout: 20_000 });
  await expect(strip).toContainText("وضع الظل — لا يُرسل");
  const proposed = (await strip.locator(".shadow-text").innerText()).trim();
  expect(proposed.length).toBeGreaterThan(5);
  await page.waitForTimeout(2500);
  await expect(coreBubbles).toHaveCount(before); // the agent sent nothing

  await strip.getByRole("button", { name: "استخدام الاقتراح" }).click();
  await expect(page.getByLabel("نص الرسالة")).toHaveValue(proposed);
  await page.getByRole("button", { name: "إرسال" }).click();
  await expect(page.locator(".msg.from-human").last()).toContainText(proposed.slice(0, 12), { timeout: 10_000 });
  await expect(strip).toContainText("استخدم الاقتراح كما هو", { timeout: 10_000 });
  await expect(coreBubbles).toHaveCount(before);

  // the server agrees: the proposal is answered + accepted, and the run is a shadow run with a trace
  const headers = await auth();
  const conv = (await (await fetch(`${API}/api/v1/finora-core/conversations`, { headers })).json()) as {
    items: { id: string; customerName: string }[];
  };
  const sara = conv.items.find((c) => c.customerName === "د. سارة");
  const shadow = (await (await fetch(`${API}/api/v1/finora-core/conversations/${sara?.id}/shadow`, { headers })).json()) as {
    items: { status: string; human: { accepted: boolean } | null }[];
  };
  expect(shadow.items[0]?.status).toBe("answered");
  expect(shadow.items[0]?.human?.accepted).toBe(true);
  const runs = (await (await fetch(`${API}/api/v1/finora-core/agent-runs?mode=shadow`, { headers })).json()) as {
    items: { mode: string; trace: { result: string } }[];
  };
  expect(runs.items[0]?.mode).toBe("shadow");
  expect(runs.items[0]?.trace.result).toContain("shadow");
});
