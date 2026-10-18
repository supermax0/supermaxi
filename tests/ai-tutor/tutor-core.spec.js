import { test, expect } from "@playwright/test";
import {
  A, C, SHOT, card, clinicApi, clinicPost, drive, fixture, gotoClinic, openHome, openVisitViaApi, say, setTutor, settled, superLogin, tenantLogin, tutorials,
} from "./_helpers.js";

/**
 * Phase 7 browser E2E: the clinic core journey, one lesson at a time. Every lesson is driven by its real definition
 * (see _helpers.drive), the result is verified in the backend, and training logs are checked for privacy.
 * Owns its state: resets progress + feature flag first, creates its own fixtures through the real API.
 */
test.use({ channel: "msedge" });
test.describe.configure({ mode: "serial", timeout: 240_000 }); // full lessons (and chains of lessons) are long on purpose

let ctxSuper;
let superPage;
let ctxA;
let pageA;
let ctxC;
let pageC;
const stamp = Date.now();
const isoDay = (offset) => new Date(Date.now() + offset * 86_400_000).toISOString().slice(0, 10);
const patient = { name: `مريض اختبار ${stamp}`, phone: `0770${String(stamp).slice(-7)}` };

test.beforeAll(async ({ browser }) => {
  fixture("reset");
  fixture("clear-patients", A);
  ctxSuper = await browser.newContext({ baseURL: process.env.PLAYWRIGHT_BASE_URL, locale: "ar" });
  superPage = await ctxSuper.newPage();
  await superLogin(superPage);
  await setTutor(superPage, A, true);
  ctxA = await browser.newContext({ baseURL: process.env.PLAYWRIGHT_BASE_URL, locale: "ar" });
  pageA = await ctxA.newPage();
  pageA.on("console", (m) => { if (["warning", "error"].includes(m.type()) && /tutor/i.test(m.text())) console.log(`[browser ${m.type()}] ${m.text().slice(0, 300)}`); });
  pageA.on("pageerror", (e) => console.log(`[pageerror] ${e.message.slice(0, 300)}`));
  await tenantLogin(pageA, A);
});

test.afterAll(async () => {
  await ctxA?.close();
  await ctxC?.close();
  fixture("clear-patients", A);
  fixture("strip", C);
  fixture("reset");
  for (const slug of [A, C]) await setTutor(superPage, slug, false).catch(() => {});
  await ctxSuper?.close();
});

test("1. patient.create: chat -> start -> real form -> backend verifies the new patient -> completed", async () => {
  await gotoClinic(pageA);
  await openHome(pageA);
  const reply = await say(pageA, "شلون أضيف مريض");
  await expect(reply).toContainText("أكدر أعلمك إضافة مريض");
  await pageA.screenshot({ path: `${SHOT}/60-patient-chat-suggestion.png` });
  const before = (await clinicApi(pageA, "/clinics/api/patients")).length;
  await reply.locator('[data-tutor-chat-action="start_tutorial"]').click();
  await expect(card(pageA)).toContainText("المرضى");
  await settled(pageA);
  await pageA.screenshot({ path: `${SHOT}/61-patient-step1.png` });

  const trail = await drive(pageA, { "patient.name": patient.name, "patient.phone": patient.phone }, {
    onStep: async (page, { step }) => {
      if (step.id === "name") await page.screenshot({ path: `${SHOT}/62-patient-name.png` });
      if (step.id === "save") await page.screenshot({ path: `${SHOT}/63-patient-save.png` });
    },
  });
  expect(trail.at(-1)).toBe("patient.create:done");
  await settled(pageA);
  await pageA.screenshot({ path: `${SHOT}/64-patient-completed.png` });

  const rows = await clinicApi(pageA, "/clinics/api/patients?limit=500");
  expect(rows.length).toBe(before + 1);
  expect(rows.some((p) => p.full_name === patient.name)).toBe(true);
  const progress = (await tutorials(pageA)).find((t) => t.id === "patient.create").progress;
  expect(progress.status).toBe("completed");
});

