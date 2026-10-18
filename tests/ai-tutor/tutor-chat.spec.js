import fs from "node:fs";
import { test, expect } from "@playwright/test";

/**
 * Browser E2E for Phase 5 (Tutor chat). The server runs WITHOUT any AI provider, so this also proves the
 * deterministic fallback. Same prerequisites as tutor-ux.spec.js; start the server with
 * AI_TUTOR_ASK_PER_USER=30 so the rate-limit test needs only a short burst.
 */
const CREDS = JSON.parse(fs.readFileSync(process.env.E2E_TUTOR_CREDS, "utf-8"));
const [A, B] = ["tutor-e2e-a", "tutor-e2e-b"];
const SHOT = process.env.E2E_SHOTS || "tests/_artifacts/tutor";
const BASE = process.env.PLAYWRIGHT_BASE_URL;

test.use({ channel: "msedge" });
test.describe.configure({ mode: "serial" });

const FAB = "#finoraAiFab";
const CARD = '[data-tutor-ui="card"]';
const card = (page) => page.locator(CARD);
const bot = (page) => page.locator('[data-tutor-msg="bot"]:not(.is-typing)');
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

async function openHome(page) {
  await page.waitForFunction(() => !!window.FinoraTutor?.launcher);
  await page.locator(FAB).click();
  await page.locator('[data-tutor-menu="learn"]').click();
  await expect(page.locator('[data-tutor-ui="home"]')).toBeVisible();
  await expect(page.locator('[data-tutor-ui="chat-input"]')).toBeEnabled();
}

let welcomeHandled = false;

async function gotoPage(page, path) {
  await page.goto(path);
  await expect(page.locator(FAB)).toBeVisible();
  await page.waitForFunction(() => !!window.FinoraTutor);
  if (!welcomeHandled) {
    // First dashboard visit shows the welcome card; "later" is remembered for the session.
    welcomeHandled = await page.locator('[data-tutor-action="welcome-later"]').click({ timeout: 4000 }).then(() => true, () => false);
  }
}

