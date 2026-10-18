import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { finoraRequestSchema, type FinoraRequest } from "@shared/ipc";
import { BranchScopeSwitcher } from "@/components/BranchScopeSwitcher";
import { useConnection } from "@/stores/connection";
import { useSession } from "@/stores/session";
import { useWindowManager } from "@/stores/windowManager";
import { installMockBridge, removeMockBridge, SESSION_PAYLOAD } from "@/test/mockBridge";
import { BranchesWindow } from "./BranchesWindow";

const BASE = "/api/v1/desktop/branches";
const ok = (data: unknown) => ({ ok: true as const, status: 200, data: { ok: true, ...(data as object) } });

const branch = (id: number, name: string, extra: object = {}) => ({
  id,
  code: `B${id}`,
  name,
  address: "",
  phone: "",
  is_active: true,
  is_default: id === 1,
  created_at: "2026-01-01 09:00",
  short_name: "",
  branch_type: "sales",
  branch_type_label: "فرع مبيعات",
  governorate: "بغداد",
  city: "الكرادة",
  email: "",
  manager_name: "علي",
  opened_on: "",
  archived_at: "",
  archive_reason: "",
  stats: {
    sales_total: 1_000_000 * id,
    orders: 3,
    open_orders: 1,
    stock_value: 500_000,
    cash: 250_000,
    last_activity: "",
  },
  ...extra,
});

function meta(over: { enabled?: boolean; canSwitch?: boolean; viewAll?: boolean } = {}) {
  return {
    multi_branch: { enabled: over.enabled ?? true, explicit: true, active_branches: 2 },
    primary_branch_id: 1,
    can_manage: true,
    types: [{ id: "sales", label: "فرع مبيعات" }],
    current_branch_id: 1,
    scope: {
      can_switch: over.canSwitch ?? true,
      view_all: over.viewAll ?? false,
      branches: [
        { id: 1, name: "الفرع الرئيسي", code: "B1", is_default: true },
        { id: 2, name: "فرع المنصور", code: "B2", is_default: false },
      ],
    },
  };
}

function setup(options: { metaBody?: ReturnType<typeof meta>; ui: React.ReactNode }) {
  useSession.setState({ status: "signed_in", session: { ...SESSION_PAYLOAD } as never } as never);
  useWindowManager.setState({ active: "branches" });
  const bridge = installMockBridge((request: FinoraRequest) => {
    if (request.path === `${BASE}/meta`) return ok(options.metaBody ?? meta());
    if (request.path === BASE && request.method === "GET")
      return ok({
        rows: [
          branch(1, "الفرع الرئيسي"),
          branch(2, "فرع المنصور"),
          branch(3, "فرع البصرة", { stats: { ...branch(3, "").stats, cash: null } }),
        ],
        multi_branch: { enabled: true, explicit: true, active_branches: 3 },
      });
    if (request.path === `${BASE}/switch`) return ok({});
    if (request.path === `${BASE}/feature`)
      return ok({ multi_branch: { enabled: true, explicit: true, active_branches: 1 } });
    return { ok: false, failure: "http", status: 404, data: { error: "not found" } };
  });
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      {options.ui}
    </QueryClientProvider>,
  );
  return bridge;
}

afterEach(() => {
  removeMockBridge();
  useConnection.setState({ status: "online" });
});

it("shows the scope selector only for multi-branch companies and switches the view scope on the server", async () => {
  const bridge = setup({ ui: <BranchScopeSwitcher /> });
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: /نطاق العمل: الفرع الرئيسي/ }));
  await user.click(await screen.findByRole("option", { name: /فرع المنصور/ }));
  await waitFor(() =>
    expect(bridge.finora.request.mock.calls.find(([r]) => r.path === `${BASE}/switch`)?.[0].body).toEqual({
      branch_id: 2,
    }),
  );
  for (const [request] of bridge.finora.request.mock.calls)
    expect(finoraRequestSchema.safeParse(request).success).toBe(true);
});

it("shared-branch mode says «كل الفروع (مشتركة)» instead of naming the main branch", async () => {
  const shared = meta({ canSwitch: false });
  (shared.scope as Record<string, unknown>).shared = true;
  setup({ metaBody: shared, ui: <BranchScopeSwitcher /> });
  expect(await screen.findByText("كل الفروع (مشتركة)")).toBeInTheDocument();
  expect(screen.queryByText("الفرع الرئيسي")).not.toBeInTheDocument();
});

it("renders nothing for a single-branch company or a user tied to one branch", async () => {
  const disabled = meta({ enabled: false });
  const { container } = (() => {
    setup({ metaBody: disabled, ui: <BranchScopeSwitcher /> });
    return { container: document.body };
  })();
  await waitFor(() => expect(container.querySelector('[aria-haspopup="listbox"]')).toBeNull());
});

it("lists branches with live totals, never fakes an unavailable balance, and turns the feature on without data", async () => {
  const bridge = setup({ ui: <BranchesWindow /> });
  expect(await screen.findByText("فرع البصرة")).toBeInTheDocument();
  expect(screen.getAllByText("غير متاح")).toHaveLength(2); // Basra's row cell + the company cash total
  // company totals: 1+2+3 million of sales, but cash total is unknown because one branch is unknown
  expect(screen.getByText("مبيعات الشركة").closest("div")).toHaveTextContent("6,000,000");
  expect(screen.getByText(/إجمالي النقد/).closest("div")).toHaveTextContent("غير متاح");
  expect(bridge.finora.request.mock.calls.some(([r]) => r.path === `${BASE}/feature`)).toBe(false);
});

it("explains the simple mode and enables multi-branch with one button", async () => {
  const bridge = setup({ metaBody: meta({ enabled: false }), ui: <BranchesWindow /> });
  const user = userEvent.setup();
  const banner = await screen.findByText("تعدد الفروع غير مفعّل");
  expect(within(banner.closest("section") as HTMLElement).getByText(/لا يغيّر أي رصيد/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /فرع جديد/ })).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "تفعيل تعدد الفروع" }));
  await waitFor(() =>
    expect(bridge.finora.request.mock.calls.find(([r]) => r.path === `${BASE}/feature`)?.[0].body).toEqual({
      enabled: true,
    }),
  );
});
