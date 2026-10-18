import { describe, expect, it } from "vitest";
import { canMoveLead, LEAD_STAGE_META } from "./leadStages";
import { leadStageSchema } from "./schemas";

describe("lead lifecycle", () => {
  it("defines a label and tone for every stage", () => {
    for (const s of leadStageSchema.options) expect(LEAD_STAGE_META[s].label).toBeTruthy();
  });

  it("follows the explicit forward path", () => {
    expect(canMoveLead("new", "engaged")).toBe(true);
    expect(canMoveLead("qualified", "trial")).toBe(true);
    expect(canMoveLead("account_created", "onboarding")).toBe(true);
    expect(canMoveLead("onboarding", "active_customer")).toBe(true);
  });

  it("refuses hidden or impossible transitions", () => {
    expect(canMoveLead("new", "active_customer")).toBe(false);
    expect(canMoveLead("lost", "active_customer")).toBe(false);
    expect(canMoveLead("qualified", "qualified")).toBe(false);
  });

  it("can always escalate to a human except from lost", () => {
    for (const s of leadStageSchema.options) {
      if (s === "needs_human" || s === "lost") continue;
      expect(canMoveLead(s, "needs_human")).toBe(true);
    }
  });
});