test("2. patient privacy: training logs and progress never contain what was typed", async () => {
  const dump = fixture("logs", A);
  expect(dump).not.toContain(patient.name);
  expect(dump).not.toContain(patient.phone);
  expect(dump).not.toContain("مريض اختبار");
  const logs = JSON.parse(dump).training_activity_logs.filter((l) => l.tutorial_id === "patient.create");
  expect(logs.length).toBeGreaterThan(5);
  expect(logs.every((l) => l.detail === null || /^[A-Za-z0-9_.:-]{1,80}$/.test(l.detail))).toBe(true);
  expect(new Set(logs.map((l) => l.event))).toContain("tutorial_completed");
  void clinicPost;
});

test("3. appointment.create with an existing patient: search + pick, doctor, backend verifies the appointment", async () => {
  const day = isoDay(3);
  await gotoClinic(pageA);
  await openHome(pageA);
  const reply = await say(pageA, "أريد أسوي موعد");
  await expect(reply).toContainText("أكدر أعلمك حجز موعد");
  await reply.locator('[data-tutor-chat-action="start_tutorial"]').click();
  await expect(card(pageA)).toContainText("المواعيد");
  await settled(pageA);
  const trail = await drive(pageA, {
    "appointment.patient_search": patient.name, "appointment.date": day, "appointment.time": "11:15",
  }, {
    onStep: async (page, { step }) => {
      if (step.id === "patient-pick") await page.screenshot({ path: `${SHOT}/65-appointment-pick-patient.png` });
      if (step.id === "doctor") await page.screenshot({ path: `${SHOT}/66-appointment-doctor.png` });
    },
  });
  expect(trail).toContain("appointment.create:patient-pick"); // a name search needs the explicit pick
  expect(trail.at(-1)).toBe("appointment.create:done");
  await settled(pageA);
  await pageA.screenshot({ path: `${SHOT}/67-appointment-completed.png` });
  const rows = await clinicApi(pageA, `/clinics/api/appointments?date=${day}`);
  const mine = rows.filter((a) => a.patient_name === patient.name);
  expect(mine).toHaveLength(1);
  expect(mine[0].start_time.slice(0, 5)).toBe("11:15");
  expect(mine[0].doctor_id).toBeTruthy();
  expect((await tutorials(pageA)).find((t) => t.id === "appointment.create").progress.status).toBe("completed");
});

test("4. no patient yet: appointment.create -> patient.create -> back to the appointment, nothing lost or duplicated", async () => {
  fixture("clear-patients", A);
  const day = isoDay(4);
  const second = { name: `مريض ثاني ${stamp}`, phone: `0771${String(stamp).slice(-7)}` };
  await gotoClinic(pageA);
  await openHome(pageA);
  const reply = await say(pageA, "احجز موعد");
  await reply.locator('[data-tutor-chat-action="start_tutorial"]').click();
  await expect(card(pageA)).toContainText("نحتاج مريضاً مسجلاً");
  await pageA.screenshot({ path: `${SHOT}/68-appointment-needs-patient.png` });
  const trail = await drive(pageA, {
    "patient.name": second.name, "patient.phone": second.phone,
    "appointment.patient_search": second.phone, "appointment.date": day, "appointment.time": "12:30",
  });
  const order = trail.filter((k) => ["dependency_start", "patient.create:save", "patient.create:done", "appointment.create:save", "appointment.create:done"].includes(k));
  expect(order).toEqual(["dependency_start", "patient.create:save", "patient.create:done", "appointment.create:save", "appointment.create:done"]);
  expect(trail).not.toContain("appointment.create:patient-pick"); // the phone matched exactly: the patient was already picked
  const patients = await clinicApi(pageA, "/clinics/api/patients?limit=500");
  expect(patients.filter((p) => p.full_name === second.name)).toHaveLength(1);
  const rows = await clinicApi(pageA, `/clinics/api/appointments?date=${day}`);
  expect(rows.filter((a) => a.patient_name === second.name)).toHaveLength(1);
  const status = Object.fromEntries((await tutorials(pageA)).map((t) => [t.id, t.progress?.status]));
  expect(status["patient.create"]).toBe("completed");
  expect(status["appointment.create"]).toBe("completed");
});

