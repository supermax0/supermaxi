import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { FinoraRequest } from "@shared/ipc";
import { useConnection } from "@/stores/connection";
import { useSession } from "@/stores/session";
import { useWindowManager } from "@/stores/windowManager";
import { installMockBridge, removeMockBridge, SESSION_PAYLOAD } from "@/test/mockBridge";
import { codesFromCsv, splitCodes } from "./shared";
import { ShippingCenterWindow } from "./ShippingCenterWindow";

const BASE = "/api/v1/desktop/shipping-center";
const stats = (n: number) => ({ count: n, amount: n * 1000 });
const STATS = {
  total: stats(9),
  transit: stats(4),
  delivered_unsettled: stats(2),
  due: stats(6),
  returned: stats(1),
};

const order = (id: number, remaining: number, fee: number) => ({
  id,
  customer_name: `عميل ${id}`,
  customer_phone: "0770",
  customer_city: "بغداد",
  customer_address: "",
  total: remaining,
  paid_amount: 0,
  remaining,
  status: "جاري الشحن",
  shipping_status: "",
  payment_status: "غير مدفوع",
  shipping_company_id: 5,
  shipping_company: "شركة البرق",
  delivery_agent_id: null,
  delivery_agent: "",
  waybills: [`WB${id}`],
  fee,
  fee_due: fee,
  created_at: "2026-10-14T10:00:00",
});

function manifestState() {
  const rows: ReturnType<typeof order>[] = [];
  const selections: Record<string, string> = {};
  let executed = false;
  const build = () => {
    const delivered = rows.filter((r) => selections[String(r.id)] === "واصل");
    const amount = delivered.reduce((s, r) => s + r.remaining, 0);
    const fee = delivered.reduce((s, r) => s + r.fee, 0);
    const unclassified = rows.filter((r) => !selections[String(r.id)]);
    return {
      id: 70,
      number: "STL-20261015-0001",
      kind: "settlement",
      carrier_id: 5,
      carrier: "شركة البرق",
      agent: "",
      orders_count: rows.length,
      total_amount: rows.reduce((s, r) => s + r.remaining, 0),
      executed,
      created_at: "2026-10-15T09:00:00",
      created_by: "admin",
      reference: "B-1145",
      breakdown: {},
      meta: { reference: "B-1145", date: "2026-10-15" },
      selections: { ...selections },
      rows: rows.map((r) => ({ ...r, selection: selections[String(r.id)] ?? "" })),
      issues: [],
      blocking: unclassified.map((r) => ({
        severity: "error",
        code: "unclassified",
        order_id: r.id,
        message: `الطلب ${r.id} غير مصنف`,
      })),
      totals: {
        delivered: { count: delivered.length, amount, fee },
        returned: stats(0),
        postponed: stats(0),
        problem: stats(0),
        unclassified: { count: unclassified.length, amount: 0 },
      },
      expected_net: amount - fee,
      ready: rows.length > 0 && unclassified.length === 0,
    };
  };
  return {
    build,
    add: (codes: string[]) => {
      for (const code of codes) {
        const id = Number(code);
        if (!rows.some((r) => r.id === id)) rows.push(order(id, id === 101 ? 250000 : 150000, 5000));
      }
    },
    select: (s: Record<string, string>) => Object.assign(selections, s),
    execute: () => (executed = true),
  };
}

function setup(permissions: string[] = ["can_see_shipping", "can_manage_shipping"]) {
  useSession.setState({
    status: "signed_in",
    session: { ...SESSION_PAYLOAD, permissions } as never,
  } as never);
  useWindowManager.setState({ active: "shipping" });
  const m = manifestState();
  const ok = (data: unknown) => ({ ok: true as const, status: 200, data });
  const bridge = installMockBridge((request: FinoraRequest) => {
    const body = (request.body ?? {}) as Record<string, unknown>;
    if (request.path === `${BASE}/manifests` && request.method === "POST")
      return ok({ ok: true, manifest: m.build() });
    switch (request.path) {
      case `${BASE}/meta`:
        return ok({
          ok: true,
          carriers: [{ id: 5, name: "شركة البرق", phone: "", price: 5000 }],
          agents: [],
          treasury_accounts: [{ id: 3, name: "الصندوق", is_default: true }],
          can_approve: true,
          can_manage: true,
        });
      case `${BASE}/overview`:
        return ok({
          ok: true,
          cards: {
            in_transit: { count: 42 },
            delivered_unsettled: { count: 7, amount: 1250000 },
            carriers_due: { count: 12, amount: 3400000 },
            agents_due: { count: 3, amount: 410000 },
            returns: { count: 5 },
            open_manifests: { count: 2, flagged: 1 },
          },
        });
      case `${BASE}/carriers`:
        return ok({
          ok: true,
          rows: [
            {
              id: 5,
              name: "شركة البرق",
              phone: "",
              price: 5000,
              notes: "",
              opening_balance: 0,
              stats: STATS,
              due: 3400000,
              open_manifests: 1,
            },
          ],
        });
      case `${BASE}/manifests`:
        return ok({ ok: true, rows: [] });
      case `${BASE}/manifests/70`:
        return ok({ ok: true, manifest: m.build() });
      case `${BASE}/manifests/70/rows`:
        m.add(body.codes as string[]);
        return ok({
          ok: true,
          manifest: m.build(),
          added: (body.codes as string[]).map(Number),
          duplicates: [],
          missing: [],
        });
      case `${BASE}/manifests/70/selections`:
        m.select(body.selections as Record<string, string>);
        return ok({ ok: true, manifest: m.build() });
      case `${BASE}/manifests/70/approve`:
        m.execute();
        return ok({ ok: true, manifest: m.build(), result: {} });
    }
    return { ok: false, failure: "http", status: 404, data: { error: "not found" } };
  });
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ShippingCenterWindow />
    </QueryClientProvider>,
  );
  return bridge;
}

