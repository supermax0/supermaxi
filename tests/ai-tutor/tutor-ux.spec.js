import fs from "node:fs";
import { test, expect } from "@playwright/test";

/**
 * Browser E2E for Finora AI Tutor: feature gating + unified launcher + onboarding + the
 * `doctor.create` reference tutorial (smart card, spotlight, back, reconcile, dependency, mobile).
 * Needs: running server (PLAYWRIGHT_BASE_URL), two clinic tenants, a Super Admin and
 * E2E_TUTOR_CREDS=<json written by scripts/provision_tutor_e2e.py setup>.
 * Run: set PW_HEADLESS=1 && npx playwright test tests/ai-tutor --workers=1
 */
const CREDS = JSON.parse(fs.readFileSync(process.env.E2E_TUTOR_CREDS, "utf-8"));
const [A, B] = ["tutor-e2e-a", "tutor-e2e-b"];
const SHOT = process.env.E2E_SHOTS || "tests/_artifacts/tutor";
const BASE = process.env.PLAYWRIGHT_BASE_URL;

test.use({ channel: "msedge" });
test.describe.configure({ mode: "serial" });

const CARD = '[data-tutor-ui="card"]';
const ROOT = "#finora-tutor-root";
const FAB = "#finoraAiFab";

const card = (page) => page.locator(CARD);
const next = (page) => page.locator('[data-tutor-action="next"]');
const settled = (page) => expect(card(page)).not.toHaveClass(/is-transitioning/, { timeout: 15_000 });

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

async function setFeature(page, slug, enable) {
  await page.goto("/superadmin/tenants");
  page.once("dialog", (dialog) => dialog.accept());
  await page.locator(`button.btn-details-trigger[data-slug="${slug}"]`).click();
  await page.locator('[data-tenant-tab="platform"]').click();
  await page.locator(enable ? "#ft-m-enable" : "#ft-m-disable").click();
  await expect(page.locator("#ft-m-state")).toContainText(enable ? "مفعّل" : "غير مفعّل");
}

async function apiStatus(page) {
  return page.evaluate(async () => {
    const res = await fetch("/api/clinic/ai-tutor/status", { credentials: "same-origin" });
    return { status: res.status, body: await res.json().catch(() => null) };
  });
}

async function expectNoTutor(page, label) {
  await page.goto("/clinics/");
  await expect(page.locator(ROOT)).toHaveCount(0);
  expect(await page.locator('script[src*="ai-tutor"]').count(), `${label}: no tutor script`).toBe(0);
  const res = await apiStatus(page);
  expect(res.status).toBe(403);
  expect(res.body).toEqual({ error: "FEATURE_NOT_ENABLED", feature: "clinic_ai_tutor" });
}

const boxOf = (page, selector) => page.locator(selector).first().boundingBox();
const intersects = (a, b) => a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;

/** The card never covers the target and stays inside the viewport (desktop floating mode). */
async function expectCardClearOf(page, selector, label) {
  await settled(page);
  const [c, t] = [await card(page).boundingBox(), await boxOf(page, selector)];
  const vp = page.viewportSize();
  expect(c && t, `${label}: boxes`).toBeTruthy();
  expect(intersects(c, t), `${label}: card covers target`).toBe(false);
  expect(c.x).toBeGreaterThanOrEqual(0);
  expect(c.y).toBeGreaterThanOrEqual(0);
  expect(c.x + c.width).toBeLessThanOrEqual(vp.width + 1);
  expect(c.y + c.height).toBeLessThanOrEqual(vp.height + 1);
  return card(page).getAttribute("data-tutor-side");
}

const spotlightOver = async (page, selector) => {
  await settled(page);
  const [box, target] = await Promise.all([boxOf(page, '[data-tutor-ui="spotlight"]'), boxOf(page, selector)]);
  expect(box && target).toBeTruthy();
  expect(Math.abs(box.x + box.width / 2 - (target.x + target.width / 2))).toBeLessThan(10);
  expect(Math.abs(box.y + box.height / 2 - (target.y + target.height / 2))).toBeLessThan(10);
};

/** One launcher only: open the existing assistant button, pick "تعلّم النظام", pick a lesson. */
async function openMenu(page) {
  // The FAB is clickable before the tutor module attaches; wait so the click reaches the unified menu.
  await page.waitForFunction(() => !!window.FinoraTutor?.launcher);
  await page.locator(FAB).click();
}

