import { QueryClient } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MotionGlobalConfig } from "framer-motion";
import { App } from "@/app/App";
import { useSession } from "@/stores/session";
import { useWindowManager } from "@/stores/windowManager";
import { createFinoraFixture } from "@/test/fixtures";
import { installMockBridge, removeMockBridge } from "@/test/mockBridge";

beforeAll(() => {
  MotionGlobalConfig.skipAnimations = true;
});

afterEach(() => {
  removeMockBridge();
  useWindowManager.getState().reset();
  useSession.setState({ status: "unknown", session: null, reason: null });
});

async function openReports() {
  const fixture = createFinoraFixture();
  const bridge = installMockBridge(fixture.handler);
  render(<App queryClient={new QueryClient({ defaultOptions: { queries: { retry: false } } })} />);
  await screen.findByRole("navigation", { name: "النوافذ" });
  act(() => useWindowManager.getState().open("reports"));
  const win = await screen.findByRole("dialog", { name: "التقارير" });
  return { fixture, bridge, win };
}

describe("Reports", () => {
  it("shows the six KPIs with meaning-based colours and the dashboard sections", async () => {
    const { win } = await openReports();
    const sales = await within(win).findByRole("button", { name: "المبيعات — فتح التقرير" });
    expect(sales).toHaveTextContent("2,480,000");
    expect(sales).toHaveTextContent("+12.6%");
    // expenses went up: shown as bad news (red), not green
    const expenses = within(win).getByRole("button", { name: "المصاريف — فتح التقرير" });
    expect(within(expenses).getByText("+4.8%").parentElement).toHaveClass("text-danger");
    // point-in-time balances never invent a comparison
    const debts = within(win).getByRole("button", { name: "ديون العملاء — فتح التقرير" });
    expect(within(debts).getByText("لا تتوفر مقارنة")).toBeInTheDocument();
    expect(within(win).getByRole("img", { name: "حركة المبيعات" })).toBeInTheDocument();
    expect(within(win).getByRole("region", { name: "حركة المبيعات" })).toBeInTheDocument();
    expect(within(win).getByRole("img", { name: "مقارنة الفترات" })).toBeInTheDocument();
    expect(within(win).getByRole("region", { name: "الأرباح والخسائر" })).toHaveTextContent("1,017,000");
  });

  it("the financial position report shows equity and where the profit went", async () => {
    const { win } = await openReports();
    const user = userEvent.setup();
    await within(win).findByRole("button", { name: "المبيعات — فتح التقرير" });
    await user.click(within(win).getByRole("button", { name: "نوع التقرير" }));
    await user.click(await screen.findByRole("option", { name: "المركز المالي وأين ذهبت الأرباح" }));
    const position = await within(win).findByRole("table", { name: "المركز المالي" });
    expect(position).toHaveTextContent("72,339,050");
    const bridge = within(win).getByRole("table", { name: "أين ذهب الربح" });
    expect(bridge).toHaveTextContent("سحوبات المالك");
    expect(bridge).not.toHaveTextContent("بقي عند الزبائن"); // zero lines are left out
    expect(within(win).getByRole("list", { name: "ملخص أين ذهبت الأرباح" })).toHaveTextContent(
      "تحول إلى بضاعة في المخازن",
    );
  });

  it("drill-down opens the detail report on the same period and branch", async () => {
    const { win, fixture } = await openReports();
    const user = userEvent.setup();
    await within(win).findByRole("button", { name: "المبيعات — فتح التقرير" });
    await user.click(within(win).getByRole("button", { name: "الفترة الزمنية" }));
    await user.click(await screen.findByRole("option", { name: "الشهر السابق" }));
    await user.click(within(win).getByRole("button", { name: "الفرع" }));
    await user.click(await screen.findByRole("option", { name: "فرع الكرادة" }));
    expect(within(win).getByRole("button", { name: "الفرع" })).toHaveTextContent("فرع الكرادة");
    await waitFor(() =>
      expect(
        fixture.calls.some((c) => c.path === "/reports/api/v2/dashboard" && c.query?.branch_id === 2),
      ).toBe(true),
    );
    await user.click(within(win).getByRole("button", { name: "فتح تفاصيل المبيعات" }));
    expect(await within(win).findByRole("heading", { name: "المبيعات" })).toBeInTheDocument();
    await waitFor(() => {
      const call = fixture.calls.find((c) => c.path === "/reports/api/v2/section/sales");
      expect(call?.query).toMatchObject({ period: "last_month", branch_id: 2 });
    });
    expect(await within(win).findByRole("table", { name: "فواتير المبيعات" })).toHaveTextContent("#10045");
  });

  it("exports the open report to Excel with the active filters and view", async () => {
    const { win, bridge } = await openReports();
    const user = userEvent.setup();
    await user.click(await within(win).findByRole("button", { name: "فتح تفاصيل المبيعات" }));
    await within(win).findByRole("table", { name: "فواتير المبيعات" });
    await user.click(within(win).getByRole("radio", { name: "المنتج" }));
    await user.click(within(win).getByRole("button", { name: "Excel — المبيعات" }));
    await waitFor(() =>
      expect(bridge.reports.export).toHaveBeenCalledWith({
        section: "sales",
        format: "xlsx",
        title: "المبيعات",
        query: { period: "this_month", by: "product" },
      }),
    );
  });

  it("employee list: search (Arabic-insensitive) and keyboard choice", async () => {
    const { win, fixture } = await openReports();
    const user = userEvent.setup();
    await within(win).findByRole("button", { name: "المبيعات — فتح التقرير" });
    await user.click(within(win).getByRole("button", { name: "الموظف" }));
    const search = await screen.findByRole("textbox", { name: "بحث في الموظف" });
    await waitFor(() => expect(search).toHaveFocus());
    await user.type(search, "ساره");
    const list = screen.getByRole("listbox", { name: "الموظف" });
    await waitFor(() =>
      expect(
        within(list)
          .getAllByRole("option")
          .map((o) => o.textContent),
      ).toEqual(["سارة"]),
    );
    await user.keyboard("{Enter}");
    expect(screen.queryByRole("listbox", { name: "الموظف" })).not.toBeInTheDocument();
    expect(within(win).getByRole("button", { name: "الموظف" })).toHaveTextContent("سارة");
    await waitFor(() =>
      expect(
        fixture.calls.some((c) => c.path === "/reports/api/v2/dashboard" && c.query?.employee_id === 7),
      ).toBe(true),
    );
  });
});
