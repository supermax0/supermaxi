import fs from "node:fs";
import { execFileSync } from "node:child_process";
import { expect } from "@playwright/test";

/** Shared helpers for the Phase 7 specs (core journey, dependencies, mobile). */
export const CREDS = JSON.parse(fs.readFileSync(process.env.E2E_TUTOR_CREDS, "utf-8"));
export const [A, B, C] = ["tutor-e2e-a", "tutor-e2e-b", "tutor-e2e-c"];
export const BASE = process.env.PLAYWRIGHT_BASE_URL;
export const SHOT = process.env.E2E_SHOTS || "tests/_artifacts/tutor";

export const FAB = "#finoraAiFab";
export const CARD = '[data-tutor-ui="card"]';
export const card = (page) => page.locator(CARD);
export const next = (page) => page.locator('[data-tutor-action="next"]');
export const bot = (page) => page.locator('[data-tutor-msg="bot"]:not(.is-typing)');
export const settled = (page) => expect(card(page)).not.toHaveClass(/is-transitioning/, { timeout: 15_000 });

/** State helpers run against the throwaway E2E tenants only (the script refuses any other slug). */
export function fixture(...args) {
  return execFileSync("python", ["scripts/tutor_e2e_fixture.py", ...args], {
    env: { ...process.env, FINORA_DISABLE_SCHEDULERS: "1", PYTHONIOENCODING: "utf-8" },
    stdio: ["ignore", "pipe", "ignore"],
    encoding: "utf-8",
  });
}

/**
 * Switch the tutor feature through the Super Admin API. Going through the app (not the database) also invalidates the
 * server's feature cache, so a page loaded right afterwards sees the new state.
 */
export async function setTutor(superPage, slug, enabled) {
  const res = await superPage.request.patch(`/superadmin/features/tenants/${slug}/clinic_ai_tutor`, { data: { enabled } });
  if (!res.ok()) throw new Error(`could not ${enabled ? "enable" : "disable"} the tutor for ${slug}: ${res.status()}`);
}

export async function tenantLogin(page, slug) {
  await page.goto("/login");
  await page.locator('input[name="tenant_slug"]').fill(slug);
  await page.locator("#username").fill(CREDS.tenants[slug].username);
  await page.locator("#password").fill(CREDS.tenants[slug].password);
  await page.locator('form.login-form button[type="submit"]').click();
  await page.waitForURL((url) => !url.pathname.endsWith("/login"), { timeout: 35_000 });
}

export async function superLogin(page) {
  await page.goto("/superadmin/login");
  await page.locator("#username").fill(CREDS.superadmin.username);
  await page.locator("#password").fill(CREDS.superadmin.password);
  await page.locator("form button.sa-login-submit").click();
  await page.waitForURL((url) => !url.pathname.endsWith("/login"));
}

/** Open a clinic page and get past the first-visit welcome card (it is dealt with once per user). */
export async function gotoClinic(page, path = "/clinics/") {
  await page.goto(path);
  await expect(page.locator(FAB)).toBeVisible();
  await page.waitForFunction(() => !!window.FinoraTutor?.launcher);
  await page.locator('[data-tutor-action="welcome-later"]').click({ timeout: 3000 }).catch(() => {});
}

export async function openHome(page) {
  await page.waitForFunction(() => !!window.FinoraTutor?.launcher);
  await page.locator(FAB).click();
  await page.locator('[data-tutor-menu="learn"]').click();
  await expect(page.locator('[data-tutor-ui="home"]')).toBeVisible();
  await expect(page.locator('[data-tutor-ui="chat-input"]')).toBeEnabled();
}

/** Type a natural-language question and wait for the structured answer. */
export async function say(page, text) {
  const before = await bot(page).count();
  await page.locator('[data-tutor-ui="chat-input"]').fill(text);
  await page.locator('[data-tutor-ui="chat-send"]').click();
  await expect(bot(page)).toHaveCount(before + 1, { timeout: 15_000 });
  return bot(page).last();
}

export async function exitTutor(page) {
  await page.locator('[data-tutor-action="cancel"]').click();
  await page.locator('[data-tutor-action="confirm-end"]').click();
  await expect(card(page)).toBeHidden();
}

