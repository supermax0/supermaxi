import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MotionGlobalConfig } from "framer-motion";
import { vi } from "vitest";
import type { FinoraSession } from "@/api/finora";
import type { FinoraResponse } from "@shared/ipc";
import { finoraRequestSchema } from "@shared/ipc";
import { workspaceApi } from "@/api/finora/workspace";
import { useSession } from "@/stores/session";
import { useWindowManager } from "@/stores/windowManager";
import { useHRNavigation } from "@/stores/hrNavigation";
import { installMockBridge, removeMockBridge } from "@/test/mockBridge";
import { SmartWorkspace } from "./SmartWorkspace";
import { defaultPreferences, useWorkspace, type WorkspaceTarget } from "./state";
import { openWorkspaceTarget, useWorkspaceRequest } from "./navigation";

const session: FinoraSession = {
  user: { id: 1, name: "موظف", username: "test", role: "admin" },
  tenant: { id: 1, slug: "one", name: "شركة اختبار", business_type: "general" },
  branch: { id: 1, name: "الأول" },
  branch_scope: "branch",
  roles: [],
  permissions: [
    "view_reports",
    "manage_customers",
    "can_see_orders",
    "can_manage_inventory",
    "view_pos",
    "view_expenses",
    "finance.view",
    "finance.create",
    "inventory.audit.view",
  ],
  session_max_age_seconds: 3600,
};
const ok = (data: unknown): FinoraResponse => ({ ok: true, status: 200, data });
function setup(failedSales = false, allCountsOnly = false) {
  const bridge = installMockBridge((request) => {
    if (request.path.endsWith("/workspace/sales"))
      return failedSales
        ? { ok: false, failure: "http", status: 500, data: {} }
        : ok({
            ok: true,
            value: 4850000,
            previous: 3980000,
            change: 21.9,
            date: "2026-10-20",
            captured_at: "2026-10-20T08:00:00Z",
          });
    if (request.path.endsWith("/workspace/receivables"))
      return ok({
        ok: true,
        value: 2450000,
        overdue: 100000,
        debtors: 3,
        captured_at: "2026-10-20T08:00:00Z",
      });
    if (request.path.endsWith("/workspace/activity")) return ok({ ok: true, rows: [], has_more: false });
    if (request.path === "/hr/api/notifications") {
      const item = {
        key: "correction:7",
        type: "correction",
        title: "طلب تصحيح دوام بانتظار الموافقة",
        body: "يحتاج مراجعة",
        date: "2026-10-20",
        tone: "warning",
        tab: "corrections",
        person_id: 7,
        month: "2026-10",
      };
      return ok({ total: 2, items: [item, item] });
    }
    if (request.path === "/orders/api/counts")
      return ok({
        success: true,
        counts: allCountsOnly ? { all: 24 } : { all: 24, ordered: 8, packed: 12, shipping: 4 },
      });
    if (request.path === "/inventory/api/products")
      return ok({
        success: true,
        rows: [],
        page: 1,
        page_size: 1,
        total: 5,
        total_pages: 5,
        stats: { total: 5, available: 2, low: 2, out: 1 },
        categories: [],
        branch_scope_label: "الأول",
      });
    return { ok: false, failure: "http", status: 403, data: {} };
  });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <SmartWorkspace />
    </QueryClientProvider>,
  );
  return { bridge, client };
}
beforeEach(() => {
  MotionGlobalConfig.skipAnimations = true;
  localStorage.clear();
  useWindowManager.getState().reset();
  useSession.getState().signedIn(session);
  useWorkspace.getState().reset();
  useWorkspace.getState().activate("https://one.test", session);
});
afterEach(() => {
  removeMockBridge();
  useWorkspace.getState().reset();
  vi.restoreAllMocks();
});

it("renders independent real-contract summaries and opens filtered native destinations", async () => {
  const { bridge } = setup();
  expect(await screen.findByText("4,850,000")).toBeVisible();
  expect(await screen.findByText("2,450,000")).toBeVisible();
  expect(within(screen.getByRole("region", { name: "الطلبات" })).getByText("24")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: /طلبات بانتظار التجهيز/ }));
  expect(useWindowManager.getState().active).toBe("orders");
  expect(useWorkspace.getState().requests.orders?.target.tab).toBe("ordered");
  expect(bridge.finora.request.mock.calls.every(([r]) => r.method === "GET")).toBe(true);
});
it("one failed source does not prevent other cards or quick actions", async () => {
  setup(true);
  expect(await screen.findByText("2,450,000")).toBeVisible();
  expect(within(screen.getByRole("region", { name: "مبيعات اليوم" })).getByRole("alert")).toHaveTextContent(
    "تعذر تحميل البيانات",
  );
  await userEvent.click(screen.getByRole("button", { name: "منتج جديد" }));
  expect(useWorkspace.getState().requests.products?.action).toBe("product");
});

