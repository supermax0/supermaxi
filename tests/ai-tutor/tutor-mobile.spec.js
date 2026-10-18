import { test, expect } from "@playwright/test";
import {
  A, SHOT, card, clinicApi, createInvoiceViaApi, drive, fixture, gotoClinic, openHome, say, setTutor, settled, superLogin, tenantLogin, tutorials,
} from "./_helpers.js";

/**
 * Phase 7 mobile run: the same real lessons on a phone (touch, 390x800): the sidebar is a closed drawer the lesson opens by
 * itself, forms are modals, the card is a bottom sheet that must never hide the control the lesson points at, and an
 * on-screen keyboard (a much shorter viewport) must not push the target under the sheet.
 */
test.use({ channel: "msedge" });
test.describe.configure({ mode: "serial", timeout: 240_000 });

const stamp = Date.now();
const isoDay = (offset) => new Date(Date.now() + offset * 86_400_000).toISOString().slice(0, 10);
let ctxSuper;
let superPage;
let ctx;
let page;

/** The sheet docks to the bottom; whatever the lesson points at must stay above its top edge. */
async function expectTargetAboveSheet(p, step) {
  if (!step.target || !["wait_click", "wait_input", "wait_select", "highlight", "wait_api_success"].includes(step.type)) return;
  const kind = Object.keys(step.target)[0];
  const selector = `[data-finora-${kind}="${Object.values(step.target)[0]}"]`;
  const target = p.locator(selector).first();
  await target.scrollIntoViewIfNeeded().catch(() => {});
  await settled(p);
  const [c, t] = [await card(p).boundingBox(), await target.boundingBox()];
  if (!c || !t) return;
  const sheet = await card(p).evaluate((el) => el.classList.contains("is-sheet"));
  const edge = await card(p).evaluate((el) => el.dataset.tutorEdge || "bottom");
  if (sheet && edge === "top") {
    // Docked to the top (the target is a fixed control near the bottom edge): it must sit fully below the sheet.
    expect(t.y >= c.y + c.height - 1, `${step.id}: target is hidden by the top sheet (card bottom=${Math.round(c.y + c.height)}, target y=${Math.round(t.y)})`).toBe(true);
  } else if (sheet) {
    // The engine scrolls the target above the sheet. A tall target (a text area, a permissions box) may extend below the
    // sheet's top edge, but the part a person needs (its first ~40px, or all of it if smaller) must stay visible.
    const needed = Math.min(t.height, 40);
    const visible = Math.min(t.y + t.height, c.y) - Math.max(t.y, 0);
    expect(visible >= needed - 1, `${step.id}: target is hidden by the bottom sheet (card y=${Math.round(c.y)}, target y=${Math.round(t.y)}+${Math.round(t.height)})`).toBe(true);
  }
}

test.beforeAll(async ({ browser }) => {
  fixture("reset");
  fixture("clear-patients", A);
  ctxSuper = await browser.newContext({ baseURL: process.env.PLAYWRIGHT_BASE_URL, locale: "ar" });
  superPage = await ctxSuper.newPage();
  await superLogin(superPage);
  await setTutor(superPage, A, true);
  ctx = await browser.newContext({
    baseURL: process.env.PLAYWRIGHT_BASE_URL, locale: "ar", viewport: { width: 390, height: 800 }, isMobile: true, hasTouch: true,
  });
  page = await ctx.newPage();
  await tenantLogin(page, A);
});

test.afterAll(async () => {
  await ctx?.close();
  fixture("clear-patients", A);
  fixture("reset");
  await setTutor(superPage, A, false).catch(() => {});
  await ctxSuper?.close();
});