test("5. multi-level dependency on a clean clinic: appointment -> doctor -> specialty -> doctor -> appointment", async ({ browser }) => {
  fixture("strip", C); // no doctors, no specialties, no patients, no progress
  await setTutor(superPage, C, true);
  ctxC = await browser.newContext({ baseURL: process.env.PLAYWRIGHT_BASE_URL, locale: "ar" });
  pageC = await ctxC.newPage();
  await tenantLogin(pageC, C);
  const person = { name: `مريض نظيف ${stamp}`, phone: `0772${String(stamp).slice(-7)}` };
  const created = await clinicPost(pageC, "/clinics/api/patients", { full_name: person.name, phone: person.phone });
  expect(created.ok ?? true).toBeTruthy();
  const day = isoDay(5);
  const doctorName = `طبيب نظيف ${stamp}`;
  const specialtyName = `اختصاص نظيف ${stamp}`;

  await gotoClinic(pageC);
  await openHome(pageC);
  const reply = await say(pageC, "حجز موعد");
  await reply.locator('[data-tutor-chat-action="start_tutorial"]').click();
  await expect(card(pageC)).toContainText("نحتاج طبيباً مسجلاً"); // patient exists, doctor does not
  await pageC.screenshot({ path: `${SHOT}/69-multilevel-needs-doctor.png` });
  let sawSpecialtyPrompt = false;
  const trail = await drive(pageC, {
    "doctor.name": doctorName, "doctor.username": `dr_clean_${stamp}`, "doctor.password": `E2e!${stamp}`,
    "specialty.name": specialtyName, "appointment.patient_search": person.phone, "appointment.date": day, "appointment.time": "10:45",
  }, {
    onStep: async (page, { id, step }) => {
      if (step.id !== "dependency_start") return;
      const text = await card(page).innerText();
      if (text.includes("اختصاص")) {
        sawSpecialtyPrompt = true;
        await page.screenshot({ path: `${SHOT}/70-multilevel-needs-specialty.png` });
      }
    },
  });
  expect(sawSpecialtyPrompt).toBe(true);
  const order = trail.filter((k) => ["dependency_start", "specialty.create:save", "specialty.create:done", "doctor.create:save",
    "doctor.create:done", "appointment.create:save", "appointment.create:done"].includes(k));
  expect(order).toEqual(["dependency_start", "dependency_start", "specialty.create:save", "specialty.create:done",
    "doctor.create:save", "doctor.create:done", "appointment.create:save", "appointment.create:done"]);
  await settled(pageC);
  await pageC.screenshot({ path: `${SHOT}/71-multilevel-completed.png` });
  // No duplicated work and nothing lost: exactly one of each thing was created, every lesson completed.
  const doctors = await clinicApi(pageC, "/clinics/api/doctors");
  expect(doctors.filter((d) => (d.full_name || d.name) === doctorName)).toHaveLength(1);
  const specialties = await clinicApi(pageC, "/clinics/api/specialties");
  expect(specialties.filter((s) => s.name_ar === specialtyName)).toHaveLength(1);
  const appointments = await clinicApi(pageC, `/clinics/api/appointments?date=${day}`);
  expect(appointments.filter((a) => a.patient_name === person.name)).toHaveLength(1);
  const status = Object.fromEntries((await tutorials(pageC)).map((t) => [t.id, t.progress?.status]));
  expect(status).toMatchObject({ "specialty.create": "completed", "doctor.create": "completed", "appointment.create": "completed" });
});

