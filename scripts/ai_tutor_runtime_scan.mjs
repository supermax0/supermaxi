/*
 * Runtime analyzer for Finora AI Tutor (development / CI only).
 *
 * Logs into a TEST clinic account, visits every clinic page reachable from the sidebar and records the
 * data-finora-* elements it sees (page, route, visible state, modal state, label). It only navigates and
 * opens modals from an explicit allow-list; it never clicks anything classified destructive, financial or
 * irreversible, never presses a save button, and counts any write request it observes (must be 0).
 *
 * CLI:  AI_TUTOR_SCAN_URL=http://127.0.0.1:5008 AI_TUTOR_SCAN_TENANT=... AI_TUTOR_SCAN_USER=... \
 *       AI_TUTOR_SCAN_PASSWORD=... node scripts/ai_tutor_runtime_scan.mjs --out runtime.json
 *       python scripts/analyze_ai_tutor.py --runtime runtime.json --write
 */
import fs from "node:fs";
import { pathToFileURL } from "node:url";

/** Only these actions may be clicked (they merely open a form). Everything else is observed, never touched. */
export const SAFE_OPENERS = ["appointment.create", "doctor.create", "employee.create", "patient.create", "specialty.create"];

const CLASSES = [
  ["financial", /(pay|refund|settle|invoice|billing|cash|expense|receipt|salary|payroll|discount|charge|deposit)/],
  ["destructive", /(delete|remove|archive|void|discard|reset|purge|erase|deactivate|disable|revoke)/],
  ["irreversible", /(save|submit|confirm|approve|finalize|complete|close|checkout|checkin|send|post|publish|import|restore|transfer|merge)/],
];

/** destructive | financial | irreversible | safe  (navigation and modal.cancel are plumbing and always safe). */
export function classify(id) {
  if (id.startsWith("nav.") || id === "modal.cancel") return "safe";
  const hit = CLASSES.find(([, pattern]) => pattern.test(id));
  return hit ? hit[0] : "safe";
}

export function mayClick(id, allow = SAFE_OPENERS) {
  return allow.includes(id) && classify(id) === "safe";
}

const IGNORED_WRITES = ["/api/clinic/ai-tutor/", "/api/features/"]; // tutor telemetry, not application data

async function collect(page) {
  return page.evaluate(() => {
    const out = [];
    const modalOf = (node) => node.closest("#cxModal, .cx-modal, [role='dialog']:not([data-tutor-ui])");
    const visible = (node) => {
      const r = node.getBoundingClientRect();
      const s = getComputedStyle(node);
      return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none" && !node.closest("[hidden]");
    };
    const label = (node, kind) => {
      if (kind !== "action" && kind !== "field") return null;
      const text = node.getAttribute("aria-label") || node.getAttribute("title") || node.getAttribute("placeholder") || (node.innerText || "").trim();
      return text ? text.replace(/\s+/g, " ").slice(0, 60) : null;
    };
    for (const kind of ["page", "section", "action", "field"]) {
      for (const node of document.querySelectorAll(`[data-finora-${kind}]`)) {
        if (node.closest("[data-tutor-ui], #finora-tutor-root")) continue;
        const modal = modalOf(node);
        out.push({
          kind, id: node.getAttribute(`data-finora-${kind}`), visible: visible(node),
          in_modal: !!modal && visible(modal), label: label(node, kind),
        });
      }
    }
    return out;
  });
}

/** Pages render in stages (skeleton, then data): wait until the number of finora elements stops changing. */
async function settle(page, maxMs = 4000) {
  const count = () => page.evaluate(() => document.querySelectorAll("[data-finora-action],[data-finora-field],[data-finora-section]").length);
  let previous = -1;
  let stable = 0;
  for (let waited = 0; waited < maxMs && stable < 2; waited += 300) {
    const now = await count();
    stable = now === previous ? stable + 1 : 0;
    previous = now;
    await page.waitForTimeout(300);
  }
}

async function closeModal(page) {
  const cancel = page.locator('[data-finora-action="modal.cancel"]').first();
  if (await cancel.isVisible().catch(() => false)) await cancel.click();
  else await page.keyboard.press("Escape");
}

