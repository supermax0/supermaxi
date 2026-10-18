import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { finoraRequestSchema, type FinoraRequest } from "@shared/ipc";
import { useConnection } from "@/stores/connection";
import { installMockBridge, removeMockBridge } from "@/test/mockBridge";
import { CashTransfers } from "./CashTransfers";

const BASE = "/api/v1/desktop/branch-cash";
const ok = (data: unknown) => ({ ok: true as const, status: 200, data: { ok: true, ...(data as object) } });

const doc = (over: object = {}) => ({
  id: 4,
  number: "BCT-20261016-0001",
  status: "approved",
  status_label: "معتمد — بانتظار تأكيد الاستلام",
  amount: 500000,
  currency: "IQD",
  from_account: "صندوق الرئيسي",
  to_account: "صندوق المنصور",
  from_branch: "الفرع الرئيسي",
  to_branch: "فرع المنصور",
  from_branch_id: 1,
  to_branch_id: 2,
  transfer_date: "2026-10-16",
  reference: "",
  reason: "تغذية الصندوق",
  notes: "",
  requested_by: "علي",
  approved_by: "المدير",
  received_by: "",
  closed_reason: "",
  created_at: "2026-10-16 10:00",
  completed_at: "",
  posted: false,
  events: [{ action: "create", name: "علي", at: "2026-10-16 10:00" }],
  can_approve: false,
  can_receive: true,
  can_reject: true,
  can_cancel: false,
  ...over,
});

function setup(rows = [doc()]) {
  const bridge = installMockBridge((request: FinoraRequest) => {
    if (request.path === `${BASE}/meta`)
      return ok({
        accounts: [
          {
            id: 10,
            name: "صندوق الرئيسي",
            type: "cash",
            branch_id: 1,
            branch_name: "الفرع الرئيسي",
            can_send_from: true,
            balance: 2_450_000,
          },
          {
            id: 20,
            name: "صندوق المنصور",
            type: "cash",
            branch_id: 2,
            branch_name: "فرع المنصور",
            can_send_from: false,
            balance: null,
          },
        ],
        can_execute_now: true,
        pending: { count: 1, amount: 500000 },
      });
    if (request.path === BASE && request.method === "GET")
      return ok({ rows, pending: { count: rows.length, amount: 500000 } });
    if (request.path === BASE && request.method === "POST")
      return ok({
        transfer: doc({ status: "pending", status_label: "بانتظار الاعتماد", can_receive: false }),
      });
    if (request.path.endsWith("/receive"))
      return ok({ transfer: doc({ status: "completed", status_label: "مكتمل", posted: true }) });
    return { ok: false, failure: "http", status: 404, data: { error: "not found" } };
  });
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <CashTransfers enabled />
    </QueryClientProvider>,
  );
  return bridge;
}

afterEach(() => {
  removeMockBridge();
  useConnection.setState({ status: "online" });
});

it("shows only the actions the server allows and confirms receipt with one valid request", async () => {
  const bridge = setup();
  const user = userEvent.setup();
  expect(await screen.findByText("BCT-20261016-0001")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /اعتماد/ })).not.toBeInTheDocument(); // can_approve is false
  await user.click(screen.getByRole("button", { name: /تأكيد الاستلام/ }));
  await waitFor(() =>
    expect(bridge.finora.request.mock.calls.some(([r]) => r.path === `${BASE}/4/receive`)).toBe(true),
  );
  for (const [request] of bridge.finora.request.mock.calls)
    expect(finoraRequestSchema.safeParse(request).success).toBe(true);
});

it("creates a request with a replay-safe operation id and blocks an amount above the visible balance", async () => {
  const bridge = setup([]);
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: /تحويل أموال/ }));
  const dialog = await screen.findByRole("dialog", { name: "تحويل أموال بين الفروع" });
  const submit = within(dialog).getByRole("button", { name: "إرسال الطلب" });
  expect(submit).toBeDisabled(); // no amount / reason yet
  await user.type(within(dialog).getByLabelText("مبلغ التحويل"), "9000000");
  expect(within(dialog).getByText(/المبلغ يتجاوز الرصيد/)).toBeInTheDocument();
  expect(submit).toBeDisabled();
  await user.clear(within(dialog).getByLabelText("مبلغ التحويل"));
  await user.type(within(dialog).getByLabelText("مبلغ التحويل"), "500000");
  await user.type(within(dialog).getByRole("textbox", { name: "السبب" }), "تغذية الصندوق");
  await waitFor(() => expect(submit).toBeEnabled());
  await user.click(submit);
  await waitFor(() => {
    const call = bridge.finora.request.mock.calls.find(([r]) => r.method === "POST" && r.path === BASE);
    expect(call?.[0].body).toMatchObject({
      from_account_id: 10,
      to_account_id: 20,
      amount: 500000,
      reason: "تغذية الصندوق",
    });
    expect(String((call?.[0].body as { operation_id?: string }).operation_id)).toMatch(/^[0-9a-f-]{36}$/);
  });
});
