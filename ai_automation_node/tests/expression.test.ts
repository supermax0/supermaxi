import { describe, expect, it } from "vitest";
import { evaluateSimpleCondition } from "../src/modules/workflows/expression.js";

describe("evaluateSimpleCondition", () => {
  it("supports equality expressions", () => {
    const result = evaluateSimpleCondition("intent == 'order'", { intent: "order" });
    expect(result).toBe(true);
  });

  it("supports inequality expressions", () => {
    const result = evaluateSimpleCondition("intent != support", { intent: "order" });
    expect(result).toBe(true);
  });

  it("supports exists expressions", () => {
    const result = evaluateSimpleCondition("exists(phone)", { phone: "+9647700000000" });
    expect(result).toBe(true);
  });
});