async function openHome(page) {
  await openMenu(page);
  await page.locator('[data-tutor-menu="learn"]').click();
  await expect(page.locator('[data-tutor-ui="home"]')).toBeVisible();
}

async function startTutorial(page, id = "doctor.create") {
  await page.goto("/clinics/");
  await expect(page.locator(FAB)).toBeVisible();
  await openHome(page);
  await page.locator(`[data-tutor-start="${id}"]`).click();
  await expect(card(page)).toBeVisible();
  await settled(page);
}

async function exitTutor(page) {
  await page.locator('[data-tutor-action="cancel"]').click();
  await page.locator('[data-tutor-action="confirm-end"]').click();
  await expect(card(page)).toBeHidden();
}

let ctxSuper;
let ctxA;
let ctxB;
let superPage;
let pageA;
let pageB;

const declineUpgradeConfirm = (p) => p.on("dialog", (dialog) => (dialog.message().includes("وضع العيادة") ? dialog.dismiss() : dialog.accept()));

test.beforeAll(async ({ browser }) => {
  ctxSuper = await browser.newContext({ baseURL: BASE, locale: "ar" });
  ctxA = await browser.newContext({ baseURL: BASE, locale: "ar" });
  ctxB = await browser.newContext({ baseURL: BASE, locale: "ar" });
  [superPage, pageA, pageB] = await Promise.all([ctxSuper.newPage(), ctxA.newPage(), ctxB.newPage()]);
  // The clinic form offers a multi-doctor upgrade confirm after saving: decline it.
  declineUpgradeConfirm(pageA);
  declineUpgradeConfirm(pageB);
  await Promise.all([superLogin(superPage), tenantLogin(pageA, A), tenantLogin(pageB, B)]);
});

test.afterAll(async () => {
  await Promise.all([ctxSuper, ctxA, ctxB].map((c) => c?.close()));
});

test("1. feature OFF: no tutor UI, API 403, and the assistant button works exactly as before", async () => {
  await superPage.goto("/superadmin/tenants");
  await superPage.screenshot({ path: `${SHOT}/01-superadmin-tenants.png` });
  await expectNoTutor(pageA, "A");
  await expectNoTutor(pageB, "B");
  await pageA.locator(FAB).click();
  await expect(pageA.locator("#finoraAiPanel")).toHaveClass(/is-open/); // straight to the assistant, no menu
  await pageA.locator(FAB).click();
  await expect(pageA.locator("#finoraAiPanel")).not.toHaveClass(/is-open/);
});

test("2. Super Admin enables A; one unified launcher (assistant + learn); onboarding welcome", async () => {
  await setFeature(superPage, A, true);
  await superPage.screenshot({ path: `${SHOT}/02-superadmin-enable-a.png` });
  await expectNoTutor(pageB, "B");
  expect((await apiStatus(pageA)).status).toBe(200);

  // First dashboard load: welcome card, with "first doctor" wording only if the clinic has no doctor.
  await pageA.goto("/clinics/");
  await expect(pageA.locator('[data-tutor-ui="welcome"]')).toBeVisible();
  await expect(pageA.locator('[data-tutor-ui="welcome"]')).toContainText("أهلاً بك في Finora Clinics");
  await expect(pageA.locator('[data-tutor-ui="welcome"] li').first()).toHaveText(/01\s+إضافة طبيب$/); // seeded clinic already has a doctor
  await pageA.screenshot({ path: `${SHOT}/03-onboarding-welcome.png` });
  await pageA.locator("#ftWelcomeForever").check();
  await pageA.locator('[data-tutor-action="welcome-later"]').click();
  await expect(pageA.locator('[data-tutor-ui="welcome"]')).toHaveCount(0);
  await pageA.reload();
  await expect(pageA.locator(FAB)).toBeVisible();
  await expect(pageA.locator('[data-tutor-ui="welcome"]')).toHaveCount(0); // stored: never again

  // Exactly one floating launcher; its menu offers both entries; the assistant keeps working.
  await expect(pageA.locator('[data-tutor-ui="launcher"]')).toHaveCount(0);
  await openMenu(pageA);
  await expect(pageA.locator('[data-tutor-ui="launcher-menu"] [data-tutor-menu]')).toHaveCount(2);
  await pageA.screenshot({ path: `${SHOT}/04-unified-launcher-menu.png` });
  await pageA.locator('[data-tutor-menu="assistant"]').click();
  await expect(pageA.locator("#finoraAiPanel")).toHaveClass(/is-open/);
  await pageA.locator(FAB).click(); // original toggle still closes the panel
  await expect(pageA.locator("#finoraAiPanel")).not.toHaveClass(/is-open/);
  await openHome(pageA);
  await expect(pageA.locator('[data-tutor-start="doctor.create"]')).toContainText("إضافة طبيب");
  await pageA.screenshot({ path: `${SHOT}/05-tutor-home.png` });
  await pageA.locator(`${ROOT} .ft-home__close`).click();
  await superPage.goto("/superadmin/tenants");
  await expect(superPage.locator(`tr[data-slug="${A}"] .ft-state-badge`)).toHaveText("ON");
  await expect(superPage.locator(`tr[data-slug="${B}"] .ft-state-badge`)).toHaveText("OFF");
});