/** Click the recommended-next-lesson button of the result card; the recommendation never starts by itself. */
async function startRecommended(page, lessonId) {
  const button = page.locator(`[data-tutor-action="lesson:${lessonId}"]`);
  await expect(button).toBeVisible();
  await expect(card(page)).toContainText("التالي المقترح");
  await button.click();
  await expect(card(page).locator(".ft-result-badge")).toHaveCount(0);
}

test("6. core journey through the lesson graph: patient -> appointment -> check-in -> queue -> visit, backend checked between stages", async () => {
  fixture("clear-patients", A);
  fixture("reset");
  const today = isoDay(0);
  const walker = { name: `مريض الرحلة ${stamp}`, phone: `0773${String(stamp).slice(-7)}` };
  const data = { "patient.name": walker.name, "patient.phone": walker.phone, "appointment.patient_search": walker.phone, "appointment.time": "13:30" };
  const todays = async () => (await clinicApi(pageA, `/clinics/api/appointments?date=${today}`)).filter((a) => a.patient_name === walker.name);
  await gotoClinic(pageA);
  await openHome(pageA);
  const reply = await say(pageA, "شلون أضيف مريض");
  await reply.locator('[data-tutor-chat-action="start_tutorial"]').click();

  // 1) patient -> the graph recommends booking an appointment (and only recommends it)
  await drive(pageA, data);
  await expect(card(pageA)).toContainText("اكتمل الدرس: إضافة مريض");
  expect((await clinicApi(pageA, "/clinics/api/patients?limit=500")).filter((p) => p.full_name === walker.name)).toHaveLength(1);
  expect(await todays()).toHaveLength(0); // nothing started by itself
  await pageA.screenshot({ path: `${SHOT}/72-core-patient-next-lesson.png` });

  // 2) appointment
  await startRecommended(pageA, "appointment.create");
  await drive(pageA, data);
  let [appt] = await todays();
  expect(appt.status).toBe("confirmed");

  // 3) check-in: the appointment becomes "arrived" and is NOT in the queue yet
  await startRecommended(pageA, "appointment.checkin");
  await drive(pageA, data);
  [appt] = await todays();
  expect(appt.status).toBe("arrived");

  // 4) queue
  await startRecommended(pageA, "queue.add");
  await drive(pageA, data);
  [appt] = await todays();
  expect(appt.status).toBe("waiting");

  // 5) visit
  await startRecommended(pageA, "visit.start");
  await drive(pageA, data);
  await expect(card(pageA)).toContainText("اكتمل الدرس: بدء زيارة");
  await settled(pageA);
  await pageA.screenshot({ path: `${SHOT}/73-core-visit-started.png` });
  [appt] = await todays();
  expect(appt.status).toBe("in_consultation");
  const visits = await clinicApi(pageA, `/clinics/api/visits?date=${today}`);
  expect(visits.filter((v) => v.patient_name === walker.name && v.appointment_id === appt.id)).toHaveLength(1);
  const status = Object.fromEntries((await tutorials(pageA)).map((t) => [t.id, t.progress?.status]));
  expect(status).toMatchObject({ "patient.create": "completed", "appointment.create": "completed", "appointment.checkin": "completed",
    "queue.add": "completed", "visit.start": "completed" });
});

test("7. service.create: name, price, duration, specialty link, backend verifies the new service", async () => {
  fixture("reset");
  const name = `خدمة اختبار ${stamp}`;
  await gotoClinic(pageA);
  await openHome(pageA);
  const reply = await say(pageA, "شلون أضيف خدمة");
  await expect(reply).toContainText("أكدر أعلمك إضافة خدمة");
  await reply.locator('[data-tutor-chat-action="start_tutorial"]').click();
  await drive(pageA, { "service.name": name }, {
    onStep: async (page, { step }) => {
      if (step.id === "specialty") await page.screenshot({ path: `${SHOT}/74-service-specialty.png` });
    },
  });
  await expect(card(pageA)).toContainText("اكتمل الدرس: إضافة خدمة");
  const rows = await clinicApi(pageA, "/clinics/api/services");
  const mine = (rows.items || rows).filter((s) => s.name === name);
  expect(mine).toHaveLength(1);
  expect((mine[0].specialty_ids || []).length).toBeGreaterThan(0); // linked, so it shows up when booking
  expect((await tutorials(pageA)).find((t) => t.id === "service.create").progress.status).toBe("completed");
});

