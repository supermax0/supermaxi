export function evaluateSimpleCondition(expression: string, context: Record<string, unknown>): boolean {
  const normalized = expression.trim();
  if (!normalized) return false;

  const eqMatch = normalized.match(/^([a-zA-Z0-9_.$-]+)\s*==\s*['"]?([^'"]+)['"]?$/);
  if (eqMatch) {
    const key = eqMatch[1];
    const expected = eqMatch[2];
    const actual = context[key];
    return String(actual ?? "") === expected;
  }

  const notEqMatch = normalized.match(/^([a-zA-Z0-9_.$-]+)\s*!=\s*['"]?([^'"]+)['"]?$/);
  if (notEqMatch) {
    const key = notEqMatch[1];
    const expected = notEqMatch[2];
    const actual = context[key];
    return String(actual ?? "") !== expected;
  }

  const existsMatch = normalized.match(/^exists\(([a-zA-Z0-9_.$-]+)\)$/);
  if (existsMatch) {
    const key = existsMatch[1];
    return context[key] !== undefined && context[key] !== null && String(context[key]) !== "";
  }

  return false;
}