test("3. reference tutorial 'إضافة طبيب': smart card, spotlight, one persistent card, real backend result", async () => {
  const name = `طبيب اختبار ${Date.now()}`;
  const username = `dr_e2e_${Date.now()}`;
  const sides = {};
  await startTutorial(pageA);

  // Step 1: dashboard -> sidebar entry. Click steps never offer "next"; no "back" on the first step.
  await expect(card(pageA)).toContainText("الأطباء والموظفون");
  await expect(card(pageA)).toContainText("1 / 14");
  await expect(next(pageA)).toHaveCount(0);
  await expect(pageA.locator('[data-tutor-action="back"]')).toHaveCount(0);
  await spotlightOver(pageA, '[data-finora-action="nav.doctors"]');
  sides.nav = await expectCardClearOf(pageA, '[data-finora-action="nav.doctors"]', "nav");
  await pageA.screenshot({ path: `${SHOT}/06-step1-sidebar-target.png` });
  await pageA.locator('[data-finora-action="nav.doctors"]').click();

  // Navigation: compact card, then it resumes on the new page exactly where the old one was.
  await pageA.waitForURL(/\/clinics\/staff/);
  await expect(card(pageA)).toContainText("إضافة طبيب وحساب");
  await settled(pageA);
  await pageA.evaluate(() => { document.querySelector('[data-tutor-ui="card"]').dataset.persist = "same-node"; });
  await spotlightOver(pageA, '[data-finora-action="doctor.create"]');
  sides.add = await expectCardClearOf(pageA, '[data-finora-action="doctor.create"]', "add");
  await pageA.screenshot({ path: `${SHOT}/07-step-add-button.png` });
  await pageA.locator('[data-finora-action="doctor.create"]').click();

  await expect(card(pageA)).toContainText("الاسم الكامل");
  await expect(next(pageA)).toBeDisabled();
  sides.name = await expectCardClearOf(pageA, '[data-finora-field="doctor.name"]', "name");
  await pageA.screenshot({ path: `${SHOT}/08-step-name-in-modal.png` });
  await pageA.locator('[data-finora-field="doctor.name"]').fill(name);
  await expect(next(pageA)).toBeEnabled();
  await next(pageA).click();

  await expect(card(pageA)).toContainText("رقم الهاتف اختياري");
  sides.phone = await expectCardClearOf(pageA, '[data-finora-field="doctor.phone"]', "phone");
  await next(pageA).click();

  await expect(card(pageA)).toContainText("اسم المستخدم");
  await expect(next(pageA)).toBeDisabled();
  await pageA.locator('[data-finora-field="doctor.username"]').fill(username);
  await expect(next(pageA)).toBeEnabled();
  await next(pageA).click();

  await expect(card(pageA)).toContainText("كلمة مرور");
  await pageA.locator('[data-finora-field="doctor.password"]').fill("short");
  await expect(next(pageA)).toBeDisabled();
  await pageA.locator('[data-finora-field="doctor.password"]').fill(`E2e!${Date.now()}`);
  await expect(next(pageA)).toBeEnabled();
  await next(pageA).click();

  await expect(card(pageA)).toContainText("اختصاص");
  await expect(next(pageA)).toBeEnabled(); // the real form pre-selects the first specialty
  await pageA.locator('[data-finora-field="doctor.specialty"]').first().uncheck();
  await expect(next(pageA)).toBeDisabled();
  await pageA.locator('[data-finora-field="doctor.specialty"]').first().check();
  await expect(next(pageA)).toBeEnabled();
  await next(pageA).click();

  await expect(card(pageA)).toContainText("رقم الإجازة");
  await next(pageA).click();
  await expect(card(pageA)).toContainText("الصلاحيات");
  sides.permissions = await expectCardClearOf(pageA, '[data-finora-section="doctor.permissions"]', "permissions");
  await next(pageA).click();

  await expect(card(pageA)).toContainText("اضغط «حفظ»");
  await expect(next(pageA)).toHaveCount(0);
  await spotlightOver(pageA, '[data-finora-action="doctor.save"]');
  sides.save = await expectCardClearOf(pageA, '[data-finora-action="doctor.save"]', "save");
  await pageA.screenshot({ path: `${SHOT}/09-step-save.png` });

  // Still the very same card element (never remounted between steps) and only one exists.
  expect(await pageA.locator(CARD).count()).toBe(1);
  expect(await card(pageA).getAttribute("data-persist")).toBe("same-node");

  await pageA.locator('[data-finora-action="doctor.save"]').click();
  await expect(card(pageA)).toContainText("اكتمل الدرس", { timeout: 25_000 });
  await expect(card(pageA)).toContainText("تأكدنا من ذلك داخل النظام");
  await expect(card(pageA)).toContainText("التالي المقترح");
  await settled(pageA);
  await pageA.screenshot({ path: `${SHOT}/10-completed.png` });

  const doctors = await pageA.evaluate(async () => (await (await fetch("/clinics/api/doctors")).json()).data);
  expect(doctors.some((d) => (d.full_name || d.name) === name)).toBe(true);
  const progress = await pageA.evaluate(async () => (await (await fetch("/api/clinic/ai-tutor/tutorials")).json()).tutorials);
  expect(progress.find((t) => t.id === "doctor.create").progress.status).toBe("completed");

  await pageA.locator('[data-tutor-action="end"]').click();
  await expect(card(pageA)).toBeHidden();
  await pageA.reload();
  await expect(card(pageA)).toBeHidden(); // completed tutorials do not resume
  fs.writeFileSync(`${SHOT}/placements.json`, JSON.stringify(sides, null, 2));
  expect(Object.values(sides).every((s) => ["left", "right", "top", "bottom", "safe", "dock"].includes(s))).toBe(true);
});

