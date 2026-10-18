import test from "node:test";
import assert from "node:assert/strict";
import {
  conditionMet, factMet, indexOfStep, nextStepIndex, previousTeachingIndex, recoveryAnchorIndex, requestMatches,
  routeForPage, selectorFor,
} from "../../static/ai-tutor/engine/core.js";
import { InvalidTransition, STATES, TRANSITIONS, TutorStateMachine } from "../../static/ai-tutor/engine/machine.js";

test("selectorFor builds stable data-finora selectors for every kind", () => {
  assert.equal(selectorFor({ action: "doctor.create" }), '[data-finora-action="doctor.create"]');
  assert.equal(selectorFor({ field: "doctor.name" }), '[data-finora-field="doctor.name"]');
  assert.equal(selectorFor({ section: "staff.form" }), '[data-finora-section="staff.form"]');
  assert.equal(selectorFor({ page: "staff" }), '[data-finora-page="staff"]');
});

test("selectorFor rejects fragile or unsafe references", () => {
  assert.throws(() => selectorFor({ action: 'x"] , body [a="' }), TypeError);
  assert.throws(() => selectorFor({ css: "div:nth-child(3)" }), TypeError);
  assert.throws(() => selectorFor({ action: "a", field: "b" }), TypeError);
  assert.throws(() => selectorFor(null), TypeError);
});

test("conditionMet covers min_length and min_checked", () => {
  assert.equal(conditionMet({ min_length: 3 }, { value: "  ab " }), false);
  assert.equal(conditionMet({ min_length: 3 }, { value: "abc" }), true);
  assert.equal(conditionMet({ min_checked: 1 }, { checked: 0 }), false);
  assert.equal(conditionMet({ min_checked: 1 }, { checked: 2 }), true);
  assert.equal(conditionMet(undefined, {}), true);
});

test("requestMatches checks method and url pattern", () => {
  const match = { method: "POST", url: "^/clinics/api/staff$" };
  assert.equal(requestMatches(match, "post", "/clinics/api/staff"), true);
  assert.equal(requestMatches(match, "GET", "/clinics/api/staff"), false);
  assert.equal(requestMatches(match, "POST", "/clinics/api/staff/5"), false);
});

const steps = [
  { id: "a", type: "wait_click", page: "x" },
  { id: "nav", type: "navigate", page: "y", route: "/y" },
  { id: "c", type: "wait_click", page: "y" },
  { id: "d", type: "wait_input", page: "y" },
];

test("step graph helpers", () => {
  assert.equal(indexOfStep(steps, "c"), 2);
  assert.throws(() => indexOfStep(steps, "zzz"), RangeError);
  assert.equal(nextStepIndex(steps, 0), 1);
  assert.equal(nextStepIndex(steps, 3), null);
  assert.equal(nextStepIndex(steps, 0, "d"), 3);
  assert.equal(recoveryAnchorIndex(steps, 3), 2);
  assert.equal(recoveryAnchorIndex(steps, 2), null);
  assert.equal(routeForPage(steps, 3, "y"), "/y");
  assert.equal(routeForPage(steps, 3, "zzz"), null);
});

test("state machine follows the documented transitions", () => {
  const m = new TutorStateMachine();
  const seen = [];
  m.subscribe((t) => seen.push(`${t.from}>${t.to}`));
  m.send("start"); m.send("ready"); m.send("await"); m.send("satisfied");
  m.send("validate"); m.send("invalid"); m.send("validate"); m.send("valid");
  m.send("pause"); m.send("resume"); m.send("finish");
  assert.equal(m.state, STATES.COMPLETED);
  assert.ok(m.isTerminal());
  assert.equal(seen[0], "IDLE>STARTING");
  m.send("reset");
  assert.equal(m.state, STATES.IDLE);
});

test("state machine rejects illegal transitions", () => {
  const m = new TutorStateMachine();
  assert.throws(() => m.send("await"), InvalidTransition);
  m.send("start"); m.send("ready"); m.send("cancel");
  assert.throws(() => m.send("advance"), InvalidTransition);
  assert.equal(m.can("reset"), true);
});

test("every non-terminal state can fail or be cancelled (no dead ends)", () => {
  for (const [state, table] of Object.entries(TRANSITIONS)) {
    if (["IDLE", "COMPLETED", "FAILED", "CANCELLED"].includes(state)) continue;
    assert.ok("cancel" in table, `${state} must allow cancel`);
    assert.ok("fail" in table, `${state} must allow fail`);
  }
});

test("factMet evaluates dependency rules and rejects unknown ones", () => {
  const facts = { doctors_count: 0, specialties_count: 2 };
  assert.equal(factMet({ name: "specialties_count", op: "gt", value: 0 }, facts), true);
  assert.equal(factMet({ name: "doctors_count", op: "eq", value: 0 }, facts), true);
  assert.equal(factMet({ name: "doctors_count", op: "gte", value: 1 }, facts), false);
  assert.equal(factMet({ name: "doctors_count", op: "lt", value: 1 }, facts), true);
  assert.throws(() => factMet({ name: "patients_count", op: "gt", value: 0 }, facts), RangeError);
  assert.throws(() => factMet({ name: "doctors_count", op: "like", value: 0 }, facts), RangeError);
});

test("semantic Back skips non-teaching, forbidden and off-page steps (never implies undo)", () => {
  const steps = [
    { id: "menu", type: "wait_click" },
    { id: "nav", type: "navigate", page: "staff" },
    { id: "add", type: "wait_click", page: "staff" },
    { id: "modal", type: "wait_modal", page: "staff" },
    { id: "branch", type: "branch", page: "staff" },
    { id: "name", type: "wait_input", page: "staff" },
    { id: "save", type: "wait_api_success", page: "staff", allow_back: false },
    { id: "verify", type: "wait_state", allow_back: false },
    { id: "done", type: "complete" },
  ];
  assert.equal(previousTeachingIndex(steps, 5, "staff"), 2); // skips branch + wait_modal
  assert.equal(previousTeachingIndex(steps, 2, "staff"), 0); // skips navigate
  assert.equal(previousTeachingIndex(steps, 0, "staff"), null);
  assert.equal(previousTeachingIndex(steps, 8, "staff"), 5); // never back onto the saved/verified steps
  assert.equal(previousTeachingIndex(steps, 5, "patients"), 0); // steps of another page cannot be shown here
});
