import { boundedToolResult, currentAssistantScope, sendAssistant } from "./engine";
import { validateDraft } from "./draftSchema";
import { useAssistant } from "./state";
import { useSession } from "@/stores/session";
import { useWorkspace } from "@/features/workspace/state";
import { installMockBridge, removeMockBridge } from "@/test/mockBridge";
import { GUIDES, searchGuides } from "./catalog";
import { WINDOW_IDS } from "@/windows/registry";
afterEach(() => {
  removeMockBridge();
  useAssistant.getState().reset("");
});
it("has version-matched instructions for every native window", () => {
  expect(new Set(GUIDES.map((g) => g.window))).toEqual(new Set(WINDOW_IDS));
  expect(GUIDES.every((g) => g.steps.length >= 2 && g.steps.every((s) => s.text.length > 15))).toBe(true);
});
it("rejects unsupported financial overrides, invalid quantities and hidden stock modifications", () => {
  expect(validateDraft("product", { name: "منتج", salePrice: 5000 })).toEqual({
    name: "منتج",
    salePrice: 5000,
  });
  for (const [kind, fields] of [
    ["product", { openingStock: 100 }],
    ["receipt", { tenant_id: 7, amount: 100 }],
    ["sale", { items: [{ product_id: 1, quantity: -1 }] }],
    ["sale", { items: [{ product_id: 1, quantity: 1, unitPrice: 1 }] }],
    ["expense", { amount: NaN }],
  ] as const)
    expect(() => validateDraft(kind, fields)).toThrow();
});
it("keeps tool JSON valid and explicitly reports truncation", () => {
  const result = boundedToolResult({
    rows: Array.from({ length: 80 }, (_, i) => ({ id: i, name: "x".repeat(4000) })),
  });
  expect(result.length).toBeLessThan(4600);
  expect(JSON.parse(result)).toMatchObject({ truncated: true });
});
it("offers local teaching without any network or cloud fallback when inference is disabled", async () => {
  const bridge = installMockBridge(() => {
    throw Error("Unexpected network request");
  });
  useSession.setState({ session: null });
  useWorkspace.setState({ identity: "" });
  useAssistant.getState().reset(currentAssistantScope());
  await sendAssistant("علّمني المنتج");
  expect(bridge.finora.request).not.toHaveBeenCalled();
  expect(useAssistant.getState().busy).toBe(false);
  expect(useAssistant.getState().messages.at(-1)?.text).toContain("Ollama");
  expect(searchGuides("منتج", null)).toEqual([]);
});