test("4. failed save keeps waiting and shows the backend error (duplicate username)", async () => {
  await startTutorial(pageA);
  await pageA.locator('[data-finora-action="nav.doctors"]').click();
  await pageA.waitForURL(/\/clinics\/staff/);
  await expect(card(pageA)).toContainText("إضافة طبيب وحساب");
  await pageA.locator('[data-finora-action="doctor.create"]').click();
  await expect(card(pageA)).toContainText("الاسم الكامل");
  await pageA.locator('[data-finora-field="doctor.name"]').fill("طبيب مكرر");
  await next(pageA).click();
  await expect(card(pageA)).toContainText("رقم الهاتف اختياري");
  await next(pageA).click();
  await expect(card(pageA)).toContainText("اسم المستخدم");
  await pageA.locator('[data-finora-field="doctor.username"]').fill(CREDS.tenants[A].username); // already taken
  await next(pageA).click();
  await expect(card(pageA)).toContainText("كلمة مرور");
  await pageA.locator('[data-finora-field="doctor.password"]').fill("Passw0rd!x");
  await next(pageA).click();
  for (const text of ["اختصاص", "رقم الإجازة", "الصلاحيات"]) {
    await expect(card(pageA)).toContainText(text);
    await next(pageA).click();
  }
  await expect(card(pageA)).toContainText("اضغط «حفظ»");
  await pageA.locator('[data-finora-action="doctor.save"]').click();
  await expect(card(pageA).locator(".ft-notice")).toBeVisible();
  await expect(card(pageA)).toContainText("اضغط «حفظ»"); // still on the save step
  await pageA.screenshot({ path: `${SHOT}/11-save-failed.png` });
  await exitTutor(pageA);
});

test("5. semantic Back: review only (no undo), not offered on the first step, then forward again", async () => {
  await startTutorial(pageA);
  await pageA.locator('[data-finora-action="nav.doctors"]').click();
  await pageA.waitForURL(/\/clinics\/staff/);
  await expect(card(pageA)).toContainText("إضافة طبيب وحساب");
  await pageA.locator('[data-finora-action="doctor.create"]').click();
  await expect(card(pageA)).toContainText("الاسم الكامل");
  await pageA.locator('[data-finora-field="doctor.name"]').fill("طبيب مراجعة");
  await next(pageA).click();
  await expect(card(pageA)).toContainText("رقم الهاتف اختياري");
  await expect(pageA.locator('[data-tutor-action="back"]')).toBeVisible();

  await pageA.locator('[data-tutor-action="back"]').click(); // -> name (review)
  await expect(card(pageA)).toContainText("مراجعة لخطوة سابقة");
  await expect(card(pageA)).toContainText("الاسم الكامل");
  await expect(pageA.locator('[data-finora-field="doctor.name"]')).toHaveValue("طبيب مراجعة"); // nothing undone
  await expect(next(pageA)).toBeEnabled();
  await pageA.screenshot({ path: `${SHOT}/12-back-review.png` });
  await next(pageA).click();
  await expect(card(pageA)).toContainText("رقم الهاتف اختياري"); // back at the frontier, not a review any more
  await expect(card(pageA)).not.toContainText("مراجعة لخطوة سابقة");
  await exitTutor(pageA);
  await pageA.reload();
});

