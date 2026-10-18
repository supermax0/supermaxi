import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { FinoraRequest } from "@shared/ipc";
import { installMockBridge, removeMockBridge } from "@/test/mockBridge";
import { useWindowManager } from "@/stores/windowManager";
import { PermissionsWindow } from "./PermissionsWindow";

const BASE = "/api/v1/desktop/permissions";
const ok = (data: unknown) => ({ ok: true as const, status: 200, data: { ok: true, ...(data as object) } });

const catalog = {
  groups: [
    {
      key: "sales",
      title: "المبيعات",
      permissions: [
        { name: "view_pos", label: "استخدام نقطة البيع", sensitive: false },
        { name: "delete_orders", label: "حذف الطلبات", sensitive: true },
      ],
    },
  ],
};
const employees = {
  rows: [
    {
      id: 1,
      name: "المدير",
      username: "boss",
      role: "admin",
      active: true,
      branch: "",
      roles: [],
      overrides: 0,
      is_admin: true,
    },
    {
      id: 2,
      name: "سارة",
      username: "sara",
      role: "sales",
      active: true,
      branch: "",
      roles: ["كاشير"],
      overrides: 1,
      is_admin: false,
    },
  ],
};
const detail = (isAdmin: boolean) => ({
  employee: {
    id: isAdmin ? 1 : 2,
    name: isAdmin ? "المدير" : "سارة",
    role: isAdmin ? "admin" : "sales",
    active: true,
    is_admin: isAdmin,
  },
  role_ids: [10],
  permissions: [
    {
      name: "view_pos",
      group: "sales",
      allowed: true,
      source: isAdmin ? "admin" : "role",
      override: null,
      roles: ["كاشير"],
    },
    { name: "delete_orders", group: "sales", allowed: false, source: "none", override: null, roles: [] },
  ],
});
const roles = { rows: [{ id: 10, name: "كاشير", description: "", permissions: ["view_pos"], employees: 1 }] };

function mount(handler?: (r: FinoraRequest) => unknown) {
  useWindowManager.setState({ active: "permissions" } as never);
  const bridge = installMockBridge((r: FinoraRequest) => {
    const custom = handler?.(r);
    if (custom) return custom as never;
    if (r.path === `${BASE}/catalog`) return ok(catalog);
    if (r.path === `${BASE}/employees`) return ok(employees);
    if (r.path === `${BASE}/employees/1`) return ok(detail(true));
    if (r.path === `${BASE}/employees/2`) return ok(detail(false));
    if (r.path === `${BASE}/roles`) return ok(roles);
    if (r.path === `${BASE}/audit`) return ok({ rows: [] });
    return { ok: false, failure: "http", status: 404, data: { error: "not found" } };
  });
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <PermissionsWindow />
    </QueryClientProvider>,
  );
  return bridge;
}

afterEach(removeMockBridge);

it("shows where each permission comes from and sends only the changed exceptions", async () => {
  const bridge = mount((r) => {
    if (r.path === `${BASE}/employees/2/overrides`) return ok(detail(false));
    return undefined;
  });
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: /سارة/ }));
  await user.click(await screen.findByText(/المبيعات/)); // open the group
  expect(await screen.findByText(/من الدور \(كاشير\)/)).toBeInTheDocument();
  await user.click(screen.getByRole("radio", { name: "حذف الطلبات: منع" }));
  expect(screen.getByRole("button", { name: /حفظ التغييرات \(1\)/ })).toBeEnabled();
  await user.click(screen.getByRole("button", { name: /حفظ التغييرات/ }));
  await waitFor(() =>
    expect(
      bridge.finora.request.mock.calls.find(([r]) => r.path === `${BASE}/employees/2/overrides`)?.[0].body,
    ).toEqual({ changes: { delete_orders: "deny" }, note: "" }),
  );
});

it("reverting a choice back to its original removes it from the pending changes", async () => {
  mount();
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: /سارة/ }));
  await user.click(await screen.findByText(/المبيعات/));
  await user.click(await screen.findByRole("radio", { name: "حذف الطلبات: سماح" }));
  expect(screen.getByRole("button", { name: /حفظ التغييرات \(1\)/ })).toBeEnabled();
  await user.click(screen.getByRole("radio", { name: "حذف الطلبات: حسب الدور" }));
  expect(screen.getByRole("button", { name: /حفظ التغييرات/ })).toBeDisabled();
});

it("does not offer editing for the general admin", async () => {
  mount();
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: /المدير/ }));
  expect(await screen.findByText(/يملك كل الصلاحيات/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /حفظ التغييرات/ })).not.toBeInTheDocument();
});

it("creates a role with the chosen permissions", async () => {
  const bridge = mount((r) => (r.path === `${BASE}/roles` && r.method === "POST" ? ok(roles) : undefined));
  const user = userEvent.setup();
  await user.click(await screen.findByRole("tab", { name: "الأدوار" }));
  await user.click(await screen.findByRole("button", { name: /دور جديد/ }));
  await user.type(await screen.findByRole("textbox", { name: "اسم الدور" }), "محاسب");
  await user.click(await screen.findByRole("checkbox", { name: /حذف الطلبات/ }));
  await user.click(screen.getByRole("button", { name: "حفظ الدور" }));
  await waitFor(() =>
    expect(
      bridge.finora.request.mock.calls.find(([r]) => r.path === `${BASE}/roles` && r.method === "POST")?.[0]
        .body,
    ).toEqual({ name: "محاسب", description: "", permissions: ["delete_orders"] }),
  );
});

it("installs the chosen ready-made roles and marks installed ones", async () => {
  const templates = [
    { key: "cashier", name: "كاشير", description: "البيع", permissions: ["view_pos"], installed: false },
    {
      key: "accountant",
      name: "محاسب",
      description: "الحسابات",
      permissions: ["view_accounts"],
      installed: true,
    },
  ];
  const bridge = mount((r) => {
    if (r.path === `${BASE}/role-templates` && r.method === "GET") return ok({ rows: templates });
    if (r.path === `${BASE}/role-templates/install`)
      return ok({ created: ["كاشير"], skipped: [], rows: roles.rows, templates });
    return undefined;
  });
  const user = userEvent.setup();
  await user.click(await screen.findByRole("tab", { name: "الأدوار" }));
  await user.click(await screen.findByRole("button", { name: "الأدوار الجاهزة" }));
  const accountant = await screen.findByRole("checkbox", { name: /محاسب/ });
  expect(accountant).toBeDisabled();
  expect(accountant).toBeChecked();
  expect(screen.getByRole("button", { name: /إضافة المحدد \(0\)/ })).toBeDisabled();
  await user.click(screen.getByRole("checkbox", { name: /كاشير/ }));
  await user.click(screen.getByRole("button", { name: /إضافة المحدد \(1\)/ }));
  await waitFor(() =>
    expect(
      bridge.finora.request.mock.calls.find(([r]) => r.path === `${BASE}/role-templates/install`)?.[0].body,
    ).toEqual({ keys: ["cashier"] }),
  );
});