export async function scanClinic(page, { baseURL, allowOpeners = SAFE_OPENERS, log = () => {} } = {}) {
  const writes = [];
  const thirdParty = new Set();
  const origin = new URL(baseURL).origin;
  page.on("request", (req) => {
    if (["GET", "HEAD", "OPTIONS"].includes(req.method())) return;
    if (new URL(req.url()).origin !== origin) { // analytics beacons etc.: not application data, reported separately
      thirdParty.add(new URL(req.url()).host);
      return;
    }
    if (IGNORED_WRITES.some((p) => req.url().includes(p))) return;
    writes.push(`${req.method()} ${req.url()}`);
  });

  await page.goto(new URL("/clinics/", baseURL).href, { waitUntil: "domcontentloaded" });
  const routes = await page.evaluate(() => [...new Set([...document.querySelectorAll('a[data-finora-action^="nav."]')]
    .map((a) => a.getAttribute("href")).filter((h) => h && h.startsWith("/clinics")))]);
  const clicked = [];
  const skipped = new Map();
  const pages = [];

  for (const route of routes) {
    const response = await page.goto(new URL(route, baseURL).href, { waitUntil: "domcontentloaded" });
    await page.waitForFunction(() => document.querySelector("#cxRoot")?.children.length > 0, null, { timeout: 8000 })
      .catch(() => log(`render wait timed out on ${route}`)); // slow page: still record what is there
    await settle(page);
    const id = await page.evaluate(() => document.querySelector("main[data-finora-page]")?.getAttribute("data-finora-page") || null);
    const expected = route === "/clinics/" || route === "/clinics" ? "dashboard" : route.replace(/\/$/, "").split("/").pop();
    const accessible = id === expected;
    const elements = new Map();
    const remember = (items) => items.forEach((e) => { const k = `${e.kind}:${e.id}`; const prev = elements.get(k); elements.set(k, prev ? { ...prev, visible: prev.visible || e.visible, in_modal: prev.in_modal || e.in_modal } : e); });
    if (accessible) {
      const base = await collect(page);
      remember(base);
      for (const opener of base.filter((x) => x.kind === "action" && x.visible && mayClick(x.id, allowOpeners))) {
        await page.locator(`[data-finora-action="${opener.id}"]`).first().click();
        clicked.push(opener.id);
        await page.locator("#cxModal:not([hidden])").waitFor({ timeout: 4000 }).catch(() => log(`no modal after ${opener.id}`));
        await settle(page, 1500);
        remember((await collect(page)).filter((x) => x.in_modal || x.kind === "field"));
        await closeModal(page);
        await page.locator("#cxModal").waitFor({ state: "hidden", timeout: 4000 }).catch(() => log(`modal did not close after ${opener.id}`));
      }
    }
    pages.push({ id: id || expected, route, accessible, status: response ? response.status() : 0, elements: [...elements.values()] });
  }
  for (const p of pages) {
    for (const e of p.elements) {
      if (e.kind === "action" && !e.id.startsWith("nav.") && !e.id.startsWith("modal.") && classify(e.id) !== "safe") skipped.set(e.id, classify(e.id));
    }
  }
  return {
    schema: 1, generated_at: new Date().toISOString(), pages,
    safety: { clicked: [...new Set(clicked)], skipped: [...skipped].map(([id, klass]) => ({ id, class: klass })), writes_observed: writes.length, write_requests: writes.slice(0, 10), third_party_write_hosts: [...thirdParty] },
  };
}

async function main() {
  const out = process.argv.includes("--out") ? process.argv[process.argv.indexOf("--out") + 1] : "runtime.json";
  const env = (name) => process.env[name] || (() => { throw new Error(`${name} is required`); })();
  const baseURL = env("AI_TUTOR_SCAN_URL");
  const { chromium } = await import("@playwright/test");
  const browser = await chromium.launch({ channel: process.env.AI_TUTOR_SCAN_CHANNEL || undefined, headless: true });
  try {
    const page = await (await browser.newContext({ baseURL, locale: "ar" })).newPage();
    await page.goto("/login");
    await page.locator('input[name="tenant_slug"]').fill(env("AI_TUTOR_SCAN_TENANT"));
    await page.locator("#username").fill(env("AI_TUTOR_SCAN_USER"));
    await page.locator("#password").fill(env("AI_TUTOR_SCAN_PASSWORD"));
    await page.locator('form.login-form button[type="submit"]').click();
    await page.waitForURL((url) => !url.pathname.endsWith("/login"));
    const result = await scanClinic(page, { baseURL, log: (m) => console.error(m) });
    fs.writeFileSync(out, JSON.stringify(result, null, 1));
    console.log(`runtime scan: ${result.pages.length} pages, ${result.pages.reduce((n, p) => n + p.elements.length, 0)} elements, clicked [${result.safety.clicked}], writes ${result.safety.writes_observed} -> ${out}`);
    if (result.safety.writes_observed) process.exitCode = 1;
  } finally {
    await browser.close();
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((error) => { console.error(error.message); process.exit(2); });
}