export const apiJson = (page, url, init) => page.evaluate(async ([u, i]) => {
  const res = await fetch(u, { credentials: "same-origin", headers: { "Content-Type": "application/json" }, ...(i || {}) });
  return { status: res.status, body: await res.json().catch(() => null) };
}, [url, init]);

export const clinicApi = (page, url) => apiJson(page, url).then((r) => r.body?.data);
export const clinicPost = (page, url, body) => apiJson(page, url, { method: "POST", body: JSON.stringify(body) }).then((r) => r.body);
/**
 * Fixture through the REAL clinic API (as the signed-in user): patient -> appointment today -> arrived -> waiting -> visit.
 * Returns {patient, appointment, visit}. Test data only; clinics use slot-aligned times so the day grid shows them.
 */
export async function openVisitViaApi(page, { name, phone, time }) {
  const today = new Date().toISOString().slice(0, 10);
  const patient = (await clinicPost(page, "/clinics/api/patients", { full_name: name, phone })).data;
  const doctors = await clinicApi(page, "/clinics/api/doctors");
  const appointment = (await clinicPost(page, "/clinics/api/appointments", {
    patient_id: patient.id, doctor_id: doctors[0].id, appointment_date: today, start_time: time, status: "confirmed",
  })).data;
  for (const status of ["arrived", "waiting"]) await clinicPost(page, `/clinics/api/appointments/${appointment.id}/status`, { status });
  const visit = (await clinicPost(page, "/clinics/api/visits", { appointment_id: appointment.id })).data;
  return { patient, appointment, visit };
}

/** A real, payable invoice (through the real clinic API, not a shortcut): patient -> visit -> treatment plan -> invoice. */
export async function createInvoiceViaApi(page, { name, phone, time, price }) {
  const { patient } = await openVisitViaApi(page, { name, phone, time });
  const plan = (await clinicPost(page, `/clinics/api/patients/${patient.id}/dental-treatment-plans`, { name: "خطة الدفع", status: "active" })).data;
  const planId = plan.plan?.id ?? plan.id;
  await clinicPost(page, `/clinics/api/dental-treatment-plans/${planId}/items`, { title: "علاج", estimated_price: price, tooth_number: "11", estimated_sessions: 1 });
  const invoice = (await clinicPost(page, `/clinics/api/dental-treatment-plans/${planId}/invoice`, { mode: "full" })).data;
  return { patient, invoice };
}

/** A real, fully paid invoice (through the real clinic APIs): invoice -> full payment. */
export async function createPaidInvoiceViaApi(page, person) {
  const { patient, invoice } = await createInvoiceViaApi(page, person);
  await clinicPost(page, `/clinics/api/invoices/${invoice.id}/pay`, { amount: person.price, method: "cash" });
  return { patient, invoice };
}

export const tutorials = (page) => apiJson(page, "/api/clinic/ai-tutor/tutorials").then((r) => r.body.tutorials);

const selectorFor = (ref) => {
  const [[kind, value]] = Object.entries(ref);
  return `[data-finora-${kind}="${value}"]`;
};

/** Type into an input, or choose from a select (value given, else the first real option). */
async function setField(locator, value, key) {
  const tag = await locator.evaluate((el) => el.tagName);
  if (tag === "SELECT") {
    if (value !== undefined) await locator.selectOption(String(value));
    else {
      const first = await locator.evaluate((el) => [...el.options].find((o) => o.value && !o.hidden && !o.disabled)?.value);
      if (!first) throw new Error(`${key}: select has no usable option`);
      await locator.selectOption(first);
    }
    return;
  }
  if (value === undefined) throw new Error(`${key}: no test data for this field`);
  await locator.fill(String(value));
}

const TARGETED = new Set(["wait_click", "wait_input", "wait_select", "highlight", "wait_api_success"]);

/**
 * Walk whatever tutorial is currently running, step by step, driven by the REAL definition the engine loaded:
 * every targeted step must show its own message, then the matching real control is used like a person would.
 * `data` maps field ids to the text to type. Dependencies (lessons that switch the running tutorial) are followed.
 * Returns the ids of the steps it executed, in order ("<tutorial>:<step>").
 */