test("8. treatment_plan.create: visits -> open visit -> treatment tab -> plan -> first treatment, backend verifies plan and item", async () => {
  fixture("clear-patients", A);
  fixture("reset");
  const owner = { name: `مريض الخطة ${stamp}`, phone: `0774${String(stamp).slice(-7)}`, time: "14:00" };
  const { patient: created } = await openVisitViaApi(pageA, owner);
  await gotoClinic(pageA);
  await openHome(pageA);
  const reply = await say(pageA, "شلون اسوي خطة علاج");
  await expect(reply).toContainText("أكدر أعلمك إنشاء خطة علاج");
  await reply.locator('[data-tutor-chat-action="start_tutorial"]').click();
  const planName = `خطة اختبار ${stamp}`;
  const trail = await drive(pageA, { "treatment_plan.name": planName, "treatment_plan.title": `حشوة ${stamp}` }, {
    onStep: async (page, { step }) => {
      if (step.id === "open-treatment-tab") await page.screenshot({ path: `${SHOT}/75-plan-open-tab.png` });
      if (step.id === "item-title") await page.screenshot({ path: `${SHOT}/76-plan-item-form.png` });
    },
  });
  expect(trail.at(-1)).toBe("treatment_plan.create:done");
  await settled(pageA);
  await pageA.screenshot({ path: `${SHOT}/77-plan-completed.png` });
  const plans = await clinicApi(pageA, `/clinics/api/patients/${created.id}/dental-treatment-plans`);
  expect(plans.active_plan.plan.name).toBe(planName);
  expect(plans.active_plan.items.length).toBeGreaterThanOrEqual(1);
  expect(plans.active_plan.items.some((i) => i.title === `حشوة ${stamp}`)).toBe(true);
  expect((await tutorials(pageA)).find((t) => t.id === "treatment_plan.create").progress.status).toBe("completed");
});

test("9. invoice.create: from the plan's items; the invoice exists, NOTHING is paid, backend verifies", async () => {
  fixture("clear-patients", A);
  fixture("reset");
  const owner = { name: `مريض الفاتورة ${stamp}`, phone: `0775${String(stamp).slice(-7)}`, time: "15:00" };
  const { patient } = await openVisitViaApi(pageA, owner);
  // A plan with one priced item already exists (created through the API), so the lesson starts at the invoice itself.
  const plan = (await clinicPost(pageA, `/clinics/api/patients/${patient.id}/dental-treatment-plans`, { name: "خطة الفاتورة", status: "active" })).data;
  const planId = plan.plan?.id ?? plan.id;
  await clinicPost(pageA, `/clinics/api/dental-treatment-plans/${planId}/items`, { title: "حشوة", estimated_price: 25000, tooth_number: "16", estimated_sessions: 1 });
  const before = (await clinicApi(pageA, "/clinics/api/invoices")).length;
  await gotoClinic(pageA);
  await openHome(pageA);
  const reply = await say(pageA, "اسوي فاتورة");
  await expect(reply).toContainText("أكدر أعلمك إنشاء فاتورة");
  await reply.locator('[data-tutor-chat-action="start_tutorial"]').click();
  const trail = await drive(pageA, {}, {
    onStep: async (page, { step }) => {
      if (step.id === "invoice-mode") await page.screenshot({ path: `${SHOT}/78-invoice-form.png` });
    },
  });
  expect(trail.at(-1)).toBe("invoice.create:done");
  await settled(pageA);
  await expect(card(pageA)).toContainText("لم تُسجَّل أي دفعة");
  const invoices = await clinicApi(pageA, "/clinics/api/invoices");
  expect(invoices.length).toBe(before + 1);
  const mine = invoices.filter((i) => i.patient_name === owner.name);
  expect(mine).toHaveLength(1);
  expect(Number(mine[0].total)).toBeGreaterThan(0);
  expect(Number(mine[0].paid || 0)).toBe(0); // the tutor never takes money: payment is a different lesson
  expect((await tutorials(pageA)).find((t) => t.id === "invoice.create").progress.status).toBe("completed");
});

