import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { FinoraRequest } from "@shared/ipc";
import { installMockBridge, removeMockBridge, SESSION_PAYLOAD } from "@/test/mockBridge";
import { useSession } from "@/stores/session";
import { useConnection } from "@/stores/connection";
import { useOrderNavigation } from "@/stores/orderNavigation";
import { usePurchaseNavigation } from "@/stores/purchaseNavigation";
import { useWindowManager } from "@/stores/windowManager";
import { StockActivity } from "./StockActivity";
import type { InventoryActivityRow } from "@/api/finora/inventoryActivity";

const row: InventoryActivityRow = {
  id: 12,
  record_kind: "movement",
  product_id: 8,
  product_name: "شاشة اختبار",
  sku: "TV55",
  branch_id: 2,
  branch_name: "الفرع الرئيسي",
  created_at: "2026-10-12T09:30:00Z",
  operation: "sale",
  direction: "out",
  quantity: 2,
  variant: "اللون: أسود / المقاس: L",
  before: null,
  after: null,
  balance_basis: "unknown",
  actor_name: "سارة",
  reason: "تسليم طلب",
  source_type: "invoice",
  source_id: 919,
  can_open_source: true,
  reversal: false,
};

function setup(overrides: Partial<InventoryActivityRow> = {}) {
  const requests: FinoraRequest[] = [];
  const bridge = installMockBridge(async (request) => {
    requests.push(structuredClone(request));
    return {
      ok: true,
      status: 200,
      data: {
        success: true,
        data: {
          available: true,
          items: [{ ...row, ...overrides }],
          total: 1,
          page: 1,
          page_size: 25,
          branches: [{ id: 2, name: "الفرع الرئيسي" }],
          can_view_cost: overrides.total_cost !== undefined,
          notice: "الرصيد غير الموثق يظهر —",
        },
      },
    };
  });
  useSession
    .getState()
    .signedIn({ ...SESSION_PAYLOAD, permissions: ["can_manage_inventory", "can_see_orders"] });
  useConnection.getState().setStatus("online");
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onAudit = vi.fn(),
    onProduct = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <StockActivity
        scope="acme:7:2"
        active
        onAudit={onAudit}
        onProduct={onProduct}
        onClearProduct={vi.fn()}
      />
    </QueryClientProvider>,
  );
  return { requests, bridge, onAudit, onProduct };
}

afterEach(() => {
  useOrderNavigation.getState().clear();
  usePurchaseNavigation.getState().clear();
  useWindowManager.getState().reset();
  removeMockBridge();
});

test("shows unknown balances honestly, explains them and opens the precise order without a write", async () => {
  const { requests, onProduct } = setup();
  const user = userEvent.setup();
  await user.click(await screen.findByText("شاشة اختبار"));
  const panel = screen.getByRole("complementary", { name: "تفاصيل حركة المخزون" });
  expect(within(panel).getByText(/ماكو رصيد سابق ولاحق موثق/)).toBeInTheDocument();
  expect(within(panel).queryByText(/قيمة الحركة بالتكلفة/)).not.toBeInTheDocument();
  await user.click(within(panel).getByRole("button", { name: "بطاقة المنتج" }));
  expect(onProduct).toHaveBeenCalledWith(8);
  await user.click(within(panel).getByRole("button", { name: "عرض المستند" }));
  expect(useOrderNavigation.getState().invoiceId).toBe(919);
  expect(useWindowManager.getState().active).toBe("orders");
  expect(requests.every((request) => request.method === "GET")).toBe(true);
});

test("filter inputs reach the broker, source permissions hide navigation and help owns Escape", async () => {
  const { requests } = setup({ can_open_source: false, source_id: null });
  const user = userEvent.setup();
  await screen.findByText("شاشة اختبار");
  await user.selectOptions(screen.getByLabelText("الفرع"), "2");
  await user.selectOptions(screen.getByLabelText("اتجاه الحركة"), "out");
  await user.type(screen.getByPlaceholderText(/ابحث باسم الصنف/), "TV55");
  await waitFor(() =>
    expect(requests.at(-1)?.query).toMatchObject({ branch_id: "2", direction: "out", q: "TV55" }),
  );
  await user.click(await screen.findByText("شاشة اختبار"));
  expect(screen.queryByRole("button", { name: "عرض المستند" })).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "شرح سجل حركة المخزون" }));
  expect(screen.getByRole("note")).toHaveTextContent("الرصيد غير الموثق");
  await user.keyboard("{Escape}");
  expect(screen.getByRole("complementary", { name: "تفاصيل حركة المخزون" })).toBeInTheDocument();
  await waitFor(() => expect(screen.queryByRole("note")).not.toBeInTheDocument());
});

test("routes purchases and audit sources to their native workspaces", async () => {
  const { onAudit } = setup({ source_type: "inventory_count", source_id: 17 });
  const user = userEvent.setup();
  await user.click(await screen.findByText("شاشة اختبار"));
  await user.click(screen.getByRole("button", { name: "عرض المستند" }));
  expect(onAudit).toHaveBeenCalledWith(17);
});

test("purchase source preserves its scoped target and switches to purchases", async () => {
  setup({ source_type: "purchase", source_id: 901 });
  const user = userEvent.setup();
  await user.click(await screen.findByText("شاشة اختبار"));
  await user.click(screen.getByRole("button", { name: "عرض المستند" }));
  expect(usePurchaseNavigation.getState().target?.id).toBe(901);
  expect(useWindowManager.getState().active).toBe("purchases");
  useSession.getState().signedIn({
    ...SESSION_PAYLOAD,
    permissions: ["can_manage_inventory"],
    tenant: { ...SESSION_PAYLOAD.tenant, slug: "other-company" },
  });
  expect(usePurchaseNavigation.getState().target).toBeNull();
});

test("trade-in source uses the related invoice ID and exact whole dinars", async () => {
  setup({
    source_type: "trade_in_receipt",
    source_id: 12,
    document_kind: "invoice",
    document_id: 919,
    total_cost: "9007199254740993",
    unit_cost: "9007199254740993",
  });
  const user = userEvent.setup();
  await user.click(await screen.findByText("شاشة اختبار"));
  expect(screen.getAllByText("9,007,199,254,740,993 د.ع").length).toBeGreaterThan(0);
  await user.click(screen.getByRole("button", { name: "عرض المستند" }));
  expect(useOrderNavigation.getState().invoiceId).toBe(919);
});

test("print carries the active filters without limiting the report to a table page", async () => {
  const { bridge, requests } = setup();
  const user = userEvent.setup();
  await screen.findByText("شاشة اختبار");
  await user.selectOptions(screen.getByLabelText("الفرع"), "2");
  await user.selectOptions(screen.getByLabelText("اتجاه الحركة"), "out");
  await user.type(screen.getByPlaceholderText(/ابحث باسم الصنف/), "TV55");
  await waitFor(() => expect(requests.at(-1)?.query?.q).toBe("TV55"));
  await user.click(screen.getByRole("button", { name: "طباعة / PDF" }));
  expect(bridge.print.open).toHaveBeenCalledWith({
    kind: "inventory_activity",
    q: "TV55",
    branch_id: 2,
    direction: "out",
  });
});