export async function drive(page, data = {}, { onStep, timeoutMs = 200_000 } = {}) {
  const trail = [];
  let last = null;
  let lastMismatch = "";
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await card(page).locator(".ft-result-badge").count().catch(() => 0)) return trail;
    // A lesson that needs another one first asks (inside the card) before starting the dependency.
    const dependency = page.locator('[data-tutor-action="dependency_start"]');
    if (await dependency.count().catch(() => 0)) {
      trail.push("dependency_start");
      if (onStep) await onStep(page, { id: "dependency", step: { id: "dependency_start", type: "dependency" } });
      await settled(page);
      const button = await dependency.first().elementHandle();
      await button.click({ timeout: 10_000 });
      // The question is answered once: wait for THAT button to go (a second-level question may follow at once).
      await page.waitForFunction((el) => !el.isConnected || el.closest("[hidden]") !== null, button, { timeout: 10_000 });
      continue;
    }
    const state = await page.evaluate(() => {
      const e = window.FinoraTutor?.engine;
      const ref = e?.currentStepRef;
      // No step of THIS lesson is executing right now (switching lessons, asking a question, ...).
      if (!e?.tutorial || !e.stepCtl || !ref || ref.tutorial !== e.tutorial.id) return null;
      const index = e.tutorial.steps.findIndex((s) => s.id === ref.step);
      return index < 0 ? null : { id: e.tutorial.id, index, step: e.tutorial.steps[index] };
    }).catch(() => null);
    if (!state) { await page.waitForTimeout(150); continue; }
    const key = `${state.id}:${state.step.id}`;
    if (key === last) { await page.waitForTimeout(150); continue; }
    const { step } = state;
    if (step.type === "complete") {
      // Root lesson: the result card. Dependency lesson: the engine switches back to the parent lesson instead.
      trail.push(key);
      last = key;
      await page.waitForFunction((id) => !!document.querySelector(".ft-result-badge") || window.FinoraTutor?.engine?.tutorial?.id !== id,
        state.id, { timeout: 25_000 }).catch((error) => {
        throw new Error(`${key}: lesson neither showed its result nor switched back to its parent. trail: ${trail.join(" > ")}
${error.message}`);
      });
      continue;
    }
    if (TARGETED.has(step.type) && step.message_ar) {
      // Engine state can lag behind the screen while lessons switch: act only once the card shows THIS step's message.
      const shown = ((await card(page).innerText().catch(() => "")) || "").replace(/\s+/g, " ");
      if (!shown.includes(step.message_ar.replace(/\s+/g, " "))) {
        lastMismatch = `${key}: card shows ${JSON.stringify(shown.slice(0, 80))}`;
        await page.waitForTimeout(150);
        continue;
      }
      await settled(page);
    }
    if (onStep) await onStep(page, state);
    last = key;
    trail.push(key);
    if (process.env.DRIVE_LOG) console.log(`[drive +${Math.round((Date.now() - deadline + timeoutMs) / 100) / 10}s] ${key}`);
    const target = step.target ? page.locator(selectorFor(step.target)).first() : null;
    switch (step.type) {
      case "wait_click":
      case "wait_api_success":
        await target.click();
        break;
      case "wait_input": {
        await setField(target, data[Object.values(step.target)[0]], key);
        await expect(next(page)).toBeEnabled();
        await next(page).click();
        break;
      }
      case "wait_select": {
        const box = page.locator(selectorFor(step.watch)).first();
        if (!(await box.isChecked())) {
          // Styled chips hide the native checkbox: a person clicks the label around it.
          const label = box.locator("xpath=ancestor::label[1]");
          if (await label.count()) await label.click(); else await box.check();
        }
        await expect(next(page)).toBeEnabled();
        await next(page).click();
        break;
      }
      case "highlight":
      case "explain": {
        const value = step.target ? data[Object.values(step.target)[0]] : undefined;
        if (value !== undefined) await setField(target, value, key); // optional field the test wants to set
        await next(page).click();
        break;
      }
      default:
        break; // navigate / wait_modal / wait_state / branch advance on their own
    }
  }
  throw new Error(`tutorial did not finish within ${timeoutMs} ms; trail: ${trail.join(" > ")}; last card mismatch: ${lastMismatch}`);
}