test("6. reconcile: acting before the engine attaches skips only what the real UI proves done", async () => {
  // Start the lesson and walk to the staff page so progress points at "click add doctor".
  await startTutorial(pageA);
  await pageA.locator('[data-finora-action="nav.doctors"]').click();
  await pageA.waitForURL(/\/clinics\/staff/);
  await expect(card(pageA)).toContainText("إضافة طبيب وحساب");
  await settled(pageA);

  // Fresh page whose tutor boot is held back: act like an impatient user (open the form), then release it.
  const impatient = await ctxA.newPage();
  declineUpgradeConfirm(impatient);
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  await impatient.route("**/api/clinic/ai-tutor/active", async (route) => {
    await gate;
    await route.continue();
  });
  await impatient.goto("/clinics/staff");
  await impatient.locator('[data-finora-action="doctor.create"]').click(); // before the tutor is attached
  await expect(impatient.locator('[data-finora-section="staff.form"]')).toBeVisible();
  release();
  await expect(card(impatient)).toContainText("الاسم الكامل", { timeout: 15_000 }); // jumped over "click add" + "wait modal"
  await settled(impatient);
  await impatient.screenshot({ path: `${SHOT}/13-reconciled-at-name.png` });

  // Never over-skip: "save" was NOT assumed done (nothing was saved), and the server agrees.
  const verified = await impatient.evaluate(async () => (await (await fetch("/api/clinic/ai-tutor/tutorials/doctor.create/verify", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ validator: "doctor.created_since_start" }),
  })).json()).verified);
  expect(verified).toBe(false);
  await impatient.unroute("**/api/clinic/ai-tutor/active");
  await exitTutor(impatient);
  await impatient.close();
  await pageA.reload();
});

test("7. leaving the lesson page shows the recovery card and can return", async () => {
  await startTutorial(pageA);
  await pageA.locator('[data-finora-action="nav.doctors"]').click();
  await pageA.waitForURL(/\/clinics\/staff/);
  await expect(card(pageA)).toContainText("إضافة طبيب وحساب");
  await pageA.goto("/clinics/patients");
  await expect(card(pageA)).toContainText("ابتعدت عن خطوة التعليم الحالية");
  await pageA.screenshot({ path: `${SHOT}/14-left-page.png` });
  await pageA.locator('[data-tutor-action="return"]').click();
  await pageA.waitForURL(/\/clinics\/staff/);
  await expect(card(pageA)).toContainText("إضافة طبيب وحساب");
});

test("8. wrong control gently shakes the card; lost target offers a safe rewind", async () => {
  await settled(pageA);
  await pageA.locator('[data-staff-view="employees"]').click(); // a different control
  await expect(card(pageA).locator(".ft-notice")).toContainText("مو هذا الزر");
  await pageA.locator('[data-finora-action="doctor.create"]').click();
  await expect(card(pageA)).toContainText("الاسم الكامل");
  await pageA.reload(); // modal disappears, but the saved step is still "name"
  await expect(card(pageA)).toContainText("تعذر العثور على العنصر المطلوب في هذه النسخة", { timeout: 15_000 });
  await pageA.screenshot({ path: `${SHOT}/15-target-missing.png` });
  await pageA.locator('[data-tutor-action="rewind"]').click();
  await expect(card(pageA)).toContainText("إضافة طبيب وحساب");
  await exitTutor(pageA);
});

