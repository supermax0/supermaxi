import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { FinoraRequest } from "@shared/ipc";
import { useConnection } from "@/stores/connection";
import { useSession } from "@/stores/session";
import { useWindowManager } from "@/stores/windowManager";
import { installMockBridge, removeMockBridge, SESSION_PAYLOAD } from "@/test/mockBridge";
import { ExpensesWindow } from "./ExpensesWindow";

const META = {
  success: true,
  categories: [
    { key: "rent", label: "إيجار", icon: "🏠", builtin: true },
    { key: "electricity", label: "كهرباء", icon: "⚡", builtin: true },
  ],
  treasury_accounts: [{ id: 3, name: "الصندوق", type: "cash", is_default: true, branch_name: "مشترك" }],
  today: "2026-10-15",
};
const row = {
  id: 41,
  title: "إيجار المحل",
  category: "rent",
  category_key: "rent",
  category_label: "إيجار",
  category_icon: "🏠",
  amount: 750000,
  note: "",
  base_note: "",
  expense_date: "2026-10-15",
  post_time: "",
  treasury_account_id: 3,
  treasury_account_name: "الصندوق",
  cash_posted: true,
  status: "posted",
  repeat_index: null,
  repeat_total: null,
  repeat_series_id: null,
  is_payroll: false,
  created_at: "2026-10-15 09:00",
};
const PAGE = {
  success: true,
  rows: [row],
  page: 1,
  page_size: 25,
  total: 1,
  total_pages: 1,
  counts: { all: 1, posted: 1, scheduled: 0 },
  summary: {
    today_total: 750000,
    month_total: 920000,
    year_total: 4100000,
    scheduled_total: 120000,
    scheduled_count: 2,
    filtered_total: 750000,
  },
  by_category: [{ key: "rent", label: "إيجار", icon: "🏠", amount: 750000, count: 1 }],
};

function setup(permissions: string[] = ["view_expenses"]) {
  useSession.setState({
    status: "signed_in",
    session: { ...SESSION_PAYLOAD, permissions } as never,
  } as never);
  useWindowManager.setState({ active: "expenses" });
  const bridge = installMockBridge((request: FinoraRequest) => {
    if (request.path === "/expenses/api/meta") return { ok: true, status: 200, data: META };
    if (request.path === "/expenses/api/page") return { ok: true, status: 200, data: PAGE };
    if (request.path === "/expenses/api/create")
      return {
        ok: true,
        status: 200,
        data: {
          success: true,
          message: "تم تسجيل 12 مصروف وخصم 30,000 من الصندوق (1 مستحق).",
          ids: [1],
          count: 12,
          posted_count: 1,
          scheduled_count: 11,
          amount_withdrawn: 30000,
        },
      };
    if (request.path === "/expenses/delete/41") return { ok: true, status: 200, data: { success: true } };
    return { ok: false, failure: "http", status: 404, data: { error: "not found" } };
  });
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ExpensesWindow />
    </QueryClientProvider>,
  );
  return bridge;
}

afterEach(() => {
  removeMockBridge();
  useConnection.setState({ status: "online" });
});

it("shows period totals, the expenses table and the category breakdown", async () => {
  setup();
  expect(await screen.findByText("إيجار المحل")).toBeInTheDocument();
  expect(screen.getByText("مصاريف هذا الشهر").closest("button, div")).toHaveTextContent("920,000");
  expect(screen.getByText("مجدولة (2)")).toBeInTheDocument();
  expect(screen.getByText("مخصوم")).toBeInTheDocument();
  const breakdown = screen.getByRole("complementary", { name: "توزيع المصاريف حسب الفئة" });
  expect(within(breakdown).getByText("100%")).toBeInTheDocument();
});

it("creates a recurring expense with FINORA's own rules and reports its answer", async () => {
  const bridge = setup();
  const user = userEvent.setup();
  await screen.findByText("إيجار المحل");
  await user.click(screen.getByRole("button", { name: "إضافة مصروف" }));
  const dialog = await screen.findByRole("dialog", { name: "إضافة مصروف" });
  const save = within(dialog).getByRole("button", { name: "حفظ المصروف" });
  expect(save).toBeDisabled();
  await user.type(within(dialog).getByPlaceholderText(/مثال/), "اشتراك الإنترنت");
  await user.type(within(dialog).getByLabelText("مبلغ المصروف"), "30000");
  await user.click(within(dialog).getByRole("radio", { name: /كهرباء/ }));
  await user.click(within(dialog).getByRole("checkbox"));
  expect(within(dialog).getByText(/سيُسجَّل/)).toHaveTextContent("12");
  await user.click(save);
  await waitFor(() =>
    expect(
      bridge.finora.request.mock.calls.find(([r]) => r.path === "/expenses/api/create")?.[0],
    ).toMatchObject({
      method: "POST",
      body: {
        title: "اشتراك الإنترنت",
        category: "electricity",
        amount: 30000,
        expense_date: "2026-10-15",
        treasury_account_id: 3,
        repeat_enabled: true,
        repeat_unit: "months",
        repeat_count: 12,
      },
    }),
  );
  await waitFor(() => expect(screen.queryByRole("dialog", { name: "إضافة مصروف" })).not.toBeInTheDocument());
});

it("deletes after confirmation and explains the treasury refund", async () => {
  const bridge = setup();
  const user = userEvent.setup();
  await screen.findByText("إيجار المحل");
  await user.click(screen.getByRole("button", { name: "إجراءات إيجار المحل" }));
  await user.click(await screen.findByRole("menuitem", { name: "حذف المصروف" }));
  const confirm = await screen.findByRole("dialog", { name: "حذف المصروف" });
  expect(confirm).toHaveTextContent("سيُعاد المبلغ إلى الحساب");
  await user.click(within(confirm).getByRole("button", { name: "حذف المصروف" }));
  await waitFor(() =>
    expect(bridge.finora.request.mock.calls.some(([r]) => r.path === "/expenses/delete/41")).toBe(true),
  );
});

it("tells users without the permission instead of calling FINORA", () => {
  const bridge = setup(["can_see_orders"]);
  expect(screen.getByText("لا تملك صلاحية عرض المصاريف")).toBeInTheDocument();
  expect(bridge.finora.request).not.toHaveBeenCalled();
});