afterEach(() => {
  removeMockBridge();
  useConnection.setState({ status: "online" });
});

it("splits scanned / pasted codes and CSV first columns", () => {
  expect(splitCodes("#101\n102, 103\t104 ، 105")).toEqual(["101", "102", "103", "104", "105"]);
  expect(codesFromCsv('رقم الطلب,المبلغ\r\n101,250000\n"#102",150000\n')).toEqual(["101", "102"]);
});

it("shows the six overview cards and carriers by amount due", async () => {
  setup();
  expect(await screen.findByText("1,250,000")).toBeInTheDocument();
  expect(screen.getByText("قيد التوصيل").closest("button")).toHaveTextContent("42");
  expect(screen.getByText("مستحقات شركات النقل").closest("button")).toHaveTextContent("3,400,000");
  expect(screen.getByText("مستحقات المندوبين")).toBeInTheDocument();
  expect(screen.getByText("المرتجعات", { selector: "p" })).toBeInTheDocument();
  expect(await screen.findByText("شركة البرق")).toBeInTheDocument();
});

it("creates a settlement, classifies by keyboard and approves only a matching amount", async () => {
  const bridge = setup();
  const user = userEvent.setup();
  const calls = () => bridge.finora.request.mock.calls.map(([r]) => r);
  await user.click(await screen.findByRole("button", { name: /كشف تسوية جديد/ }));
  const dialog = await screen.findByRole("dialog", { name: "كشف تسوية جديد" });
  await user.type(within(dialog).getByPlaceholderText(/2026-1145/), "B-1145");
  await user.click(within(dialog).getByRole("button", { name: /إنشاء وفتح الكشف/ }));

  const entry = await screen.findByLabelText("رقم الطلب أو البوليصة");
  await user.type(entry, "101{Enter}");
  expect(await screen.findByText("عميل 101")).toBeInTheDocument();
  fireEvent.paste(entry, { clipboardData: { getData: () => "102\n103" } });
  expect(await screen.findByText("عميل 103")).toBeInTheDocument();

  // F2 marks the focused row delivered and moves down; F3 / F4 likewise.
  const region = screen.getByRole("region", { name: /STL-20261015-0001/ });
  fireEvent.keyDown(region, { key: "F2" });
  fireEvent.keyDown(region, { key: "F2" });
  fireEvent.keyDown(region, { key: "F3" });
  expect(
    within(screen.getByRole("radiogroup", { name: "تصنيف 101" })).getByRole("radio", { name: "واصل" }),
  ).toHaveAttribute("aria-checked", "true");
  fireEvent.keyDown(region, { key: "s", ctrlKey: true });
  await waitFor(() =>
    expect(calls().find((r) => r.path === `${BASE}/manifests/70/selections`)?.body).toEqual({
      selections: { "101": "واصل", "102": "واصل", "103": "راجع" },
    }),
  );

  // Expected net: 250,000 + 150,000 − 2 × 5,000 = 390,000. Approval waits for an exact match.
  const analysis = screen.getByRole("complementary", { name: "لوحة التحليل" });
  await waitFor(() => expect(within(analysis).getByText("390,000 د.ع")).toBeInTheDocument());
  const approve = screen.getByRole("button", { name: /اعتماد التسوية/ });
  await user.type(within(analysis).getByLabelText("المبلغ المستلم فعلياً"), "380000");
  expect(await within(analysis).findByText(/فرق 10,000 د.ع نقص/)).toBeInTheDocument();
  expect(approve).toBeDisabled();
  const received = within(analysis).getByLabelText("المبلغ المستلم فعلياً");
  await user.clear(received);
  await user.type(received, "390000");
  expect(await within(analysis).findByText(/التسوية متطابقة/)).toBeInTheDocument();
  await waitFor(() => expect(approve).toBeEnabled());
  await user.click(approve);
  const confirm = await screen.findByRole("dialog", { name: "اعتماد كشف التسوية" });
  await user.click(within(confirm).getByRole("button", { name: "اعتماد وترحيل" }));
  await waitFor(() =>
    expect(calls().find((r) => r.path === `${BASE}/manifests/70/approve`)?.body).toEqual({
      received_amount: 390000,
      treasury_account_id: 3,
      payment_method: "cash",
    }),
  );
  // Approved manifests are read-only.
  await waitFor(() => expect(screen.queryByLabelText("رقم الطلب أو البوليصة")).not.toBeInTheDocument());
  expect(screen.getAllByText("معتمد").length).toBeGreaterThan(0);
});

it("tells users without the permission instead of calling FINORA", () => {
  const bridge = setup(["can_see_orders"]);
  expect(screen.getByText("لا تملك صلاحية مركز الشحن")).toBeInTheDocument();
  expect(bridge.finora.request).not.toHaveBeenCalled();
});