test("10. employee.create: a non-doctor account with a role; backend verifies it is NOT a doctor", async () => {
  fixture("reset");
  const username = `emp_e2e_${stamp}`;
  const name = `موظف اختبار ${stamp}`;
  await gotoClinic(pageA);
  await openHome(pageA);
  const reply = await say(pageA, "شلون اضيف موظف");
  await expect(reply).toContainText("أكدر أعلمك إضافة موظف");
  await reply.locator('[data-tutor-chat-action="start_tutorial"]').click();
  const trail = await drive(pageA, { "employee.name": name, "employee.username": username, "employee.password": `E2e!${stamp}` }, {
    onStep: async (page, { step }) => {
      if (step.id === "role") await page.screenshot({ path: `${SHOT}/79-employee-role.png` });
    },
  });
  expect(trail.at(-1)).toBe("employee.create:done");
  expect(trail).not.toContain("doctor.create:name"); // a different lesson: the doctor account flow was never used
  const staff = await clinicApi(pageA, "/clinics/api/staff");
  const mine = staff.items.filter((row) => row.username === username);
  expect(mine).toHaveLength(1);
  expect(mine[0].doctor).toBeFalsy();
  expect(mine[0].role_key).not.toBe("clinic_doctor");
  expect(mine[0].permissions_count).toBeGreaterThan(0); // the role's permissions were applied
  expect((await tutorials(pageA)).find((t) => t.id === "employee.create").progress.status).toBe("completed");
});

test("11. permissions.manage: edit an employee's role and permission groups; the tutor never changes anything itself", async () => {
  fixture("reset");
  const target = { name: `موظف للصلاحيات ${stamp}`, username: `perm_e2e_${stamp}` };
  const created = await clinicPost(pageA, "/clinics/api/staff", { staff_type: "employee", name: target.name, username: target.username, password: `E2e!${stamp}`, role_key: "clinic_reception" });
  expect(created.ok ?? true).toBeTruthy();
  const countPermissions = async () => (await clinicApi(pageA, "/clinics/api/staff")).items.find((r) => r.username === target.username).permissions_count;
  const before = await countPermissions();
  const writes = [];
  const track = (req) => { if (["POST", "PUT", "PATCH", "DELETE"].includes(req.method()) && req.url().includes("/clinics/api/staff")) writes.push(`${req.method()} ${new URL(req.url()).pathname}`); };
  pageA.on("request", track);
  await gotoClinic(pageA);
  await openHome(pageA);
  const reply = await say(pageA, "شلون اغير صلاحيات موظف");
  await expect(reply).toContainText("أكدر أعلمك إدارة الصلاحيات");
  await reply.locator('[data-tutor-chat-action="start_tutorial"]').click();
  const trail = await drive(pageA, {}, {
    onStep: async (page, { step }) => {
      if (step.id === "group-finance") await page.screenshot({ path: `${SHOT}/80-permissions-finance-group.png` });
      if (step.id === "click-edit") {
        // Only the lesson's own user clicks: so far no write must have happened.
        expect(writes.filter((w) => !w.startsWith("POST /clinics/api/staff"))).toEqual([]);
      }
    },
  });
  pageA.off("request", track);
  expect(trail.filter((k) => k.includes("group-"))).toHaveLength(5);
  expect(writes.filter((w) => w.startsWith("PATCH"))).toHaveLength(1); // exactly the save the person pressed
  expect(await countPermissions()).toBe(before); // nothing was escalated by the lesson
  expect((await tutorials(pageA)).find((t) => t.id === "permissions.manage").progress.status).toBe("completed");
});

