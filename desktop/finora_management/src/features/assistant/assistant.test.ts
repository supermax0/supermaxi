import {
  boundedToolResult,
  currentAssistantScope,
  currentPageContext,
  rowTarget,
  sendAssistant,
  stripThinking,
} from "./engine";
import { useAssistantPage } from "./pageContext";
import { assistantSuggestions } from "./suggestions";
import { useWindowManager } from "@/stores/windowManager";
import { ADMIN_SESSION } from "@/test/fixtures";
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
it("links each report row to the record its window opens, never a neighbouring ID", () => {
  useSession.getState().signedIn({
    ...ADMIN_SESSION,
    permissions: ["manage_customers", "can_manage_inventory", "view_reports"],
  });
  const source = (name: string) => ({ name, title: name, at: "", data: null, arguments: {} });
  // An aging row carries both the invoice and the customer: the customers window needs the customer.
  expect(rowTarget(source("get_receivables_aging"), { invoice_id: 90, customer_id: 4 })).toEqual({
    window: "customers",
    entityId: 4,
  });
  expect(rowTarget(source("get_purchases_summary"), { purchase_id: 12, supplier_id: 3 })).toEqual({
    window: "purchases",
    entityId: 12,
  });
  expect(rowTarget(source("get_overdue_installments"), { installment_id: 8, customer_id: 4 })).toMatchObject({
    entityId: 4,
  });
  expect(rowTarget(source("get_period_comparison"), { id: 1 })).toEqual({ window: "reports" });
  useSession.setState({ session: null });
});
it("tells the model what the open window shows and offers questions about it", () => {
  useWindowManager.setState({ active: "suppliers" });
  useAssistantPage.setState({
    details: { suppliers: { search: "نسيم", record: { id: 7, name: "شركة نسيم القمر" } } },
  });
  const page = currentPageContext();
  expect(page.view).toEqual({ search: "نسيم", record: { id: 7, name: "شركة نسيم القمر" } });
  expect(page.version).toMatch(/^\d+\.\d+\.\d+/);
  expect(assistantSuggestions("suppliers", page.view ?? undefined)[0]?.text).toContain("شركة نسيم القمر");
  expect(assistantSuggestions(null, undefined).map((s) => s.text)).toContain("اعرض ملخص بداية الدوام");
  useWindowManager.setState({ active: null });
  useAssistantPage.setState({ details: {} });
});
it("never shows inline model reasoning", () => {
  expect(stripThinking("<think>internal</think>\nالجواب")).toBe("الجواب");
  expect(stripThinking("<think>still thinking")).toBe("");
});
