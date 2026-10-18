/* Pure, DOM-free tutorial logic (unit-testable with node:test). */

export const ATTRIBUTE_FOR_KIND = Object.freeze({
  page: "data-finora-page",
  section: "data-finora-section",
  action: "data-finora-action",
  field: "data-finora-field",
});

const ID_PATTERN = /^[a-z0-9][a-z0-9_.\-]*$/i;

/** Build the stable attribute selector for a `{kind: id}` reference. */
export function selectorFor(ref) {
  if (!ref || typeof ref !== "object") throw new TypeError("target reference required");
  const entries = Object.entries(ref);
  if (entries.length !== 1) throw new TypeError("target must contain exactly one identifier");
  const [kind, id] = entries[0];
  const attribute = ATTRIBUTE_FOR_KIND[kind];
  if (!attribute) throw new TypeError(`unknown target kind: ${kind}`);
  if (typeof id !== "string" || !ID_PATTERN.test(id)) throw new TypeError(`invalid target id: ${id}`);
  return `[${attribute}="${id}"]`;
}

export function indexOfStep(steps, stepId) {
  const index = steps.findIndex((step) => step.id === stepId);
  if (index < 0) throw new RangeError(`unknown step: ${stepId}`);
  return index;
}

/** Index of the step that follows `index`, honouring a branch decision. */
export function nextStepIndex(steps, index, branchTakenId = null) {
  if (branchTakenId) return indexOfStep(steps, branchTakenId);
  return index + 1 < steps.length ? index + 1 : null;
}

/** Condition check for input/select steps. `snapshot` = {value?, checked?}. */
export function conditionMet(condition, snapshot) {
  const cond = condition || {};
  if (typeof cond.min_length === "number") {
    if (String(snapshot.value ?? "").trim().length < cond.min_length) return false;
  }
  if (typeof cond.min_checked === "number") {
    if ((snapshot.checked ?? 0) < cond.min_checked) return false;
  }
  return true;
}

/** Does an observed request match a step's `match` rule? */
export function requestMatches(match, method, pathname) {
  if (String(match.method || "GET").toUpperCase() !== String(method || "GET").toUpperCase()) return false;
  return new RegExp(match.url).test(pathname);
}

/** Closest earlier step the user can safely restart from after losing a target. */
export function recoveryAnchorIndex(steps, index) {
  for (let i = index - 1; i >= 0; i -= 1) {
    if (steps[i].type === "wait_click" && steps[i].page === steps[index].page) return i;
  }
  return null;
}

/** Route of the closest navigate step at/before `index` for `page` (page-mismatch recovery). */
export function routeForPage(steps, index, page) {
  for (let i = Math.min(index, steps.length - 1); i >= 0; i -= 1) {
    if (steps[i].type === "navigate" && steps[i].page === page) return steps[i].route;
  }
  return null;
}

const OPERATORS = Object.freeze({
  eq: (a, b) => a === b,
  gt: (a, b) => a > b,
  gte: (a, b) => a >= b,
  lt: (a, b) => a < b,
});

/** Dependency rule check: {name, op, value} against server facts. */
export function factMet(rule, facts) {
  const op = OPERATORS[rule.op];
  if (!op) throw new RangeError(`unknown fact operator: ${rule.op}`);
  if (!(rule.name in facts)) throw new RangeError(`unknown fact: ${rule.name}`);
  return op(Number(facts[rule.name]), Number(rule.value));
}

const NOT_TEACHING = new Set(["navigate", "branch", "wait_modal", "wait_state", "complete", "error"]);
export const REVIEWABLE_TYPES = new Set(["wait_click", "wait_input", "wait_select", "wait_api_success", "highlight", "explain"]);

/**
 * Destination of the semantic "Back": the closest earlier step that teaches something, is allowed
 * (allow_back !== false) and can be shown on the current page. Never implies undoing backend work.
 */
export function previousTeachingIndex(steps, index, page) {
  for (let i = index - 1; i >= 0; i -= 1) {
    const step = steps[i];
    if (NOT_TEACHING.has(step.type) || step.allow_back === false) continue;
    if (step.page && page && step.page !== page) continue;
    return i;
  }
  return null;
}