test("M1. mobile: patient.create, sidebar revealed by the lesson, bottom sheet never hides the target, keyboard-sized viewport", async () => {
  const person = { name: `مريض الجوال ${stamp}`, phone: `0776${String(stamp).slice(-7)}` };
  await gotoClinic(page);
  await openHome(page);
  const t0 = Date.now();
  await page.locator('[data-tutor-start="patient.create"]').click();
  await expect(card(page)).toContainText("المرضى");
  const startMs = Date.now() - t0;
  console.log(`[perf] mobile patient.create start -> first card: ${startMs} ms`);
  expect(startMs).toBeLessThan(2500); // the closed drawer is opened at once, not after a fixed wait
  await settled(page);
  await expect(card(page)).toHaveClass(/is-sheet/);
  await page.screenshot({ path: `${SHOT}/82-mobile-patient-step1.png` });
  let keyboardChecked = false;
  const trail = await drive(page, { "patient.name": person.name, "patient.phone": person.phone }, {
    onStep: async (p, { step }) => {
      await expectTargetAboveSheet(p, step);
      if (step.id === "name" && !keyboardChecked) {
        keyboardChecked = true;
        await p.setViewportSize({ width: 390, height: 460 }); // an on-screen keyboard leaves about half the height
        await p.waitForTimeout(400);
        await expectTargetAboveSheet(p, step);
        await p.screenshot({ path: `${SHOT}/83-mobile-patient-keyboard.png` });
        await p.setViewportSize({ width: 390, height: 800 });
        await p.waitForTimeout(300);
        await settled(p);
      }
      if (step.id === "save") await p.screenshot({ path: `${SHOT}/84-mobile-patient-save.png` });
    },
  });
  expect(trail.at(-1)).toBe("patient.create:done");
  const rows = await clinicApi(page, "/clinics/api/patients?limit=500");
  expect(rows.filter((r) => r.full_name === person.name)).toHaveLength(1);
  expect((await tutorials(page)).find((t) => t.id === "patient.create").progress.status).toBe("completed");
  await page.screenshot({ path: `${SHOT}/85-mobile-patient-completed.png` });
});

test("M2. mobile: appointment.create with a patient search, doctor select, date and time", async () => {
  fixture("reset");
  const day = isoDay(6);
  await gotoClinic(page);
  await openHome(page);
  const reply = await say(page, "احجز موعد");
  await reply.locator('[data-tutor-chat-action="start_tutorial"]').click();
  const trail = await drive(page, { "appointment.patient_search": `مريض الجوال ${stamp}`, "appointment.date": day, "appointment.time": "09:30" }, {
    onStep: async (p, { step }) => {
      await expectTargetAboveSheet(p, step);
      if (step.id === "patient-pick") await p.screenshot({ path: `${SHOT}/86-mobile-appointment-pick.png` });
      if (step.id === "doctor") await p.screenshot({ path: `${SHOT}/87-mobile-appointment-doctor.png` });
    },
  });
  expect(trail.at(-1)).toBe("appointment.create:done");
  const rows = await clinicApi(page, `/clinics/api/appointments?date=${day}`);
  expect(rows.filter((a) => a.patient_name === `مريض الجوال ${stamp}`)).toHaveLength(1);
  expect((await tutorials(page)).find((t) => t.id === "appointment.create").progress.status).toBe("completed");
  await page.screenshot({ path: `${SHOT}/88-mobile-appointment-completed.png` });
});

test("M3. mobile: payment.record, numeric keyboard viewport, bottom sheet never covers the amount field or confirm button", async () => {
  fixture("reset");
  const person = { name: `فاتورة الجوال ${stamp}`, phone: `0782${String(stamp).slice(-7)}`, time: "10:00", price: 500000 };
  const { invoice } = await createInvoiceViaApi(page, person);
  await gotoClinic(page);
  await openHome(page);
  const reply = await say(page, "اسجل دفعة");
  await reply.locator('[data-tutor-chat-action="start_tutorial"]').click();
  await expect(card(page)).toContainText("الفواتير");
  await settled(page);
  await expect(card(page)).toHaveClass(/is-sheet/);
  let keyboardChecked = false;
  const trail = await drive(page, { "payment.amount": "500000" }, {
    onStep: async (p, { step }) => {
      await expectTargetAboveSheet(p, step);
      if (step.id === "amount" && !keyboardChecked) {
        keyboardChecked = true;
        await p.screenshot({ path: `${SHOT}/98-mobile-payment-amount.png` });
        await p.setViewportSize({ width: 390, height: 460 }); // an on-screen numeric keyboard leaves about half the height
        await p.waitForTimeout(400);
        await expectTargetAboveSheet(p, step);
        await p.screenshot({ path: `${SHOT}/99-mobile-payment-amount-keyboard.png` });
        await p.setViewportSize({ width: 390, height: 800 });
        await p.waitForTimeout(300);
        await settled(p);
      }
      if (step.id === "save") await p.screenshot({ path: `${SHOT}/100-mobile-payment-save.png` });
    },
  });
  expect(trail.at(-1)).toBe("payment.record:done");
  await settled(page);
  const invoices = await clinicApi(page, "/clinics/api/invoices");
  const mine = invoices.find((i) => i.id === invoice.id);
  expect(mine.paid).toBe(500000);
  expect(mine.balance).toBe(0);
  expect(mine.status).toBe("paid");
  expect((await tutorials(page)).find((t) => t.id === "payment.record").progress.status).toBe("completed");
  await page.screenshot({ path: `${SHOT}/101-mobile-payment-completed.png` });
  await page.locator('[data-tutor-action="end"]').click();
  await expect(card(page)).toBeHidden();
});
