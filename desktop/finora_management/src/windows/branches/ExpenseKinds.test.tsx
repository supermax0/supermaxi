import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { FinoraRequest } from "@shared/ipc";
import { installMockBridge, removeMockBridge } from "@/test/mockBridge";
import { ExpenseKinds } from "./ExpenseKinds";

const BASE = "/api/v1/desktop/branches";
const ok = (data: unknown) => ({ ok: true as const, status: 200, data: { ok: true, ...(data as object) } });
const expense = {
  id: 7,
  title: "إيجار المقر",
  category: null,
  category_key: "rent",
  category_label: "إيجار",
  category_icon: "",
  amount: 1000,
  note: "",
  base_note: "",
  expense_date: "2026-10-10",
  post_time: "",
  treasury_account_id: null,
  treasury_account_name: "",
  cash_posted: true,
  status: "posted",
  repeat_index: null,
  repeat_total: null,
  repeat_series_id: null,
  is_payroll: false,
  created_at: "",
};

afterEach(removeMockBridge);

it("classifies an expense as central through the server and leaves the expense untouched", async () => {
  const bridge = installMockBridge((r: FinoraRequest) => {
    if (r.path === "/expenses/api/page")
      return {
        ok: true as const,
        status: 200,
        data: {
          success: true,
          rows: [expense],
          page: 1,
          page_size: 50,
          total: 1,
          total_pages: 1,
          counts: { all: 1, posted: 1, scheduled: 0 },
          summary: {
            today_total: 0,
            month_total: 0,
            year_total: 0,
            scheduled_total: 0,
            scheduled_count: 0,
            filtered_total: 1000,
          },
          by_category: [],
        },
      };
    if (r.path === `${BASE}/expense-allocation/assignments`) return ok({ rows: {} });
    if (r.path === `${BASE}/expense-allocation/7`) return ok({ expense_id: 7, kind: "central", lines: [] });
    if (r.path === `${BASE}/meta`)
      return ok({
        multi_branch: { enabled: true, explicit: true, active_branches: 2 },
        primary_branch_id: 1,
        can_manage: true,
        types: [],
        current_branch_id: null,
        scope: { can_switch: true, view_all: true, branches: [] },
      });
    return { ok: false, failure: "http", status: 404, data: { error: "not found" } };
  });
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ExpenseKinds enabled from="2026-10-01" to="2026-10-31" />
    </QueryClientProvider>,
  );
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "خاص بفرع" }));
  await user.selectOptions(await screen.findByRole("combobox", { name: "نوع المصروف" }), "central");
  await user.click(screen.getByRole("button", { name: "حفظ" }));
  await waitFor(() =>
    expect(
      bridge.finora.request.mock.calls.find(([r]) => r.path === `${BASE}/expense-allocation/7`)?.[0].body,
    ).toMatchObject({ kind: "central" }),
  );
});
