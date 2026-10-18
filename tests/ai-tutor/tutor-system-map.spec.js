import fs from "node:fs";
import { test, expect } from "@playwright/test";
import { SAFE_OPENERS, classify, mayClick, scanClinic } from "../../scripts/ai_tutor_runtime_scan.mjs";

/**
 * Phase 6 browser E2E: runtime analyzer (real crawl of a test clinic), Super Admin System Map, simulated breakage,
 * scan diff and the chat's use of the catalog. Server must run with AI_TUTOR_ANALYZER_SIMULATION=1 and an
 * isolated AI_TUTOR_SYSTEM_MAP_DIR; the spec resets that directory itself before and after (test-only endpoint).
 */
const CREDS = JSON.parse(fs.readFileSync(process.env.E2E_TUTOR_CREDS, "utf-8"));
const A = "tutor-e2e-a";
const SHOT = process.env.E2E_SHOTS || "tests/_artifacts/tutor";
const BASE = process.env.PLAYWRIGHT_BASE_URL;
const MAP = "/superadmin/ai-tutor/system-map";

test.use({ channel: "msedge" });
test.describe.configure({ mode: "serial", timeout: 240_000 }); // the crawl visits 30 pages and opens 5 forms

let ctxSuper;
let ctxA;
let superPage;
let pageA;
let runtime;

async function tenantLogin(page, slug) {
  await page.goto("/login");
  await page.locator('input[name="tenant_slug"]').fill(slug);
  await page.locator("#username").fill(CREDS.tenants[slug].username);
  await page.locator("#password").fill(CREDS.tenants[slug].password);
  await page.locator('form.login-form button[type="submit"]').click();
  await page.waitForURL((url) => !url.pathname.endsWith("/login"), { timeout: 35_000 });
}

async function superLogin(page) {
  await page.goto("/superadmin/login");
  await page.locator("#username").fill(CREDS.superadmin.username);
  await page.locator("#password").fill(CREDS.superadmin.password);
  await page.locator("form button.sa-login-submit").click();
  await page.waitForURL((url) => !url.pathname.endsWith("/login"));
}

const row = (id) => superPage.locator(`#smTable tbody tr[data-id="${id}"]`);
const status = (id) => row(id).locator(".sm-status");
const upload = (payload) => superPage.request.post(`${MAP}/runtime`, { data: payload });

async function openMap() {
  await superPage.goto(MAP);
  await expect(superPage.locator("#smRoot")).toBeVisible();
}

async function runScan() {
  await superPage.locator("#smScan").click();
  await expect(superPage.locator("#smScan")).toBeEnabled();
  await expect(superPage.locator("#smMeta")).toContainText("scanned:");
}

async function staffCount(page) {
  return page.evaluate(async () => (await (await fetch("/clinics/api/staff")).json()).data.items.length);
}

test.beforeAll(async ({ browser }) => {
  ctxSuper = await browser.newContext({ baseURL: BASE, locale: "ar", viewport: { width: 1440, height: 1000 } });
  ctxA = await browser.newContext({ baseURL: BASE, locale: "ar" });
  [superPage, pageA] = await Promise.all([ctxSuper.newPage(), ctxA.newPage()]);
  await Promise.all([superLogin(superPage), tenantLogin(pageA, A)]);
  // Isolation: this spec owns the snapshot state, whatever ran before it.
  expect((await superPage.request.post(`${MAP}/reset`)).ok()).toBe(true);
});

test.afterAll(async () => {
  await superPage?.request.post(`${MAP}/reset`).catch(() => {});
  await Promise.all([ctxSuper, ctxA].map((c) => c?.close()));
});