test("12. doctor.schedule: pick doctor + day + hours; backend verifies the new shift", async () => {
  fixture("reset");
  const before = (await clinicApi(pageA, "/clinics/api/schedules")).length;
  await gotoClinic(pageA);
  await openHome(pageA);
  const reply = await say(pageA, "شلون احدد دوام الطبيب");
  await expect(reply).toContainText("أكدر أعلمك جدول دوام الطبيب");
  await reply.locator('[data-tutor-chat-action="start_tutorial"]').click();
  const trail = await drive(pageA, { "schedule.start": "10:00", "schedule.end": "12:00" }, {
    onStep: async (page, { step }) => {
      if (step.id === "break") await page.screenshot({ path: `${SHOT}/81-schedule-break.png` });
    },
  });
  expect(trail.at(-1)).toBe("doctor.schedule:done");
  const rows = await clinicApi(pageA, "/clinics/api/schedules");
  expect(rows.length).toBe(before + 1);
  const mine = rows.filter((r) => String(r.start_time).startsWith("10:00") && String(r.end_time).startsWith("12:00"));
  expect(mine.length).toBeGreaterThanOrEqual(1);
  expect((await tutorials(pageA)).find((t) => t.id === "doctor.schedule").progress.status).toBe("completed");
  void rows;
});

test("13. a four-level dependency stack: visit.start -> queue.add -> appointment.checkin -> appointment.create, then back up", async () => {
  fixture("clear-patients", A);
  fixture("reset");
  const person = { name: `مريض السلسلة ${stamp}`, phone: `0777${String(stamp).slice(-7)}` };
  await clinicPost(pageA, "/clinics/api/patients", { full_name: person.name, phone: person.phone }); // only the patient exists
  const today = isoDay(0);
  await gotoClinic(pageA);
  await openHome(pageA);
  const reply = await say(pageA, "ابدي زيارة");
  await reply.locator('[data-tutor-chat-action="start_tutorial"]').click();
  await expect(card(pageA)).toContainText("المريض في قائمة الانتظار");
  const trail = await drive(pageA, { "appointment.patient_search": person.phone, "appointment.time": "16:00" });
  const marks = ["dependency_start", "appointment.create:save", "appointment.create:done", "appointment.checkin:act", "appointment.checkin:done",
    "queue.add:act", "queue.add:done", "visit.start:act", "visit.start:done"];
  expect(trail.filter((k) => marks.includes(k))).toEqual([
    "dependency_start", "dependency_start", "dependency_start",              // visit.start asks, queue.add asks, check-in asks
    "appointment.create:save", "appointment.create:done",                    // deepest lesson first
    "appointment.checkin:act", "appointment.checkin:done",
    "queue.add:act", "queue.add:done",
    "visit.start:act", "visit.start:done"]);                                 // and finally the lesson the person asked for
  const [appt] = (await clinicApi(pageA, `/clinics/api/appointments?date=${today}`)).filter((a) => a.patient_name === person.name);
  expect(appt.status).toBe("in_consultation");
  const visits = await clinicApi(pageA, `/clinics/api/visits?date=${today}`);
  expect(visits.filter((v) => v.appointment_id === appt.id)).toHaveLength(1);
  const status = Object.fromEntries((await tutorials(pageA)).map((t) => [t.id, t.progress?.status]));
  expect(status).toMatchObject({ "appointment.create": "completed", "appointment.checkin": "completed", "queue.add": "completed", "visit.start": "completed" });
});