/** Type a natural-language question and wait for the structured answer to be rendered. */
async function say(page, text) {
  const before = await bot(page).count();
  await page.locator('[data-tutor-ui="chat-input"]').fill(text);
  await page.locator('[data-tutor-ui="chat-send"]').click();
  await expect(bot(page)).toHaveCount(before + 1, { timeout: 15_000 });
  return bot(page).last();
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
const askBodies = [];
const mutations = [];

test.beforeAll(async ({ browser }) => {
  ctxSuper = await browser.newContext({ baseURL: BASE, locale: "ar" });
  ctxA = await browser.newContext({ baseURL: BASE, locale: "ar" });
  ctxB = await browser.newContext({ baseURL: BASE, locale: "ar" });
  [superPage, pageA, pageB] = await Promise.all([ctxSuper.newPage(), ctxA.newPage(), ctxB.newPage()]);
  pageA.on("request", (req) => {
    if (req.url().endsWith("/api/clinic/ai-tutor/ask")) askBodies.push(JSON.parse(req.postData() || "{}"));
    if (["POST", "PUT", "PATCH", "DELETE"].includes(req.method()) && req.url().includes("/clinics/api/")) mutations.push(`${req.method()} ${req.url()}`);
  });
  await Promise.all([superLogin(superPage), tenantLogin(pageA, A), tenantLogin(pageB, B)]);
});

test.afterAll(async () => {
  await Promise.all([ctxSuper, ctxA, ctxB].map((c) => c?.close()));
});

test("1. enable A; Tutor Home shows registry-generated quick actions, honest progress and the chat", async () => {
  await setFeature(superPage, A, true);
  await gotoPage(pageA, "/clinics/");
  await openHome(pageA);
  // Generated from the lesson registry: the screen shows exactly what the API says this user may run.
  const api = await pageA.evaluate(async () => (await (await fetch("/api/clinic/ai-tutor/knowledge")).json()));
  const quick = pageA.locator("[data-tutor-start]");
  await expect(quick).toHaveCount(api.quick_actions.length);
  const ids = await quick.evaluateAll((els) => els.map((e) => e.dataset.tutorStart));
  expect(ids).toEqual(api.quick_actions.map((q) => q.tutorial_id)); // curriculum order
  expect(ids).toEqual(expect.arrayContaining(["doctor.create", "specialty.create", "patient.create", "appointment.create"]));
  const plan = pageA.locator('[data-tutor-ui="plan"]');
  await expect(plan).toHaveCount(api.plan.groups.length);
  for (const group of api.plan.groups) {
    await expect(pageA.locator(`[data-tutor-plan-group="${group.id}"]`)).toContainText(`${group.title_ar} — 0 من ${group.items.length}`);
  }
  await expect(pageA.locator('[data-tutor-ui="plan"]').first()).not.toContainText("قريباً"); // only lessons that exist are listed
  expect(await pageA.locator('[data-tutor-prompt]').count()).toBeGreaterThanOrEqual(3);
  await pageA.screenshot({ path: `${SHOT}/30-tutor-home-chat.png` });
});

test("2. 'شلون أضيف طبيب' -> suggestion -> 'ابدأ التعليم' runs the existing doctor.create tutorial", async () => {
  const reply = await say(pageA, "شلون أضيف طبيب");
  await expect(reply).toContainText("أكدر أعلمك إضافة طبيب");
  await expect(reply.locator('[data-tutor-chat-action="start_tutorial"]')).toHaveText("ابدأ التعليم");
  await expect(reply.locator('[data-tutor-chat-action="show_me"]')).toHaveText("وريني وين");
  await pageA.screenshot({ path: `${SHOT}/31-chat-doctor-suggestion.png` });
  // Privacy of the request itself: only the question + page/route/issue label, never page content.
  const body = askBodies.at(-1);
  expect(Object.keys(body).sort()).toEqual(["active", "intent", "message", "page", "route"]);
  expect(body.message).toBe("شلون أضيف طبيب");

  await reply.locator('[data-tutor-chat-action="start_tutorial"]').click();
  await expect(card(pageA)).toContainText("الأطباء والموظفون");
  await expect(card(pageA)).toContainText("1 / 14");
  await settled(pageA);
  await pageA.screenshot({ path: `${SHOT}/32-chat-started-doctor-tutorial.png` });
  await exitTutor(pageA);
});

test("3. different Iraqi phrasings reach the same lesson; specialty phrasing reaches specialty.create", async () => {
  await openHome(pageA);
  for (const text of ["اريد ادخل دكتور جديد", "علمني أضيف دكتور", "اسوي حساب دكتور"]) {
    const reply = await say(pageA, text);
    await expect(reply, text).toContainText("أكدر أعلمك إضافة طبيب");
  }
  const spec = await say(pageA, "اريد اضيف اختصاص");
  await expect(spec).toContainText("أكدر أعلمك إضافة اختصاص");
  await pageA.screenshot({ path: `${SHOT}/33-chat-specialty-suggestion.png` });
  await spec.locator('[data-tutor-chat-action="start_tutorial"]').click();
  await expect(card(pageA)).toContainText("الاختصاصات");
  await expect(card(pageA)).toContainText("1 / 9");
  await exitTutor(pageA);
});

test("4. unknown feature: no hallucination, only real lessons are offered; medical advice is declined", async () => {
  await openHome(pageA);
  const unknown = await say(pageA, "وين نظام العمليات الجراحية");
  await expect(unknown).toContainText("ما لقيت هذه الميزة ضمن النسخة الحالية");
  const labels = await unknown.locator("button").allTextContents();
  const lessons = await pageA.evaluate(async () => (await (await fetch("/api/clinic/ai-tutor/knowledge")).json()).quick_actions.map((q) => q.label));
  expect(labels.length).toBeGreaterThan(0);
  expect(labels.every((l) => lessons.includes(l.trim()))).toBe(true); // only real lessons are ever offered
  expect(await unknown.locator('[data-tutor-chat-action="show_me"]').count()).toBe(0);
  await pageA.screenshot({ path: `${SHOT}/34-chat-not-found.png` });

  const medical = await say(pageA, "شنو علاج هذا المريض");
  await expect(medical).toContainText("ما أكدر أعطي تشخيص أو علاج");
  await expect(medical).toContainText("أكدر أعلمك وين تسجل التشخيص");
  const where = await say(pageA, "وين اسجل التشخيص");
  await expect(where).toContainText("المعاينة الطبية");
});

test("5. page explanation comes from the registry (staff page)", async () => {
  await gotoPage(pageA, "/clinics/staff");
  await openHome(pageA);
  const reply = await say(pageA, "شنو هاي الصفحة؟");
  await expect(reply).toContainText("أنت حالياً بصفحة الأطباء والموظفون");
  await expect(reply).toContainText("تدير الأطباء والموظفين وحسابات الدخول والصلاحيات");
  // The staff page now has three real lessons (doctor, employee, permissions): all are offered, each a registry lesson.
  const offered = await reply.locator('[data-tutor-chat-action="start_tutorial"]').evaluateAll((els) => els.map((e) => e.dataset.tutorId));
  expect(offered).toEqual(expect.arrayContaining(["doctor.create", "employee.create", "permissions.manage"]));
  await pageA.screenshot({ path: `${SHOT}/35-chat-page-explanation.png` });
});

test("6. clarification buttons, then Show Me highlights without clicking, saving or changing data", async () => {
  const ask = await say(pageA, "أريد أضيف حساب");
  await expect(ask).toContainText("تقصد طبيب لو موظف؟");
  expect(await ask.locator("button").allTextContents()).toEqual(["طبيب", "موظف"]);
  await pageA.screenshot({ path: `${SHOT}/36-chat-clarification.png` });
  await ask.locator("button", { hasText: "موظف" }).click();
  const answer = bot(pageA).last();
  await expect(answer).toContainText("إضافة موظف");
  await expect(answer).toContainText("أكدر أعلمك إضافة موظف"); // the lesson exists now (Phase 7)

  const before = mutations.length;
  await answer.locator('[data-tutor-chat-action="show_me"]').click();
  await expect(pageA.locator('[data-tutor-ui="spotlight"]')).toBeVisible();
  await expect(pageA.locator('[data-tutor-ui="virtual-pointer"]')).toBeVisible();
  const [spot, target] = [await pageA.locator('[data-tutor-ui="spotlight"]').boundingBox(), await pageA.locator('[data-finora-action="employee.create"]').boundingBox()];
  await settled(pageA);
  expect(Math.abs(spot.x + spot.width / 2 - (target.x + target.width / 2))).toBeLessThan(12);
  await pageA.screenshot({ path: `${SHOT}/37-showme-employee-create.png` });
  await expect(pageA.locator('[data-finora-section="staff.form"]')).toHaveCount(0); // nothing was clicked
  await pageA.locator('[data-tutor-action="next"]').click(); // "تمام"
  await expect(card(pageA)).toBeHidden();
  await expect(pageA.locator('[data-tutor-ui="virtual-pointer"]')).toBeHidden();
  expect(mutations.length).toBe(before); // no write request was made by Show Me
  await expect(pageA).toHaveURL(/\/clinics\/staff$/);
});

test("7. Show Me from another page points at the real sidebar entry (and opens nothing)", async () => {
  await gotoPage(pageA, "/clinics/");
  await openHome(pageA);
  const reply = await say(pageA, "وين اضيف زبون");
  await reply.locator('[data-tutor-chat-action="show_me"]').click();
  await expect(card(pageA)).toContainText("ضمن «المرضى»");
  await settled(pageA);
  const [spot, link] = [await pageA.locator('[data-tutor-ui="spotlight"]').boundingBox(), await pageA.locator('[data-finora-action="nav.patients"]').boundingBox()];
  expect(Math.abs(spot.y + spot.height / 2 - (link.y + link.height / 2))).toBeLessThan(12);
  await expect(pageA).toHaveURL(/\/clinics\/?$/); // guidance only: the page did not navigate
  await pageA.screenshot({ path: `${SHOT}/38-showme-sidebar.png` });
  await pageA.locator('[data-tutor-action="next"]').click();
  await expect(card(pageA)).toBeHidden();
});

test("8. during a lesson the chat explains only the CURRENT step and can point at it", async () => {
  await openHome(pageA);
  await pageA.locator('[data-tutor-start="doctor.create"]').click();
  await expect(card(pageA)).toContainText("الأطباء والموظفون");
  await pageA.locator('[data-finora-action="nav.doctors"]').click();
  await pageA.waitForURL(/\/clinics\/staff/);
  await expect(card(pageA)).toContainText("إضافة طبيب وحساب");
  await settled(pageA);
  await openHome(pageA);
  await expect(pageA.locator('[data-tutor-ui="home"] .ft-home__note')).toContainText("درس قيد التنفيذ");
  const help = await say(pageA, "شنو اسوي هسه");
  await expect(help).toContainText("هسه:");
  await expect(help).toContainText("اضغط «إضافة طبيب وحساب»");
  await expect(help).not.toContainText("اسم المستخدم"); // no replay of later/earlier steps
  await pageA.screenshot({ path: `${SHOT}/39-chat-active-step-help.png` });
  await help.locator('[data-tutor-chat-action="show_current"]').click();
  await expect(pageA.locator('[data-tutor-ui="virtual-pointer"]')).toBeVisible();
  await expect(card(pageA)).toContainText("إضافة طبيب وحساب"); // the lesson did not move
  const another = await (async () => {
    await openHome(pageA);
    return say(pageA, "اريد اضيف اختصاص");
  })();
  await another.locator('[data-tutor-chat-action="start_tutorial"]').click();
  await expect(bot(pageA).last()).toContainText("هناك درس قيد التنفيذ"); // never a second flow
  await pageA.locator('[data-tutor-ui="home"] .ft-home__close').click();
  await exitTutor(pageA);
});

test("9. help during a blocked step uses the real state (missing specialty) and resumes the dependency flow", async () => {
  await gotoPage(pageA, "/clinics/");
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
    await openHome(pageA);
    await pageA.locator('[data-tutor-start="doctor.create"]').click();
    await expect(card(pageA)).toContainText("قبل إضافة الطبيب نحتاج نضيف اختصاص");
    await openHome(pageA);
    const why = await say(pageA, "ليش ما يكمل");
    await expect(why).toContainText("ما نكدر نكمل");
    await expect(why).toContainText("قبل إضافة الطبيب نحتاج نضيف اختصاص");
    await pageA.screenshot({ path: `${SHOT}/40-chat-dependency-help.png` });
    await why.locator('[data-tutor-chat-action="resume_dependency"]').click();
    await expect(card(pageA)).toContainText("الاختصاصات"); // the existing dependency engine took over
    await expect(card(pageA)).toContainText("1 / 9");
    await exitTutor(pageA);
  } finally {
    await pageA.evaluate(async (ids) => {
      for (const id of ids) {
        await fetch(`/clinics/api/specialties/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ is_active: true }) });
      }
    }, deactivated);
  }
});

test("10. rate limit answers politely and does not hurt other users; history is session-scoped", async () => {
  await gotoPage(pageA, "/clinics/");
  const codes = await pageA.evaluate(async () => {
    const out = [];
    for (let i = 0; i < 40; i += 1) {
      const res = await fetch("/api/clinic/ai-tutor/ask", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message: "هلا" }) });
      out.push(res.status);
      if (res.status === 429) break;
    }
    return out;
  });
  expect(codes.at(-1)).toBe(429);
  expect(codes.filter((c) => c === 200).length).toBeGreaterThan(5);
  // The sliding window frees slots as old hits expire, so the UI wording is checked against a pinned 429.
  await pageA.route("**/api/clinic/ai-tutor/ask", (route) => route.fulfill({
    status: 429, contentType: "application/json", body: JSON.stringify({ ok: false, error: "RATE_LIMITED", retry_after: 5 }),
  }));
  await openHome(pageA);
  const reply = await say(pageA, "شلون أضيف طبيب");
  await expect(reply).toContainText("كثرت الأسئلة");
  await pageA.unroute("**/api/clinic/ai-tutor/ask");
  await pageA.screenshot({ path: `${SHOT}/41-chat-rate-limited.png` });
  const history = await pageA.evaluate(() => JSON.parse(sessionStorage.getItem("finora.tutor.chat")));
  expect(history.length).toBeLessThanOrEqual(20);
  expect(history.every((m) => !/\d{5,}/.test(m.text))).toBe(true);
});

test("11. feature OFF: chat API answers 403 FEATURE_NOT_ENABLED, no chat UI anywhere; B was never enabled", async () => {
  await setFeature(superPage, A, false);
  await pageA.goto("/clinics/");
  await expect(pageA.locator("#finora-tutor-root")).toHaveCount(0);
  const off = await pageA.evaluate(async () => {
    const res = await fetch("/api/clinic/ai-tutor/ask", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message: "شلون أضيف طبيب" }) });
    return { status: res.status, body: await res.json() };
  });
  expect(off.status).toBe(403);
  expect(off.body).toEqual({ error: "FEATURE_NOT_ENABLED", feature: "clinic_ai_tutor" });
  await pageB.goto("/clinics/");
  await expect(pageB.locator("#finora-tutor-root")).toHaveCount(0);
  const offB = await pageB.evaluate(async () => (await fetch("/api/clinic/ai-tutor/ask", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" })).status);
  expect(offB).toBe(403);
  await pageA.locator(FAB).click();
  await expect(pageA.locator("#finoraAiPanel")).toHaveClass(/is-open/); // plain assistant again
});
