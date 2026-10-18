import { test, expect } from "@playwright/test";
import {
  A, SHOT, card, clinicApi, createInvoiceViaApi, drive, fixture, gotoClinic, openHome, say, settled, tenantLogin, tutorials,
} from "./_helpers.js";

/**
 * Phase 8B: payment.record, through the real Billing page. Full payment, partial payment followed by a second
 * payment that finishes it off, and the generic (no drawer open) "any payable invoice" path.
 */
test.use({ channel: "msedge" });
test.describe.configure({ mode: "serial", timeout: 180_000 });

const stamp = Date.now();
let ctxA;
let pageA;

test.beforeAll(async ({ browser }) => {
  fixture("reset");
  fixture("clear-patients", A);
  fixture("enable", A);
  ctxA = await browser.newContext({ baseURL: process.env.PLAYWRIGHT_BASE_URL, locale: "ar" });
  pageA = await ctxA.newPage();
  await tenantLogin(pageA, A);
});

test.afterAll(async () => {
  await ctxA?.close();
  fixture("clear-patients", A);
  fixture("reset");
});

test("1. full payment from the invoice drawer: amount == remaining, invoice becomes paid, backend verifies", async () => {
  const person = { name: `فاتورة كاملة ${stamp}`, phone: `0778${String(stamp).slice(-7)}`, time: "10:00", price: 500000 };
  const { invoice } = await createInvoiceViaApi(pageA, person);
  await gotoClinic(pageA);
  await openHome(pageA);
  const reply = await say(pageA, "اسجل دفعة");
  await expect(reply).toContainText("أكدر أعلمك تسجيل دفعة");
  await reply.locator('[data-tutor-chat-action="start_tutorial"]').click();
  await expect(card(pageA)).toContainText("الفواتير");
  const trail = await drive(pageA, { "payment.amount": "500000" }, {
    onStep: async (page, { step }) => {
      if (step.id === "method") await page.screenshot({ path: `${SHOT}/91-payment-method.png` });
      if (step.id === "save") await page.screenshot({ path: `${SHOT}/92-payment-save.png` });
    },
  });
  expect(trail.at(-1)).toBe("payment.record:done");
  await settled(pageA);
  await pageA.screenshot({ path: `${SHOT}/93-payment-completed.png` });
  const invoices = await clinicApi(pageA, "/clinics/api/invoices");
  const mine = invoices.find((i) => i.id === invoice.id);
  expect(mine.paid).toBe(500000);
  expect(mine.balance).toBe(0);
  expect(mine.status).toBe("paid");
  expect((await tutorials(pageA)).find((t) => t.id === "payment.record").progress.status).toBe("completed");
  await pageA.locator('[data-tutor-action="end"]').click();
  await expect(card(pageA)).toBeHidden();
});

test("2. partial payment keeps the invoice partial, then a second payment.record run finishes it off", async () => {
  fixture("reset");
  const person = { name: `فاتورة جزئية ${stamp}`, phone: `0779${String(stamp).slice(-7)}`, time: "11:00", price: 500000 };
  const { invoice } = await createInvoiceViaApi(pageA, person);
  await gotoClinic(pageA);
  await openHome(pageA);

  // first payment: 200,000 of 500,000 — the lesson teaches that this does NOT close the invoice
  let reply = await say(pageA, "دفعة جزئية");
  await expect(reply).toContainText("أكدر أعلمك تسجيل دفعة");
  await reply.locator('[data-tutor-chat-action="start_tutorial"]').click();
  await expect(card(pageA)).toContainText("الفواتير");
  let trail = await drive(pageA, { "payment.amount": "200000" }, {
    onStep: async (page, { step }) => {
      if (step.id === "amount") await expect(card(page)).toContainText("لا تغلق الفاتورة");
    },
  });
  expect(trail.at(-1)).toBe("payment.record:done");
  let rows = await clinicApi(pageA, "/clinics/api/invoices");
  let mine = rows.find((i) => i.id === invoice.id);
  expect(mine.paid).toBe(200000);
  expect(mine.balance).toBe(300000);
  expect(mine.status).toBe("partial");
  await pageA.screenshot({ path: `${SHOT}/94-payment-partial-done.png` });
  await pageA.locator('[data-tutor-action="end"]').click();
  await expect(card(pageA)).toBeHidden();

  // second run: uses the NEW remaining (300,000), pays it off, invoice becomes paid
  await openHome(pageA);
  reply = await say(pageA, "اسجل دفعة");
  await reply.locator('[data-tutor-chat-action="start_tutorial"]').click();
  // Already on /clinics/billing from the first run: reconcile skips the navigation steps straight to
  // the real wait_click, so wait for the stale "done" badge to be gone rather than for nav-step text.
  await expect(card(pageA).locator(".ft-result-badge")).toHaveCount(0);
  trail = await drive(pageA, { "payment.amount": "300000" });
  expect(trail.at(-1)).toBe("payment.record:done");
  rows = await clinicApi(pageA, "/clinics/api/invoices");
  mine = rows.find((i) => i.id === invoice.id);
  expect(mine.paid).toBe(500000);
  expect(mine.balance).toBe(0);
  expect(mine.status).toBe("paid");

  // payment history now shows both payments
  const stmt = await clinicApi(pageA, `/clinics/api/patients/${invoice.patient_id}/statement`);
  const payments = (stmt.lines || []).filter((l) => l.type === "payment");
  expect(payments.length).toBeGreaterThanOrEqual(2);
  await pageA.screenshot({ path: `${SHOT}/95-payment-history-two-payments.png` });
  await pageA.locator('[data-tutor-action="end"]').click();
  await expect(card(pageA)).toBeHidden();
});

