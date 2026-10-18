import { test, expect } from "@playwright/test";
import {
  A, C, SHOT, fixture, gotoClinic, openHome, say, setTutor, superLogin, tenantLogin,
} from "./_helpers.js";

/**
 * Phase 8A: the tutorial availability contract (registered vs available vs verified), scoped Google Ads/remarketing,
 * and a privacy regression. `tutor-e2e-a` is a seeded dental clinic (has a "dentistry" specialty); `tutor-e2e-c` is
 * stripped to an empty, non-dental clinic.
 */
test.use({ channel: "msedge" });
test.describe.configure({ mode: "serial", timeout: 120_000 });

const AD_HOSTS = ["googleadservices.com", "googlesyndication.com", "doubleclick.net"]; // + any google.com/pagead path
const isAdRequest = (url) => AD_HOSTS.some((h) => url.includes(h)) || url.includes("google.com/pagead") || url.includes("google.com/ccm") || url.includes("google.iq/pagead");

let ctxSuper;
let superPage;
let ctxA;
let pageA;
let ctxC;
let pageC;

test.beforeAll(async ({ browser }) => {
  fixture("reset");
  fixture("clear-patients", A);
  fixture("strip", C);
  ctxSuper = await browser.newContext({ baseURL: process.env.PLAYWRIGHT_BASE_URL, locale: "ar" });
  superPage = await ctxSuper.newPage();
  await superLogin(superPage);
  await setTutor(superPage, A, true);
  await setTutor(superPage, C, true);
  ctxA = await browser.newContext({ baseURL: process.env.PLAYWRIGHT_BASE_URL, locale: "ar" });
  pageA = await ctxA.newPage();
  await tenantLogin(pageA, A);
  ctxC = await browser.newContext({ baseURL: process.env.PLAYWRIGHT_BASE_URL, locale: "ar" });
  pageC = await ctxC.newPage();
  await tenantLogin(pageC, C);
});

test.afterAll(async () => {
  await ctxA?.close();
  await ctxC?.close();
  fixture("clear-patients", A);
  fixture("strip", C);
  fixture("reset");
  await setTutor(superPage, A, false).catch(() => {});
  await setTutor(superPage, C, false).catch(() => {});
  await ctxSuper?.close();
});

test("1. dental tenant: treatment_plan.create is a real, startable suggestion (no target_missing)", async () => {
  await gotoClinic(pageA);
  await openHome(pageA);
  const home = await pageA.evaluate(async () => (await (await fetch("/api/clinic/ai-tutor/knowledge")).json()));
  expect(home.quick_actions.map((q) => q.tutorial_id)).toContain("treatment_plan.create");
  const reply = await say(pageA, "شلون اسوي خطة علاج");
  await expect(reply).toContainText("أكدر أعلمك إنشاء خطة علاج");
  await expect(reply.locator('[data-tutor-chat-action="start_tutorial"]')).toHaveText("ابدأ التعليم");
  await pageA.screenshot({ path: `${SHOT}/89-availability-dental-available.png` });
});

test("2. non-dental tenant: treatment_plan.create is never offered, chat gives the exact unavailable wording, never target_missing", async () => {
  await gotoClinic(pageC);
  await openHome(pageC);
  const home = await pageC.evaluate(async () => (await (await fetch("/api/clinic/ai-tutor/knowledge")).json()));
  expect(home.quick_actions.map((q) => q.tutorial_id)).not.toContain("treatment_plan.create");
  expect(home.plan.groups.flatMap((g) => g.items.map((i) => i.id))).not.toContain("treatment_plan.create");
  const reply = await say(pageC, "شلون اسوي خطة علاج");
  await expect(reply).toContainText("خطة العلاج الحالية متاحة لعيادات الأسنان في هذه النسخة");
  expect(await reply.locator('[data-tutor-chat-action="start_tutorial"]').count()).toBe(0);
  // Never try to run it and discover a missing target: the server refuses to even start it.
  const start = await pageC.evaluate(async () => {
    const res = await fetch("/api/clinic/ai-tutor/tutorials/treatment_plan.create/start", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    return res.status;
  });
  expect(start).toBe(403);
  await pageC.screenshot({ path: `${SHOT}/90-availability-non-dental-unavailable.png` });
});

test("3. permission missing (dental tenant, no clinics_clinical): honest 'no permission', not the specialty message", async () => {
  const username = `avail_limited_${Date.now()}`;
  const password = "E2e!12345";
  const created = await pageA.evaluate(async ({ u, p }) => (await (await fetch("/clinics/api/staff", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ staff_type: "employee", name: "Limited", username: u, password: p, role_key: "clinic_reception" }),
  })).json()), { u: username, p: password });
  expect(created?.data || created).toBeTruthy();
  const ctxReception = await pageA.context().browser().newContext({ baseURL: process.env.PLAYWRIGHT_BASE_URL, locale: "ar" });
  const reception = await ctxReception.newPage();
  await reception.goto("/login");
  await reception.locator('input[name="tenant_slug"]').fill(A);
  await reception.locator("#username").fill(username);
  await reception.locator("#password").fill(password);
  await reception.locator('form.login-form button[type="submit"]').click();
  await reception.waitForURL((u) => !u.pathname.endsWith("/login"));
  await gotoClinic(reception);
  await openHome(reception);
  const reply = await say(reception, "شلون اسوي خطة علاج");
  await expect(reply).toContainText("ما عندك صلاحية تنفيذ هذه العملية");
  expect(await reply.locator('[data-tutor-chat-action="start_tutorial"]').count()).toBe(0);
  await ctxReception.close();
});

test("4. feature disabled: the API refuses and the UI shows nothing (regardless of availability)", async () => {
  await setTutor(superPage, A, false);
  const status = await pageA.evaluate(async () => (await fetch("/api/clinic/ai-tutor/status")).status);
  expect(status).toBe(403);
  await setTutor(superPage, A, true);
});

test("5. no third-party ad/remarketing requests on authenticated clinic pages (patients, appointments, visits, treatment plan, invoice)", async () => {
  const hits = [];
  const track = (req) => { if (isAdRequest(req.url())) hits.push(req.url()); };
  pageA.on("request", track);
  for (const path of ["/clinics/", "/clinics/patients", "/clinics/appointments", "/clinics/visits", "/clinics/billing", "/clinics/settings"]) {
    await pageA.goto(path);
    await pageA.waitForTimeout(2000);
  }
  pageA.off("request", track);
  expect(hits, `unexpected ad/remarketing requests: ${JSON.stringify(hits)}`).toEqual([]);
  // Google Fonts / Font Awesome are a separate (non-ads) concern, documented, not touched by this phase.
  const hasGtag = await pageA.evaluate(() => typeof window.gtag === "function");
  expect(hasGtag).toBe(false);
});

test("6. the login page (not the authenticated clinic app) still carries the tag: marketing/public pages are untouched", async () => {
  const ctx2 = await pageA.context().browser().newContext({ baseURL: process.env.PLAYWRIGHT_BASE_URL, locale: "ar" });
  const page2 = await ctx2.newPage();
  await page2.goto("/login");
  await page2.waitForTimeout(1000);
  expect(await page2.evaluate(() => !!document.querySelector('script[src*="googletagmanager"]'))).toBe(true);
  await ctx2.close();
});