test("1. runtime analyzer: crawls the real clinic in a browser, opens modals only, never writes", async () => {
  const before = await staffCount(pageA);
  runtime = await scanClinic(pageA, { baseURL: BASE });
  fs.writeFileSync(`${SHOT}/runtime-scan.json`, JSON.stringify(runtime, null, 1));
  expect(runtime.pages.length).toBeGreaterThanOrEqual(25);
  expect(runtime.pages.filter((p) => p.accessible).length).toBeGreaterThanOrEqual(25);
  const staff = runtime.pages.find((p) => p.id === "staff");
  const find = (page, kind, id) => page.elements.find((e) => e.kind === kind && e.id === id);
  expect(find(staff, "action", "doctor.create")).toMatchObject({ visible: true, label: expect.stringContaining("إضافة طبيب") });
  expect(find(staff, "action", "employee.create").visible).toBe(true);
  expect(find(staff, "field", "doctor.name")).toMatchObject({ in_modal: true, visible: true }); // seen only after opening the form
  expect(find(staff, "section", "staff.form").in_modal).toBe(true);
  const specialties = runtime.pages.find((p) => p.id === "specialties");
  expect(find(specialties, "field", "specialty.name").in_modal).toBe(true);
  expect(find(runtime.pages.find((p) => p.id === "dashboard"), "page", "dashboard")).toBeTruthy();
  // Safety: only allow-listed openers were clicked, dangerous classes were listed but never touched, zero writes.
  expect(runtime.safety.clicked.sort()).toEqual([...SAFE_OPENERS].sort());
  expect(runtime.safety.skipped.map((s) => s.id)).toEqual(expect.arrayContaining(["doctor.save", "specialty.save"]));
  expect(runtime.safety.skipped.every((s) => ["destructive", "financial", "irreversible"].includes(s.class))).toBe(true);
  expect(runtime.safety.writes_observed).toBe(0);
  expect(await staffCount(pageA)).toBe(before); // nothing was created
});

test("2. the crawler's safety classifier refuses destructive, financial and irreversible actions", async () => {
  expect(classify("patient.delete")).toBe("destructive");
  expect(classify("invoice.refund")).toBe("financial");
  expect(classify("payment.record")).toBe("financial");
  expect(classify("doctor.save")).toBe("irreversible");
  expect(classify("nav.billing")).toBe("safe"); // plain navigation
  expect(mayClick("doctor.create")).toBe(true);
  expect(mayClick("invoice.refund", ["invoice.refund"])).toBe(false); // even if someone allow-lists it by mistake
  expect(mayClick("patient.delete", ["patient.delete"])).toBe(false);
  expect(mayClick("appointment.create")).toBe(true); // a form opener on the allow-list
  for (const action of ["appointment.checkin", "queue.add", "visit.start", "invoice.create", "doctor.schedule"]) {
    expect(mayClick(action), action).toBe(false); // they change state: never on the allow-list
  }
});

test("3. System Map is Super Admin only", async () => {
  await pageA.goto(MAP);
  await expect(pageA).toHaveURL(/\/superadmin\/login|\/login/);
  const res = await pageA.evaluate(async () => (await fetch("/superadmin/ai-tutor/system-map/data")).status);
  expect(res).toBe(403);
});

test("4. Super Admin: upload runtime, run scan, results appear with separate coverage numbers", async () => {
  const uploaded = await superPage.request.post("/superadmin/ai-tutor/system-map/runtime", { data: runtime });
  expect((await uploaded.json()).ok).toBe(true);
  await openMap();
  await expect(superPage.locator("#smMeta")).toContainText("لا يوجد فحص بعد");
  await runScan();
  await expect(superPage.locator("#smMeta")).toContainText("static + runtime");
  await expect(superPage.locator('[data-card="pages"] strong')).toHaveText("31");
  expect(Number(await superPage.locator('[data-card="actions"] strong').innerText())).toBeGreaterThanOrEqual(41);
  expect(Number(await superPage.locator('[data-card="fields"] strong').innerText())).toBeGreaterThanOrEqual(24);
  for (const name of ["System Discovery Coverage", "Knowledge Coverage", "Tutorial Coverage", "Verified Tutorial Coverage"]) {
    await expect(superPage.locator("#smCoverage")).toContainText(name);
  }
  await expect(superPage.locator('[data-coverage="discovery"]')).toContainText(/\d+ \/ 31 pages/);
  await expect(superPage.locator('[data-coverage="verified"]')).toContainText(/Tutorials verified: (\d+) \/ \1 · broken: 0/);
  await superPage.screenshot({ path: `${SHOT}/50-system-map-overview.png`, fullPage: false });
});