test("9. exit asks inside the card, Escape keeps going, place is saved and resumable from Tutor Home", async () => {
  await startTutorial(pageA);
  await pageA.locator('[data-finora-action="nav.doctors"]').click();
  await pageA.waitForURL(/\/clinics\/staff/);
  await expect(card(pageA)).toContainText("إضافة طبيب وحساب");
  await pageA.keyboard.press("Escape");
  await expect(card(pageA)).toContainText("راح نحفظ مكانك");
  await pageA.screenshot({ path: `${SHOT}/16-exit-confirm.png` });
  await pageA.keyboard.press("Escape"); // second Escape = keep going
  await expect(card(pageA)).toContainText("إضافة طبيب وحساب");
  await pageA.locator('[data-tutor-action="cancel"]').click();
  await pageA.locator('[data-tutor-action="confirm-end"]').click();
  await expect(card(pageA)).toBeHidden();

  await pageA.reload();
  await expect(card(pageA)).toBeHidden(); // paused tutorials never auto-resume
  await expect(pageA.locator('[data-tutor-ui="badge"]')).toBeVisible(); // but the launcher shows a badge
  await openHome(pageA);
  await pageA.locator("[data-tutor-continue]").click();
  await expect(card(pageA)).toContainText("إضافة طبيب وحساب"); // same place
  await expect(card(pageA)).toContainText("3 / 14");
});

test("10. minimize and pause keep the lesson place", async () => {
  await pageA.locator('[data-tutor-action="minimize"]').click();
  await expect(card(pageA)).toHaveClass(/is-min/);
  await expect(pageA.locator('[data-tutor-ui="spotlight"]')).toBeVisible(); // highlight stays
  await pageA.screenshot({ path: `${SHOT}/17-minimized.png` });
  await pageA.locator('[data-tutor-action="expand"]').click();
  await expect(card(pageA)).not.toHaveClass(/is-min/);
  await pageA.locator('[data-tutor-action="pause"]').click();
  await expect(card(pageA)).toContainText("التعليم متوقف");
  await expect(pageA.locator('[data-tutor-ui="spotlight"]')).toBeHidden();
  await pageA.screenshot({ path: `${SHOT}/18-paused.png` });
  await pageA.locator('[data-tutor-action="resume"]').click();
  await expect(card(pageA)).toContainText("إضافة طبيب وحساب");
  await exitTutor(pageA);
});

test("11. dependency tutorial: missing specialty -> specialty.create -> automatic return to doctor.create", async () => {
  // Deactivate every specialty through the real API so the clinic has none.
  await pageA.goto("/clinics/");
  const deactivated = await pageA.evaluate(async () => {
    const rows = (await (await fetch("/clinics/api/specialties")).json()).data;
    const changed = [];
    for (const s of rows.filter((r) => r.is_active)) {
      const res = await fetch(`/clinics/api/specialties/${s.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ is_active: false }) });
      if (res.ok) changed.push(s.id);
    }
    return changed;
  });
  expect(deactivated.length).toBeGreaterThan(0);
  try {
    await startTutorial(pageA);
    await expect(card(pageA)).toContainText("قبل إضافة الطبيب نحتاج نضيف اختصاص واحد على الأقل");
    await expect(pageA.locator('[data-tutor-action="dependency_start"]')).toHaveText("إضافة اختصاص الآن");
    await pageA.screenshot({ path: `${SHOT}/19-dependency-card.png` });
    await pageA.locator('[data-tutor-action="dependency_start"]').click();

    // specialty.create runs (same card), then returns to doctor.create by itself.
    await expect(card(pageA)).toContainText("الاختصاصات");
    await pageA.locator('[data-finora-action="nav.specialties"]').click();
    await pageA.waitForURL(/\/clinics\/specialties/);
    await expect(card(pageA)).toContainText("إضافة اختصاص");
    await pageA.locator('[data-finora-action="specialty.create"]').click();
    await expect(card(pageA)).toContainText("اسم الاختصاص");
    await pageA.locator('[data-finora-field="specialty.name"]').fill(`اختصاص اختبار ${Date.now()}`);
    await next(pageA).click();
    await expect(card(pageA)).toContainText("الرمز اختياري");
    await next(pageA).click();
    await expect(card(pageA)).toContainText("اضغط «حفظ»");
    await pageA.screenshot({ path: `${SHOT}/20-specialty-save.png` });
    await pageA.locator('[data-finora-action="specialty.save"]').click();

    // Back in the parent lesson at the point where the dependency was found.
    await expect(card(pageA)).toContainText("الأطباء والموظفون", { timeout: 30_000 });
    await expect(card(pageA)).toContainText("1 / 14");
    const active = await pageA.evaluate(async () => (await (await fetch("/api/clinic/ai-tutor/active")).json()).active);
    expect(active.tutorial.id).toBe("doctor.create");
    await pageA.screenshot({ path: `${SHOT}/21-returned-to-parent.png` });
    await exitTutor(pageA);
  } finally {
    await pageA.evaluate(async (ids) => {
      for (const id of ids) {
        await fetch(`/clinics/api/specialties/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ is_active: true }) });
      }
    }, deactivated);
  }
});