it("does not fabricate zero active orders when only the all-orders permission is granted", async () => {
  useSession.getState().signedIn({ ...session, permissions: ["can_see_orders"] });
  setup(false, true);
  await waitFor(() =>
    expect(within(screen.getByRole("region", { name: "الطلبات" })).getByText("24")).toBeVisible(),
  );
  expect(screen.getByText("كل الطلبات الظاهرة لحسابك")).toBeVisible();
});
it("restricted accounts never request or show financial or stock sources", async () => {
  const restricted = { ...session, permissions: [] };
  useSession.getState().signedIn(restricted);
  const { bridge } = setup();
  await screen.findByText("لا يوجد نشاط حديث لعرضه.");
  for (const name of ["مبيعات اليوم", "المستحقات", "الطلبات"])
    expect(screen.queryByRole("region", { name })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "سند قبض" })).not.toBeInTheDocument();
  expect(
    bridge.finora.request.mock.calls.some(([r]) => /sales|receivables|inventory|counts/.test(r.path)),
  ).toBe(false);
});

it("reuses permission-scoped HR alerts without duplication and opens their existing filtered target", async () => {
  useSession
    .getState()
    .signedIn({ ...session, permissions: [...session.permissions, "hr.view", "hr.attendance.approve"] });
  setup();
  const button = await screen.findByRole("button", { name: /طلب تصحيح دوام بانتظار الموافقة/ });
  await waitFor(() =>
    expect(within(screen.getByRole("region", { name: "المتابعة" })).getByText("12")).toBeVisible(),
  );
  await userEvent.click(button);
  expect(useWindowManager.getState().active).toBe("employees");
  expect(useHRNavigation.getState().target).toEqual({
    tab: "corrections",
    person_id: 7,
    date: "2026-10-20",
    month: "2026-10",
  });
});
it("saves customization per server/company/user and keeps recovery per branch", () => {
  const prefs = {
    ...defaultPreferences(),
    compact: true,
    actions: ["sale" as const],
    visible: ["quick" as const],
  };
  expect(useWorkspace.getState().configure(prefs)).toBe(true);
  useWorkspace.getState().record({ window: "orders", entityId: 15, tab: "packed" });
  useWorkspace.getState().reset();
  useWorkspace.getState().activate("https://one.test", session);
  expect(useWorkspace.getState().prefs).toEqual(prefs);
  expect(useWorkspace.getState().saved[0]?.entityId).toBe(15);
  const otherBranch = { ...session, branch: { id: 2, name: "الثاني" } };
  useSession.getState().signedIn(otherBranch);
  expect(useWorkspace.getState().saved).toEqual([]);
  expect(useWorkspace.getState().prefs.compact).toBe(true);
  useSession.getState().signedIn({ ...session, user: { ...session.user, id: 9 } });
  expect(useWorkspace.getState().prefs).toEqual(defaultPreferences());
  expect(useWorkspace.getState().saved).toEqual([]);
  useWorkspace.getState().activate("https://two.test", session);
  expect(useWorkspace.getState().prefs).toEqual(defaultPreferences());
});
it("rejects persisted sensitive form data and reports failed preference saves", () => {
  expect(() =>
    useWorkspace.getState().navigate({ window: "pos", amount: 1000 } as unknown as WorkspaceTarget),
  ).toThrow();
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw Error("full");
  });
  expect(useWorkspace.getState().configure({ ...defaultPreferences(), compact: true })).toBe(false);
  expect(useWorkspace.getState().prefs.compact).toBe(false);
});

it("assistant reuses a bounded, validated JSON request without identity or provider overrides", async () => {
  const bridge = installMockBridge(() => ok({ success: true, message: "بيانات الحساب المصرح بها" }));
  await workspaceApi.ask("اعرض طلبات اليوم");
  const request = bridge.finora.request.mock.calls[0]?.[0];
  expect(finoraRequestSchema.safeParse(request).success).toBe(true);
  expect(request?.body).toEqual({ message: "اعرض طلبات اليوم" });
  expect(request?.path).toBe("/finora-ai/api/desktop/chat");
});
it("queued session restores are consumed only by the active native window without replaying writes", async () => {
  const order = vi.fn(),
    product = vi.fn();
  function Consumer() {
    useWorkspaceRequest("orders", order);
    useWorkspaceRequest("products", product);
    return null;
  }
  render(<Consumer />);
  act(() => {
    openWorkspaceTarget({ window: "orders", tab: "packed" });
    useWindowManager.getState().minimize();
    openWorkspaceTarget({ window: "products", tab: "low" });
  });
  await waitFor(() => expect(product).toHaveBeenCalledTimes(1));
  expect(order).not.toHaveBeenCalled();
  act(() => useWindowManager.getState().open("orders"));
  await waitFor(() => expect(order).toHaveBeenCalledTimes(1));
  act(() => {
    useWindowManager.getState().close();
    useWindowManager.getState().open("orders");
  });
  expect(order).toHaveBeenCalledTimes(1);
});
