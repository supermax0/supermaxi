import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { finoraRequestSchema, type FinoraRequest } from "@shared/ipc";
import { useConnection } from "@/stores/connection";
import { useFinanceNavigation } from "@/stores/financeNavigation";
import { useOrderNavigation } from "@/stores/orderNavigation";
import { useSession } from "@/stores/session";
import { useWindowManager } from "@/stores/windowManager";
import { installMockBridge, removeMockBridge, SESSION_PAYLOAD } from "@/test/mockBridge";
import { CustomerTransactions } from "./CustomerTransactions";

function setup(
  permissions: ("finance.view" | "can_see_orders")[] = ["finance.view", "can_see_orders"],
  historical = false,
  complete = true,
) {
  const requests: FinoraRequest[] = [];
  const row = {
    kind: "voucher",
    id: 1,
    date: "2026-10-11",
    description: "تسوية رصيد مقدم",
    document: "ST-000001",
    amount: 75000,
    cash: 0,
    debt_change: -75000,
    advance_change: -75000,
    invoice_id: null,
    plan_id: null,
    voucher_id: 1,
    status: "posted",
    note: "",
  };
  const bridge = installMockBridge((request) => {
    finoraRequestSchema.parse(request);
    requests.push(request);
    if (request.method !== "GET") throw Error("A collection-history read must not post money");
    return {
      ok: true,
      status: 200,
      data: {
        success: true,
        data: {
          items: [
            historical
              ? {
                  ...row,
                  kind: "debt_origin",
                  net_change: 0,
                  debt_balance: complete ? 375000 : null,
                  advance_balance: complete ? 15000 : null,
                  net_balance: complete ? 360000 : null,
                }
              : row,
          ],
          total: 32,
          page: Number(request.query?.page ?? 1),
          page_size: 25,
          as_of: "2026-10-11",
          summary: {
            debt: 375000,
            advance: 15000,
            net_due: 360000,
            unexplained_documents: 1,
            unexplained_amount: 100000,
            ...(historical
              ? {
                  opening_net: complete ? 0 : null,
                  closing_net: complete ? 360000 : null,
                  debits: 0,
                  credits: 0,
                }
              : {}),
          },
          ...(historical
            ? {
                coverage: {
                  complete,
                  missing_origins: complete ? 0 : 1,
                  archived_documents: 0,
                  malformed_sources: 0,
                  undated_movements: 0,
                  unplaced_debt: complete ? 0 : 375000,
                  unplaced_advance: 0,
                  balance_basis: "day_end",
                  date_from: null,
                  date_to: null,
                },
              }
            : {}),
        },
      },
    };
  });
  useSession.getState().signedIn({ ...SESSION_PAYLOAD, permissions });
  useConnection.getState().setStatus("online");
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const close = vi.fn();
  const view = render(
    <QueryClientProvider client={client}>
      <CustomerTransactions
        customerId={8}
        customerName="علي"
        onClose={close}
        onSchedule={vi.fn()}
        historical={historical}
      />
    </QueryClientProvider>,
  );
  return {
    requests,
    bridge,
    close,
    dispose: () => {
      view.unmount();
      client.clear();
    },
  };
}
afterEach(() => {
  removeMockBridge();
  useSession.setState({ status: "unknown", session: null });
  useConnection.getState().setStatus("online");
  useFinanceNavigation.getState().clear();
  useOrderNavigation.getState().clear();
  useWindowManager.getState().reset();
});

it("shows settlement with zero cash, warns about incomplete history, and pages without mutations", async () => {
  const test = setup();
  await screen.findByText("تسوية رصيد مقدم");
  expect(screen.getByRole("alert")).toHaveTextContent("لا تمثل حركة قبض جديدة");
  const cells = screen.getByText("تسوية رصيد مقدم").closest("tr")?.querySelectorAll("td");
  expect(cells?.[3]).toHaveTextContent("0 د.ع");
  await userEvent.click(screen.getByRole("button", { name: "الصفحة التالية" }));
  await waitFor(() => expect(test.requests.some((request) => request.query?.page === 2)).toBe(true));
  await userEvent.click(screen.getByRole("button", { name: "طباعة الحركات / PDF" }));
  expect(test.bridge.print.open).toHaveBeenCalledWith({ kind: "customer_transactions", id: 8 });
  expect(test.requests.every((request) => request.method === "GET")).toBe(true);
  test.dispose();
});

it("historical periods keep source navigation, read-only requests and matching print filters", async () => {
  const test = setup(undefined, true);
  await screen.findByText("رصيد نهاية اليوم");
  fireEvent.change(screen.getByLabelText("بداية فترة الكشف"), { target: { value: "2026-01-01" } });
  await waitFor(() => expect(test.requests.at(-1)?.query?.date_from).toBe("2026-01-01"));
  await userEvent.click(screen.getByRole("button", { name: "طباعة الحركات / PDF" }));
  expect(test.bridge.print.open).toHaveBeenCalledWith({
    kind: "customer_history",
    id: 8,
    date_from: "2026-01-01",
  });
  expect(test.requests.every((request) => request.method === "GET")).toBe(true);
  test.dispose();
});
it("unknown historical origins never show an invented opening or closing balance", async () => {
  const test = setup(undefined, true, false);
  await screen.findByText(/التاريخ غير مكتمل؛ الأرصدة التاريخية غير مثبتة/);
  expect(screen.getByText(/رصيد بداية الفترة/)).toHaveTextContent("غير مثبت");
  test.dispose();
});
it("only opens a source voucher with finance permission and never opens a collection editor", async () => {
  const test = setup();
  await screen.findByRole("button", { name: "ST-000001" });
  await userEvent.click(screen.getByRole("button", { name: "ST-000001" }));
  expect(useFinanceNavigation.getState().voucherId).toBe(1);
  expect(useFinanceNavigation.getState().collection).toBeNull();
  expect(useWindowManager.getState().active).toBe("finance");
  expect(test.close).toHaveBeenCalledOnce();
  test.dispose();
});

it("keeps source navigation permission scoped, disables offline printing, and closes help before the table", async () => {
  const test = setup([]);
  await screen.findByRole("button", { name: "ST-000001" });
  expect(screen.getByRole("button", { name: "ST-000001" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "شرح حركات التحصيل" }));
  fireEvent.keyDown(window, { key: "Escape" });
  expect(test.close).not.toHaveBeenCalled();
  await waitFor(() => expect(document.querySelector("[data-popover]")).toBeNull());
  act(() => useConnection.getState().setStatus("offline"));
  await waitFor(() => expect(screen.getByRole("button", { name: "طباعة الحركات / PDF" })).toBeDisabled());
  expect(screen.getByRole("button", { name: "تصدير كل الحركات" })).toBeDisabled();
  fireEvent.keyDown(window, { key: "Escape" });
  expect(test.close).toHaveBeenCalledOnce();
  test.dispose();
});