test("12. mobile: bottom sheet, drawer reveal, target stays visible above the sheet", async ({ browser }) => {
  const ctx = await browser.newContext({ baseURL: BASE, locale: "ar", viewport: { width: 390, height: 800 } });
  const page = await ctx.newPage();
  try {
    await tenantLogin(page, A);
    await page.goto("/clinics/");
    await openHome(page);
    const t0 = Date.now();
    await page.locator('[data-tutor-start="doctor.create"]').click();
    // The nav target hides in the closed drawer: the resolver reveals it at once (was ~4.9 s with a fixed 2.5 s wait).
    await expect(card(page)).toContainText("الأطباء والموظفون");
    const startMs = Date.now() - t0;
    console.log(`[perf] mobile tutorial start -> first card: ${startMs} ms`);
    expect(startMs).toBeLessThan(2500);
    await settled(page);
    await expect(card(page)).toHaveClass(/is-sheet/);
    const [c, t] = [await card(page).boundingBox(), await boxOf(page, '[data-finora-action="nav.doctors"]')];
    const vp = page.viewportSize();
    expect(Math.round(c.y + c.height)).toBeGreaterThanOrEqual(vp.height - 2); // docked to the bottom edge
    expect(c.height).toBeLessThanOrEqual(vp.height * 0.43);
    expect(t.y + t.height).toBeLessThanOrEqual(c.y + 1); // target is not hidden behind the sheet
    expect(intersects(c, t)).toBe(false);
    await page.screenshot({ path: `${SHOT}/22-mobile-bottom-sheet.png` });
    await exitTutor(page);
  } finally {
    await ctx.close();
  }
});

test("13. reduced motion: no movement animations, ring/pulse disabled, same behaviour", async ({ browser }) => {
  const ctx = await browser.newContext({ baseURL: BASE, locale: "ar", reducedMotion: "reduce" });
  const page = await ctx.newPage();
  try {
    await tenantLogin(page, A);
    await startTutorial(page);
    await expect(card(page)).toContainText("الأطباء والموظفون");
    const info = await page.evaluate(() => ({
      ring: getComputedStyle(document.querySelector(".ft-ring")).animationName,
      pulse: getComputedStyle(document.querySelector(".ft-pulse")).animationName,
      cardAnimations: document.querySelector('[data-tutor-ui="card"]').getAnimations().length,
      spotAnimations: document.querySelector('[data-tutor-ui="spotlight"]').getAnimations().length,
    }));
    expect(info.ring).toBe("none");
    expect(info.pulse).toBe("none");
    expect(info.cardAnimations).toBe(0);
    expect(info.spotAnimations).toBe(0);
    await exitTutor(page);
  } finally {
    await ctx.close();
  }
});