test("3. a fully paid invoice does not block the chat from suggesting payment.record on OTHER payable invoices", async () => {
  // tenant-wide dependency only cares whether ANY invoice is payable, not the specific one just closed
  const person = { name: `فاتورة أخرى ${stamp}`, phone: `0780${String(stamp).slice(-7)}`, time: "12:00", price: 150000 };
  await createInvoiceViaApi(pageA, person);
  await openHome(pageA);
  const reply = await say(pageA, "اسجل دفعة");
  await expect(reply.locator('[data-tutor-chat-action="start_tutorial"]')).toHaveText("ابدأ التعليم");
});

test("4. dependency chain: no payable invoice anywhere -> invoice.create -> resume payment.record", async () => {
  fixture("reset");
  fixture("clear-patients", A); // test 3 left an unpaid invoice behind; this scenario needs zero payable invoices
  const person = { name: `مريض بدون فاتورة ${stamp}`, phone: `0781${String(stamp).slice(-7)}` };
  await pageA.evaluate(async ({ name, phone }) => {
    await fetch("/clinics/api/patients", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ full_name: name, phone }) });
  }, person);
  await gotoClinic(pageA);
  await openHome(pageA);
  const reply = await say(pageA, "اسجل دفعة");
  await reply.locator('[data-tutor-chat-action="start_tutorial"]').click();
  await expect(card(pageA)).toContainText("نحتاج فاتورة فيها مبلغ متبقٍ");
  await pageA.screenshot({ path: `${SHOT}/96-payment-needs-invoice.png` });
  // The full chain this drives through, cold: payment.record -> invoice.create -> treatment_plan.create ->
  // visit.start -> queue.add -> appointment.checkin -> appointment.create. "كشفية أسنان" (service id 1, 15,000)
  // gives the plan item a real, non-zero price so the invoice (and the resumed payment step) has something to pay.
  const trail = await drive(pageA, {
    "appointment.patient_search": person.phone,
    "appointment.time": "16:00",
    "treatment_plan.name": `خطة ${stamp}`,
    "treatment_plan.service": "1",
    "treatment_plan.title": "فحص",
    "payment.amount": "15000",
  }, { timeoutMs: 120_000 });
  // The invoice doesn't exist yet, so the chain bottoms out through every prerequisite in turn:
  // payment.record -> invoice.create -> treatment_plan.create -> visit.start -> queue.add -> appointment.checkin
  // -> appointment.create, each asking before starting, then unwinding deepest-first back up to payment.record.
  const marks = [
    "dependency_start", "appointment.create:done", "appointment.checkin:done", "queue.add:done",
    "visit.start:done", "treatment_plan.create:done", "invoice.create:done", "payment.record:done",
  ];
  const order = trail.filter((k) => marks.includes(k));
  expect(order).toEqual([
    "dependency_start", "dependency_start", "dependency_start", "dependency_start", "dependency_start", "dependency_start",
    "appointment.create:done", "appointment.checkin:done", "queue.add:done", "visit.start:done",
    "treatment_plan.create:done", "invoice.create:done", "payment.record:done",
  ]);
  expect((await tutorials(pageA)).find((t) => t.id === "payment.record").progress.status).toBe("completed");
  await pageA.locator('[data-tutor-action="end"]').click();
  await expect(card(pageA)).toBeHidden();
});

test("5. void/reverse-payment phrasings refuse (no real workflow exists); refund is real and offered", async () => {
  await gotoClinic(pageA, "/clinics/billing");
  await openHome(pageA);
  for (const phrase of ["الغاء فاتورة", "عكس دفعة", "حذف دفعة"]) {
    const reply = await say(pageA, phrase);
    await expect(reply, phrase).toContainText("إلغاء الفاتورة أو عكس/حذف دفعة موجود خارج دروس التعليم الحالية");
    expect(await reply.locator('[data-tutor-chat-action="start_tutorial"]').count()).toBe(0);
  }
  const reply = await say(pageA, "اريد ارجع المبلغ");
  await expect(reply).toContainText("أكدر أعلمك");
  await expect(reply.locator('[data-tutor-chat-action="start_tutorial"]')).toHaveCount(1);
});

test("6. ambiguous 'المريض دفع' asks to choose between recording and viewing payments", async () => {
  await openHome(pageA);
  const reply = await say(pageA, "المريض دفع");
  const labels = await reply.locator("button").allTextContents();
  expect(labels.map((l) => l.trim())).toEqual(expect.arrayContaining(["تسجيل دفعة", "عرض الدفعات"]));
  await pageA.screenshot({ path: `${SHOT}/97-payment-ambiguous.png` });
});