test("5. table: every discovered feature has a verified lesson (nothing tutorial_missing); filters work", async () => {
  await expect(status("doctor.create")).toHaveText("verified");
  await expect(status("specialty.create")).toHaveText("verified");
  await expect(status("employee.create")).toHaveText("verified");
  await expect(status("patient.create")).toHaveText("verified");
  await expect(status("invoice.create")).toHaveText("verified");
  await expect(row("doctor.create")).toContainText("clinics_admin");
  await expect(row("doctor.create")).toContainText("staff");

  await superPage.locator('[data-filter="tutorial_missing"]').click();
  await expect(superPage.locator("#smEmpty")).toBeVisible(); // Phase 7 closed the gap: no feature is left without a lesson
  await expect(row("doctor.create")).toHaveCount(0);
  await superPage.screenshot({ path: `${SHOT}/51-system-map-missing-tutorial.png` });
  await superPage.locator('[data-filter="verified"]').click();
  await expect(row("doctor.create")).toBeVisible();
  await expect(row("employee.create")).toBeVisible();
  await expect(row("appointment.checkin")).toBeVisible();
  await superPage.locator('[data-filter="broken"]').click();
  await expect(superPage.locator("#smEmpty")).toBeVisible(); // no broken elements
  await superPage.locator('[data-filter="all"]').click();
  await superPage.locator("#smCategory").selectOption("feature");
  expect(await superPage.locator("#smTable tbody tr").count()).toBeGreaterThanOrEqual(14); // the core journey's feature actions
  await superPage.locator("#smCategory").selectOption("all");
  await superPage.locator("#smSearch").fill("specialty");
  await expect(row("specialty.create")).toBeVisible();
  await expect(row("doctor.create")).toHaveCount(0);
  await superPage.locator("#smSearch").fill("");
});

test("6. tabs: fields, pages and tutorials with the doctor.create → specialty.create dependency", async () => {
  await superPage.locator('[data-tab="field"]').click();
  await expect(row("doctor.name")).toBeVisible();
  await expect(row("employee.name")).toBeVisible();
  await superPage.locator('[data-tab="page"]').click();
  await expect(superPage.locator("#smTable tbody tr")).toHaveCount(31);
  await expect(row("staff")).toContainText("clinics_admin");
  await superPage.locator('[data-tab="tutorial"]').click();
  await expect(row("doctor.create")).toContainText("doctor.create → specialty.create");
  await expect(row("doctor.create").locator(".sm-status")).toHaveText("verified");
  await expect(row("specialty.create").locator(".sm-status")).toHaveText("verified");
  await superPage.screenshot({ path: `${SHOT}/52-system-map-tutorials.png` });
});

test("7. temporary test-environment breakage: doctor.create target missing -> broken, never saved", async () => {
  await superPage.locator('[data-tab="action"]').click();
  await superPage.locator("#smSimId").fill("doctor.create");
  await superPage.locator("#smSimulate").click();
  await expect(superPage.locator("#smBanner")).toContainText("محاكاة اختبار فقط");
  await expect(status("doctor.create")).toHaveText("broken");
  await superPage.locator('[data-filter="broken"]').click();
  await expect(row("doctor.create")).toBeVisible();
  await superPage.locator('[data-tab="tutorial"]').click();
  await expect(row("doctor.create").locator(".sm-status")).toHaveText("broken");
  await expect(row("doctor.create")).toContainText("target_missing");
  await superPage.screenshot({ path: `${SHOT}/53-system-map-broken-simulation.png` });
  await openMap(); // reload: the simulation was not persisted
  await expect(status("doctor.create")).toHaveText("verified");
  await expect(superPage.locator("#smBanner")).toBeHidden();
});