test("13b. motion: smooth auto-scroll, spotlight morph and card slide; one card, no flicker, no layout shift", async () => {
  await startTutorial(pageA);
  await pageA.locator('[data-finora-action="nav.doctors"]').click();
  await pageA.waitForURL(/\/clinics\/staff/);
  await expect(card(pageA)).toContainText("إضافة طبيب وحساب");
  await pageA.locator('[data-finora-action="doctor.create"]').click();
  await expect(card(pageA)).toContainText("الاسم الكامل");
  await pageA.locator('[data-finora-field="doctor.name"]').fill("طبيب حركة");
  await next(pageA).click();
  await expect(card(pageA)).toContainText("رقم الهاتف اختياري");
  await next(pageA).click();
  await expect(card(pageA)).toContainText("اسم المستخدم");
  await pageA.locator('[data-finora-field="doctor.username"]').fill(`dr_motion_${Date.now()}`);
  await next(pageA).click();
  await expect(card(pageA)).toContainText("كلمة مرور");
  await pageA.locator('[data-finora-field="doctor.password"]').fill(`E2e!${Date.now()}`);
  await next(pageA).click();
  await expect(card(pageA)).toContainText("اختصاص");
  await next(pageA).click();
  await expect(card(pageA)).toContainText("رقم الإجازة");
  await settled(pageA);

  // Sample every animation frame while the tutor moves from "license" to the far-away permissions section.
  await pageA.evaluate(() => {
    const cardEl = document.querySelector('[data-tutor-ui="card"]');
    const spot = document.querySelector('[data-tutor-ui="spotlight"]');
    const target = document.querySelector('[data-finora-section="doctor.permissions"]');
    let scroller = target.parentElement;
    while (scroller && scroller.scrollHeight <= scroller.clientHeight + 1) scroller = scroller.parentElement;
    window.__samples = [];
    window.__shift = 0;
    window.__shiftSources = [];
    new PerformanceObserver((list) => {
      for (const e of list.getEntries()) {
        if (e.hadRecentInput) continue;
        // The spotlight deliberately morphs its own box (width/height) on an isolated fixed layer.
        // Only shifts of the PAGE's elements count as layout shift.
        const pageSources = (e.sources || []).filter((src) => src.node && !src.node.closest?.("#finora-tutor-root"));
        if (!pageSources.length) { window.__tutorUiShift = (window.__tutorUiShift || 0) + e.value; continue; }
        window.__shift += e.value;
        window.__shiftSources.push(`${e.value.toFixed(3)} ${pageSources.map((src) => `${src.node.nodeName}.${src.node.className}`).join("|")}`);
      }
    }).observe({ type: "layout-shift", buffered: false });
    const t0 = performance.now();
    cardEl.dataset.motionProbe = "1";
    const tick = () => {
      const now = performance.now();
      const cs = getComputedStyle(cardEl);
      const r = spot.getBoundingClientRect();
      window.__samples.push({
        t: Math.round(now - t0), card: cs.transform, opacity: cs.opacity, hidden: cardEl.hidden || cs.visibility === "hidden",
        spot: `${Math.round(r.x)},${Math.round(r.y)},${Math.round(r.width)},${Math.round(r.height)}`,
        scroll: scroller ? Math.round(scroller.scrollTop) : 0,
        sameNode: document.querySelector('[data-tutor-ui="card"]') === cardEl,
      });
      if (now - t0 < 1400) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  });
  await next(pageA).click();
  await expect(card(pageA)).toContainText("الصلاحيات");
  await pageA.waitForTimeout(1500);
  const result = await pageA.evaluate(() => ({ samples: window.__samples, shift: window.__shift, sources: window.__shiftSources, tutorUiShift: window.__tutorUiShift || 0 }));
  const s = result.samples;
  const distinct = (key) => new Set(s.map((x) => x[key])).size;
  expect(s.length).toBeGreaterThan(20);
  expect(s.every((x) => x.sameNode), "same card node the whole time").toBe(true);
  expect(s.every((x) => !x.hidden), "card never hidden (no flicker)").toBe(true);
  expect(Math.min(...s.map((x) => Number(x.opacity))), "card itself never fades out between steps").toBeGreaterThan(0.99);
  expect(distinct("spot"), "spotlight morphs through intermediate boxes").toBeGreaterThan(4);
  expect(distinct("scroll"), "auto-scroll is gradual, not a jump").toBeGreaterThan(3);
  expect(result.shift, `no visible layout shift: ${JSON.stringify(result.sources)}`).toBeLessThan(0.1);
  const gaps = s.slice(1).map((x, i) => x.t - s[i].t);
  fs.writeFileSync(`${SHOT}/motion-probe.json`, JSON.stringify({
    frames: s.length, distinctSpot: distinct("spot"), distinctScroll: distinct("scroll"), distinctCardTransform: distinct("card"),
    maxFrameGapMs: Math.max(...gaps), pageLayoutShift: result.shift, tutorOverlayShift: result.tutorUiShift,
  }, null, 2));
  await pageA.screenshot({ path: `${SHOT}/25-motion-after-scroll.png` });
  await exitTutor(pageA);
});

test("14. disabling closes a running tutor, restores the plain assistant button; B unaffected", async () => {
  await startTutorial(pageA);
  await expect(card(pageA)).toBeVisible();
  await setFeature(superPage, A, false);
  await superPage.screenshot({ path: `${SHOT}/23-superadmin-disabled.png` });
  // The next backend call the tutor makes sees FEATURE_NOT_ENABLED and removes everything.
  await pageA.locator('[data-finora-action="nav.doctors"]').click();
  await pageA.waitForURL(/\/clinics\/staff/);
  await expectNoTutor(pageA, "A after disable");
  await expectNoTutor(pageB, "B");
  await pageA.locator(FAB).click();
  await expect(pageA.locator("#finoraAiPanel")).toHaveClass(/is-open/); // no menu, original behaviour
  await pageA.screenshot({ path: `${SHOT}/24-a-after-disable.png` });
});
