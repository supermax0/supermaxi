import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import type { FinoraRequest } from "@shared/ipc";
import type { StockMeta, StockTransferDetail } from "@/api/finora/stockOperations";
import { installMockBridge, removeMockBridge } from "@/test/mockBridge";
import { StockForms } from "./StockForms";

afterEach(removeMockBridge);

const meta = {
  kind: "branch",
  kinds: ["branch"],
  locations: [],
  branches: [],
  today: "2026-10-16",
  can_create_transfer: true,
  can_send: true,
  can_receive: true,
  can_writeoff: true,
  can_edit_rules: true,
  can_manage_locations: true,
  show_cost: false,
} as unknown as StockMeta;

const row = {
  id: 9,
  ledger_kind: "branch",
  number: "TR-9",
  from_location: "branch:1",
  to_location: "branch:2",
  from_name: "الفرع الرئيسي",
  to_name: "فرع المنصور",
  status: "sent",
  quantity: 5,
  note: "",
  created_at: null,
  revision: "rev-7",
  can_send: false,
  can_receive: true,
  can_cancel: false,
  lines: [
    {
      id: 51,
      product_id: 7,
      name: "سماعة",
      variant_name: "أسود",
      quantity: 3,
      received: 0,
      residual: 3,
      cost: null,
    },
    {
      id: 52,
      product_id: 8,
      name: "شاحن",
      variant_name: "",
      quantity: 2,
      received: 0,
      residual: 2,
      cost: null,
    },
  ],
} as unknown as StockTransferDetail;

function mount(phase: "receive_partial" | "resolve", detail: StockTransferDetail = row) {
  const sent: FinoraRequest[] = [];
  const bridge = installMockBridge((request: FinoraRequest) => {
    if (request.method === "POST") {
      sent.push(request);
      return {
        ok: true as const,
        status: 200,
        data: {
          success: true,
          data: { id: 9, type: "stock_transfer", ledger_kind: "branch", status: "received" },
          operation_id: "0dd34551-6f1a-4500-8aef-21a7415ad7c3",
        },
        customerCommandScope: "scope",
      };
    }
    return { ok: true as const, status: 200, data: { success: true, data: { items: [] } } };
  });
  const target = window.finoraDesktop;
  if (target)
    target.stockRecovery = {
      list: vi.fn(async () => ({ available: true, items: [] })),
      retry: vi.fn(async (): Promise<never> => {
        throw Error("not requested");
      }),
      acknowledge: vi.fn(async () => undefined),
    };
  const onSaved = vi.fn();
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <StockForms
        mode={{ kind: "phase", phase, row: detail }}
        meta={meta}
        location="branch:2"
        scope="s"
        active
        serverUrl={null}
        onClose={() => undefined}
        onSaved={onSaved}
      />
    </QueryClientProvider>,
  );
  return { bridge, sent, onSaved };
}

it("receives only what arrived: per-line quantities go to the server with the revision", async () => {
  const { sent, onSaved } = mount("receive_partial");
  const user = userEvent.setup();
  expect(await screen.findByText("استلام جزئي للتحويل")).toBeInTheDocument();
  const headset = screen.getByLabelText("الكمية المستلمة من سماعة");
  expect(headset).toHaveValue(3); // defaults to everything sent
  await user.clear(headset);
  await user.type(headset, "2");
  await user.clear(screen.getByLabelText("الكمية المستلمة من شاحن"));
  await user.type(screen.getByLabelText("الكمية المستلمة من شاحن"), "0");
  await user.type(screen.getByLabelText("سبب العملية المخزنية"), "وصل الصندوق ناقصاً");
  await user.click(screen.getByRole("button", { name: "تأكيد وحفظ" }));
  await waitFor(() => expect(onSaved).toHaveBeenCalled());
  expect(sent[0]).toMatchObject({
    method: "POST",
    path: "/api/v1/desktop/stock-operations/branch/transfers/9/receive_partial",
    body: {
      revision: "rev-7",
      reason: "وصل الصندوق ناقصاً",
      lines: [
        { line_id: 51, received: 2 },
        { line_id: 52, received: 0 },
      ],
    },
  });
});

it("asks for the fate of every remaining quantity and sends one decision per line", async () => {
  const partial = {
    ...row,
    status: "partially_received",
    lines: [
      { ...row.lines[0], received: 2, residual: 1 },
      { ...row.lines[1], received: 2, residual: 0 }, // fully received: nothing to decide
    ],
  } as unknown as StockTransferDetail;
  const { sent } = mount("resolve", partial);
  const user = userEvent.setup();
  const list = await screen.findByRole("list", { name: "مصير الكميات المتبقية" });
  expect(within(list).getAllByRole("listitem")).toHaveLength(1);
  await user.selectOptions(within(list).getByLabelText("مصير المتبقي من سماعة"), "loss");
  await user.type(screen.getByLabelText("سبب العملية المخزنية"), "تلف بالشحن");
  await user.click(screen.getByRole("button", { name: "تأكيد وحفظ" }));
  await waitFor(() => expect(sent).toHaveLength(1));
  expect(sent[0]).toMatchObject({
    path: "/api/v1/desktop/stock-operations/branch/transfers/9/resolve",
    body: { revision: "rev-7", lines: [{ line_id: 51, action: "loss" }] },
  });
});
