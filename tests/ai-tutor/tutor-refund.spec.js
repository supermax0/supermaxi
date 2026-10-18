import { test, expect } from "@playwright/test";
import {
  A, SHOT, card, clinicApi, createInvoiceViaApi, createPaidInvoiceViaApi, drive, fixture, gotoClinic, openHome, say, settled, tenantLogin, tutorials,
} from "./_helpers.js";

/** Phase 9: refund.record, through the real Billing page. A real, separate feature (ClinicRefund) — not Phase 8B. */
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

test("1. full refund from the invoice drawer: balance/paid update, invoice becomes open, backend verifies", async () => {
  const person = { name: `فاتورة استرداد ${stamp}`, phone: `0783${String(stamp).slice(-7)}`, time: "10:00", price: 400000 };
  const { invoice } = await createPaidInvoiceViaApi(pageA, person);
  await gotoClinic(pageA);
  await openHome(pageA);
  const reply = await say(pageA, "استرجع المبلغ");
  await expect(reply).toContainText("أكدر أعلمك");
  await reply.locator('[data-tutor-chat-action="start_tutorial"]').click();
  await expect(card(pageA)).toContainText("الفواتير");
  const trail = await drive(pageA, { "refund.amount": "400000", "refund.reason": "طلب المريض" }, {
    onStep: async (page, { step }) => {
      if (step.id === "save") await page.screenshot({ path: `${SHOT}/110-refund-save.png` });
    },
  });
  expect(trail.at(-1)).toBe("refund.record:done");
  await settled(pageA);
  await pageA.screenshot({ path: `${SHOT}/111-refund-completed.png` });
  const invoices = await clinicApi(pageA, "/clinics/api/invoices");
  const mine = invoices.find((i) => i.id === invoice.id);
  expect(mine.paid).toBe(0);
  expect(mine.status).toBe("refunded");
  expect((await tutorials(pageA)).find((t) => t.id === "refund.record").progress.status).toBe("completed");
  await pageA.locator('[data-tutor-action="end"]').click();
  await expect(card(pageA)).toBeHidden();
});

test("2. dependency chain: no refundable invoice -> payment.record -> resume refund.record", async () => {
  fixture("reset");
  fixture("clear-patients", A);
  const person = { name: `فاتورة استرداد2 ${stamp}`, phone: `0784${String(stamp).slice(-7)}`, time: "11:00", price: 250000 };
  await createInvoiceViaApi(pageA, person); // exists, payable, but NOTHING paid yet: not refundable
  await gotoClinic(pageA);
  await openHome(pageA);
  const reply = await say(pageA, "استرداد");
  await reply.locator('[data-tutor-chat-action="start_tutorial"]').click();
  await expect(card(pageA)).toContainText("نحتاج فاتورة فيها مبلغ مدفوع");
  const trail = await drive(pageA, {
    "payment.amount": "250000", "refund.amount": "250000", "refund.reason": "طلب المريض",
  }, { timeoutMs: 60_000 });
  const marks = trail.filter((k) => ["dependency_start", "payment.record:done", "refund.record:done"].includes(k));
  expect(marks).toEqual(["dependency_start", "payment.record:done", "refund.record:done"]);
  expect((await tutorials(pageA)).find((t) => t.id === "refund.record").progress.status).toBe("completed");
});