test("8. diff between scans (+ new action, then - removed) and the Newly Discovered filter", async () => {
  const withExtra = structuredClone(runtime);
  withExtra.pages.push({ id: "appointments", route: "/clinics/appointments", accessible: true, status: 200, elements: [
    { kind: "action", id: "appointment.reschedule", visible: true, in_modal: false, label: "تأجيل موعد" }] });
  expect((await (await upload(withExtra)).json()).ok).toBe(true);
  await openMap();
  await runScan();
  await expect(superPage.locator("#smDiffPanel")).toBeVisible();
  await expect(superPage.locator("#smDiff")).toContainText("+ appointment.reschedule");
  await expect(status("appointment.reschedule")).toHaveText("knowledge_missing");
  await superPage.locator('[data-filter="new"]').click();
  await expect(row("appointment.reschedule")).toBeVisible();
  await expect(row("doctor.create")).toHaveCount(0);
  await superPage.screenshot({ path: `${SHOT}/54-system-map-diff-new.png` });
});

test("9. the chat tells apart: discovered-without-lesson / missing feature / feature with lesson", async () => {
  await superPage.goto("/superadmin/tenants");
  superPage.once("dialog", (dialog) => dialog.accept());
  await superPage.locator(`button.btn-details-trigger[data-slug="${A}"]`).click();
  await superPage.locator('[data-tenant-tab="platform"]').click();
  await superPage.locator("#ft-m-enable").click();
  await expect(superPage.locator("#ft-m-state")).toContainText("مفعّل");

  await pageA.goto("/clinics/");
  await pageA.waitForFunction(() => !!window.FinoraTutor?.launcher);
  await pageA.locator('[data-tutor-action="welcome-later"]').click({ timeout: 4000 }).catch(() => undefined); // welcome card, first visit
  await pageA.locator("#finoraAiFab").click();
  await pageA.locator('[data-tutor-menu="learn"]').click();
  const say = async (text) => {
    const bot = pageA.locator('[data-tutor-msg="bot"]:not(.is-typing)');
    const before = await bot.count();
    await pageA.locator('[data-tutor-ui="chat-input"]').fill(text);
    await pageA.locator('[data-tutor-ui="chat-send"]').click();
    await expect(bot).toHaveCount(before + 1, { timeout: 15_000 });
    return bot.last();
  };
  const exists = await say("وين تأجيل موعد");
  await expect(exists).toContainText("الميزة موجودة في صفحة المواعيد");
  await expect(exists).toContainText("الميزة موجودة بالنظام، لكن الشرح التفاعلي الخاص بها بعده غير متوفر");
  expect(await exists.locator('[data-tutor-chat-action="start_tutorial"]').count()).toBe(0); // no invented lesson
  const missing = await say("وين نظام العمليات الجراحية");
  await expect(missing).toContainText("ما لقيت هذه الميزة ضمن النسخة الحالية");
  const lesson = await say("شلون أضيف طبيب");
  await expect(lesson.locator('[data-tutor-chat-action="start_tutorial"]')).toHaveText("ابدأ التعليم");
  const page = await say("شنو هاي الصفحة");
  await expect(page).toContainText("أنت حالياً بصفحة");
  await pageA.screenshot({ path: `${SHOT}/55-chat-three-cases.png` });
});

test("10. cleanup: real runtime scan restored, feature disabled again", async () => {
  expect((await (await upload(runtime)).json()).ok).toBe(true);
  await openMap();
  await runScan();
  await expect(status("doctor.create")).toHaveText("verified");
  await expect(superPage.locator("#smDiff")).toContainText("- appointment.reschedule");
  await superPage.screenshot({ path: `${SHOT}/56-system-map-diff-removed.png` });
  await superPage.goto("/superadmin/tenants");
  superPage.once("dialog", (dialog) => dialog.accept());
  await superPage.locator(`button.btn-details-trigger[data-slug="${A}"]`).click();
  await superPage.locator('[data-tenant-tab="platform"]').click();
  await superPage.locator("#ft-m-disable").click();
  await expect(superPage.locator("#ft-m-state")).toContainText("غير مفعّل");
});
