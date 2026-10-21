import type { FinoraResponse } from "@shared/ipc";
import { DEFAULT_LOCAL_ASSISTANT } from "@shared/localAssistant";
import { useSession } from "@/stores/session";
import { useWorkspace } from "@/features/workspace/state";
import { installMockBridge, removeMockBridge } from "@/test/mockBridge";
import { buildSourceModel, sourceCsv } from "./sourceModel";
import { validateDraft } from "./draftSchema";
import { ALERT_CHECKS } from "./alerts";
import { diagnosisPrompt } from "./errorLog";
import { currentAssistantScope, sendAssistant } from "./engine";
import { useAssistant } from "./state";
import { routeTools } from "./toolRouter";

const ok = (data: unknown): FinoraResponse => ({ ok: true, status: 200, data });
afterEach(() => {
  removeMockBridge();
  useAssistant.getState().reset("");
});

describe("result cards (phase 3)", () => {
  it("shows a period comparison as KPI cards with the previous value and change", () => {
    const model = buildSourceModel({
      current: { from: "2026-10-01", net_sales: 590000, invoices: 3, net_profit: 140000 },
      previous: { net_sales: 400000, invoices: 2, net_profit: 0 },
      change_percent: { net_sales: 47.5, invoices: 50, net_profit: null },
    });
    expect(model.kpis.map((k) => [k.label, k.value, k.previous, k.change, k.money])).toEqual([
      ["صافي المبيعات", 590000, 400000, 47.5, true],
      ["عدد الفواتير", 3, 2, 50, false],
      ["صافي الربح", 140000, 0, null, true],
    ]);
  });
  it("charts labelled amounts and tabulates record rows without mixing them", () => {
    const model = buildSourceModel({
      receivables: 400000,
      aging: [
        { key: "today", label: "مستحق اليوم", amount: 100000 },
        { key: "d1_30", label: "1–30 يوم", amount: 300000 },
      ],
      oldest_open_invoices: [{ invoice_id: 9, customer_id: 4, customer: "أحمد", remaining: 300000 }],
    });
    expect(model.kpis).toEqual([{ key: "receivables", label: "ذمم العملاء", value: 400000, money: true }]);
    expect(model.bars[0]?.items.map((i) => i.value)).toEqual([100000, 300000]);
    expect(model.table?.columns.map((c) => c.key)).toEqual(["customer", "remaining"]);
    expect(model.table?.rows[0]).toMatchObject({ customer_id: 4 });
  });
  it("exports an Excel-readable CSV with a BOM and quoted cells", () => {
    const csv = sourceCsv("كشف", buildSourceModel({ items: [{ name: 'شاشة "LG", 55', remaining: 5 }] }));
    expect(csv.startsWith("﻿كشف")).toBe(true);
    expect(csv).toContain('"شاشة ""LG"", 55",5');
  });
});

describe("new drafts (phase 3)", () => {
  it("accepts supplier, payment, return, transfer and invoice-priced purchase drafts", () => {
    expect(validateDraft("supplier", { name: "شركة نسيم", phone: "0770" })).toEqual({
      name: "شركة نسيم",
      phone: "0770",
    });
    expect(validateDraft("supplier_payment", { supplier_id: 7, amount: 250000 })).toMatchObject({
      supplier_id: 7,
    });
    expect(validateDraft("return", { order_id: 12 })).toEqual({ order_id: 12 });
    expect(validateDraft("transfer", { items: [{ product_id: 3, quantity: 2 }] })).toBeTruthy();
    expect(
      validateDraft("purchase", {
        items: [{ product_id: 3, quantity: 2, unitCost: 9000 }],
        supplierInvoiceNo: "A-1",
      }),
    ).toMatchObject({ supplierInvoiceNo: "A-1" });
  });
  it("rejects drafts without a target record or with hidden fields", () => {
    for (const [kind, fields] of [
      ["supplier_payment", { amount: 1000 }],
      ["return", { order_id: -1 }],
      ["transfer", { items: [] }],
      ["supplier", { opening_balance: 5 }],
      ["purchase", { items: [{ product_id: 1, quantity: 1, unitCost: -5 }] }],
    ] as const)
      expect(() => validateDraft(kind, fields)).toThrow();
  });
});

describe("alerts and errors (phase 4)", () => {
  const check = (tool: string) => {
    const found = ALERT_CHECKS.find((c) => c.tool === tool);
    if (!found) throw Error(`missing check ${tool}`);
    return found;
  };
  it("raises an alert only when the tool reports something to act on", () => {
    expect(check("get_overdue_installments").read({ count: 2, amount: 40000 })?.text).toBe(
      "2 قسط متأخر بمبلغ 40,000 د.ع",
    );
    expect(check("get_overdue_installments").read({ count: 0 })).toBeNull();
    expect(check("get_low_stock").read({ count: 40 })?.text).toContain("40+");
    expect(check("get_purchases_summary").read({ totals: { remaining: 100000 } })?.window).toBe("purchases");
    expect(check("get_duplicate_customers").read({ groups_count: 0 })).toBeNull();
  });
  it("explains the real error text with where and when it happened", () => {
    const now = Date.UTC(2026, 9, 21, 10);
    const prompt = diagnosisPrompt(
      "الموردين",
      [],
      [{ message: "رصيد الحساب لا يكفي", at: now - 3 * 60_000, window: "suppliers" }],
      now,
    );
    expect(prompt).toContain("إشعار خطأ قبل 3 دقيقة في الموردين: رصيد الحساب لا يكفي");
    expect(diagnosisPrompt("الطلبات", [], [], now)).toContain("لا يوجد خطأ");
  });
  it("routes anomaly and duplicate questions to their tools", () => {
    const catalog = [
      "get_expenses",
      "get_expense_anomalies",
      "search_customer",
      "get_duplicate_customers",
    ].map((name) => ({ name, description: name, parameters: {} }));
    const route = (q: string) =>
      routeTools(catalog, { question: q, window: null, recentTools: [] }).map((t) => t.name);
    expect(route("شنو المصاريف غير الطبيعية هذا الشهر؟")).toContain("get_expense_anomalies");
    expect(route("منو العملاء المكررين بنفس الرقم؟")).toContain("get_duplicate_customers");
  });
});

describe("server fallback (phase 5)", () => {
  it("asks FINORA's server assistant only when the user enabled the fallback", async () => {
    const bridge = installMockBridge(() => ok({ success: true, message: "جواب الخادم" }));
    useSession.setState({ session: null });
    useWorkspace.setState({ identity: "" });
    useAssistant.getState().reset(currentAssistantScope());
    useAssistant.setState({ settings: { ...DEFAULT_LOCAL_ASSISTANT, serverFallback: true } });
    await sendAssistant("شكد مبيعات اليوم؟");
    expect(bridge.finora.request.mock.calls[0]?.[0]).toMatchObject({
      path: "/finora-ai/api/desktop/chat",
      body: { message: "شكد مبيعات اليوم؟" },
    });
    expect(useAssistant.getState().messages.at(-1)).toMatchObject({ text: "جواب الخادم", via: "server" });

    bridge.finora.request.mockClear();
    useAssistant.setState({ settings: { ...DEFAULT_LOCAL_ASSISTANT, serverFallback: false } });
    await sendAssistant("شكد مبيعات اليوم؟");
    expect(bridge.finora.request).not.toHaveBeenCalled();
  });
});
