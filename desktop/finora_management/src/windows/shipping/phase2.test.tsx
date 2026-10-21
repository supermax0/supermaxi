import { vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { finoraRequestSchema, type FinoraRequest } from "@shared/ipc";
import { useConnection } from "@/stores/connection";
import { installMockBridge, removeMockBridge } from "@/test/mockBridge";
import { ManifestWorkspace } from "./ManifestWorkspace";
import { ReturnsSection } from "./Returns";
import { DispatchDialog } from "./Dispatch";

const BASE = "/api/v1/desktop/shipping-center";
const ok = (data: unknown) => ({ ok: true as const, status: 200, data: { ok: true, ...(data as object) } });

const row = (id: number, remaining: number, feeDue: number, selection: string) => ({
  id,
  customer_name: `عميل ${id}`,
  customer_phone: "",
  customer_city: "بغداد",
  customer_address: "",
  total: remaining,
  paid_amount: 0,
  remaining,
  status: "جاري الشحن",
  shipping_status: "",
  payment_status: "غير مسدد",
  shipping_company_id: 5,
  shipping_company: "شركة البرق",
  delivery_agent_id: null,
  delivery_agent: "",
  waybills: [],
  fee: 5000,
  fee_due: feeDue,
  created_at: "2026-10-14 10:00",
  selection,
});

const MANIFEST = {
  id: 80,
  number: "STL-20261015-0002",
  kind: "settlement",
  carrier_id: 5,
  carrier: "شركة البرق",
  agent_id: null,
  agent: "",
  settlement_state: "draft",
  orders_count: 3,
  total_amount: 0,
  executed: false,
  created_at: "2026-10-15 09:00",
  created_by: "admin",
  reference: "",
  breakdown: {},
  meta: {},
  selections: { "201": "واصل", "202": "واصل", "203": "راجع" },
  rows: [row(201, 225000, 5000, "واصل"), row(202, 350000, 5000, "واصل"), row(203, 90000, 5000, "راجع")],
  issues: [],
  blocking: [],
  totals: {
    delivered: { count: 2, amount: 575000, fee: 10000 },
    returned: { count: 1, amount: 90000, fee: 3000 },
    postponed: { count: 0, amount: 0 },
    problem: { count: 0, amount: 0 },
    unclassified: { count: 0, amount: 0 },
  },
  expected_net: 562000,
  ready: true,
  return_fee_each: 3000,
};

afterEach(() => {
  removeMockBridge();
  useConnection.setState({ status: "online" });
});

function wrap(
  ui: React.ReactNode,
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } }),
) {
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

it("refreshes externally edited prices and agent details while keeping the received amount", async () => {
  let server = structuredClone(MANIFEST);
  installMockBridge(() => ok({ manifest: structuredClone(server) }));
  const user = userEvent.setup();
  wrap(<ManifestWorkspace manifestId={80} canApprove canManage treasuryAccounts={[]} onBack={vi.fn()} />);
  await screen.findByText("عميل 201");
  await user.type(screen.getByLabelText("المبلغ المستلم فعلياً"), "562000");
  fireEvent.keyDown(screen.getByText("عميل 201"), { key: "F5" });
  const details = await screen.findByRole("dialog", { name: "الطلب #201" });
  server = {
    ...server,
    rows: server.rows
      .filter((row) => row.id !== 202)
      .map((row) =>
        row.id === 201 ? { ...row, total: 400000, remaining: 400000, delivery_agent: "مندوب جديد" } : row,
      ),
  };
  await waitFor(() => expect(within(details).getByText("مندوب جديد")).toBeInTheDocument(), { timeout: 5000 });
  expect(within(details).getAllByText("400,000 د.ع")).toHaveLength(2);
  expect(screen.queryByText("عميل 202")).not.toBeInTheDocument();
  expect(screen.getByLabelText("المبلغ المستلم فعلياً")).toHaveValue("562,000");
}, 10000);

it("does not replace a newer local classification with an earlier autosave acknowledgement", async () => {
  let server = structuredClone(MANIFEST);
  let finish: (() => void) | undefined;
  let writes = 0;
  installMockBridge((request) => {
    if (request.path.endsWith("/selections")) {
      const incoming = (request.body as { selections: Record<string, string> }).selections;
      server = { ...server, selections: { ...server.selections, ...incoming } };
      const saved = structuredClone(server);
      if (++writes === 1)
        return new Promise<ReturnType<typeof ok>>((resolve) => {
          finish = () => resolve(ok({ manifest: saved }));
        });
    }
    return ok({ manifest: structuredClone(server) });
  });
  const user = userEvent.setup();
  wrap(<ManifestWorkspace manifestId={80} canApprove canManage treasuryAccounts={[]} onBack={vi.fn()} />);
  const first = await screen.findByRole("radiogroup", { name: "تصنيف 201" });
  await user.click(within(first).getByRole("radio", { name: "راجع" }));
  await waitFor(() => expect(finish).toBeDefined());
  const second = screen.getByRole("radiogroup", { name: "تصنيف 202" });
  await user.click(within(second).getByRole("radio", { name: "مؤجل" }));
  await act(async () => finish?.());
  expect(within(second).getByRole("radio", { name: "مؤجل" })).toHaveAttribute("aria-checked", "true");
  await waitFor(() => expect(server.selections["202"]).toBe("مؤجل"), { timeout: 3000 });
  expect(server.selections["201"]).toBe("راجع");
});

it("retains a rejected draft without repeatedly resubmitting it until the user changes it", async () => {
  let writes = 0;
  installMockBridge((request) => {
    if (request.path.endsWith("/selections")) {
      writes += 1;
      return { ok: false, failure: "http", status: 409, data: { error: "تغيّر الكشف" } };
    }
    return ok({ manifest: MANIFEST });
  });
  const user = userEvent.setup();
  wrap(<ManifestWorkspace manifestId={80} canApprove canManage treasuryAccounts={[]} onBack={vi.fn()} />);
  const first = await screen.findByRole("radiogroup", { name: "تصنيف 201" });
  await user.click(within(first).getByRole("radio", { name: "راجع" }));
  await waitFor(() => expect(writes).toBe(1));
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 2100));
  });
  expect(writes).toBe(1);
  expect(within(first).getByRole("radio", { name: "راجع" })).toHaveAttribute("aria-checked", "true");
  await user.click(within(first).getByRole("radio", { name: "مؤجل" }));
  await waitFor(() => expect(writes).toBe(2));
}, 10000);

it("distributes a partial payment oldest-first, deducting each fee once and the return fee", async () => {
  const bridge = installMockBridge((request: FinoraRequest) => {
    if (request.path === `${BASE}/manifests/80`) return ok({ manifest: MANIFEST });
    if (request.path === `${BASE}/manifests/80/approve`)
      return ok({ manifest: { ...MANIFEST, executed: true }, result: {} });
    return { ok: false, failure: "http", status: 404, data: { error: "not found" } };
  });
  const user = userEvent.setup();
  wrap(
    <ManifestWorkspace
      manifestId={80}
      canApprove
      canManage
      treasuryAccounts={[{ id: 3, name: "الصندوق", is_default: true }]}
      onBack={() => undefined}
    />,
  );
  const analysis = await screen.findByRole("complementary", { name: "لوحة التحليل" });
  expect(within(analysis).getByText("562,000 د.ع")).toBeInTheDocument(); // 575,000 − 10,000 − 3,000

  await user.click(within(analysis).getByRole("checkbox"));
  // 320,000 received + 3,000 return fee: order 201 in full (220,000 net), the rest to 202 (103,000 + its 5,000 fee)
  await user.type(within(analysis).getByLabelText("المبلغ المستلم فعلياً"), "320000");
  await user.click(within(analysis).getByRole("button", { name: "توزيع تلقائي على الأقدم" }));
  expect(screen.getByLabelText("المبلغ المسدد للطلب 202")).toHaveValue("108,000");
  expect(await within(analysis).findByText(/التسوية متطابقة/)).toBeInTheDocument();
  expect(within(analysis).getByText("242,000 د.ع")).toBeInTheDocument(); // still owed by the carrier

  await user.click(screen.getByRole("button", { name: /اعتماد التسوية/ }));
  const confirm = await screen.findByRole("dialog", { name: "اعتماد كشف التسوية" });
  expect(confirm).toHaveTextContent("بانتظار الاستلام");
  await user.click(within(confirm).getByRole("button", { name: "اعتماد وترحيل" }));
  await waitFor(() =>
    expect(
      bridge.finora.request.mock.calls.find(([r]) => r.path === `${BASE}/manifests/80/approve`)?.[0].body,
    ).toEqual({
      received_amount: 320000,
      treasury_account_id: 3,
      payment_method: "cash",
      allocations: { "201": 225000, "202": 108000 },
    }),
  );
  // Every request must pass the main-process IPC validation (e.g. timeoutMs ≤ 60s), or Electron refuses it.
  for (const [request] of bridge.finora.request.mock.calls)
    expect(finoraRequestSchema.safeParse(request).success).toBe(true);
});

it("receives a returned parcel by scan, then closes the inspection with damaged quantities", async () => {
  const ret = {
    id: 9,
    order_id: 203,
    state: "received",
    manifest_id: 80,
    manifest_number: "STL-20261015-0002",
    party_type: "carrier",
    party_id: 5,
    party_name: "شركة البرق",
    order_amount: 90000,
    customer_name: "عميل 203",
    customer_city: "بغداد",
    order_status: "جاري الشحن",
    waybills: [],
    reported_at: "2026-10-15 09:00",
    received_at: "2026-10-15 11:00",
    received_by: "admin",
    closed_at: "",
    closed_by: "",
    branch_id: null,
    packaging_ok: null,
    inspection: [],
    writeoffs: [],
    note: "",
    items: [{ item_id: 51, product_id: 7, name: "سماعة", variant: "", quantity: 2 }],
    branches: [{ id: 1, name: "الفرع الرئيسي" }],
  };
  const bridge = installMockBridge((request: FinoraRequest) => {
    if (request.path === `${BASE}/returns`)
      return ok({ rows: [ret], counts: { awaiting: 0, received: 1, closed: 0 } });
    if (request.path === `${BASE}/returns/receive`) return ok({ item: ret });
    if (request.path === `${BASE}/returns/9`) return ok({ item: ret, can_writeoff: true });
    if (request.path === `${BASE}/returns/9/close`)
      return ok({ item: { ...ret, state: "closed", writeoffs: ["WO-ABC"] } });
    return { ok: false, failure: "http", status: 404, data: { error: "not found" } };
  });
  const user = userEvent.setup();
  wrap(<ReturnsSection enabled canManage />);
  await user.type(await screen.findByLabelText("استلام مرتجع بالباركود"), "203{Enter}");
  await waitFor(() =>
    expect(
      bridge.finora.request.mock.calls.find(([r]) => r.path === `${BASE}/returns/receive`)?.[0].body,
    ).toEqual({
      code: "203",
    }),
  );
  await user.click(await screen.findByRole("button", { name: "فحص وإغلاق" }));
  const dialog = await screen.findByRole("dialog", { name: /فحص مرتجع الطلب/ });
  const damaged = await within(dialog).findByLabelText("الكمية التالفة من سماعة");
  await user.clear(damaged);
  await user.type(damaged, "1");
  await user.click(within(dialog).getByRole("checkbox"));
  await user.click(within(dialog).getByRole("button", { name: /إغلاق المرتجع/ }));
  await waitFor(() =>
    expect(
      bridge.finora.request.mock.calls.find(([r]) => r.path === `${BASE}/returns/9/close`)?.[0].body,
    ).toEqual({
      branch_id: 1,
      packaging_ok: false,
      note: "",
      lines: [{ item_id: 51, damaged: 1 }],
    }),
  );
});

it("lists orders the carrier holds but the manifest misses, and adds the picked ones", async () => {
  const held = { ...row(301, 70000, 5000, ""), days_out: 12, in_manifest: "" };
  const busy = { ...row(302, 40000, 5000, ""), days_out: 3, in_manifest: "STL-20261014-0001" };
  const bridge = installMockBridge((request: FinoraRequest) => {
    if (request.path === `${BASE}/manifests/80`) return ok({ manifest: MANIFEST });
    if (request.path === `${BASE}/manifests/80/missing`)
      return ok({ rows: [held, busy], total: 2, amount: 110000 });
    if (request.path === `${BASE}/manifests/80/rows`)
      return ok({ manifest: MANIFEST, added: [301], duplicates: [], missing: [] });
    return { ok: false, failure: "http", status: 404, data: { error: "not found" } };
  });
  const user = userEvent.setup();
  wrap(
    <ManifestWorkspace
      manifestId={80}
      canApprove
      canManage
      treasuryAccounts={[{ id: 3, name: "الصندوق", is_default: true }]}
      onBack={() => undefined}
    />,
  );
  await user.click(await screen.findByRole("button", { name: /طلب لدى الجهة لم يرد في الكشف/ }));
  const dialog = await screen.findByRole("dialog", { name: "طلبات لدى الجهة ولم ترد في الكشف" });
  expect(within(dialog).getByLabelText("تحديد 302")).toBeDisabled(); // already in another open settlement
  expect(within(dialog).getByText("12")).toBeInTheDocument();
  await user.click(within(dialog).getByLabelText("تحديد 301"));
  await user.click(within(dialog).getByRole("button", { name: /إضافة 1 للكشف/ }));
  await waitFor(() =>
    expect(
      bridge.finora.request.mock.calls.find(([r]) => r.path === `${BASE}/manifests/80/rows`)?.[0].body,
    ).toEqual({
      codes: ["301"],
    }),
  );
  await waitFor(() =>
    expect(screen.queryByRole("dialog", { name: "طلبات لدى الجهة ولم ترد في الكشف" })).toBeNull(),
  );
});

it("hands preloaded and scanned orders to an agent manifest, or assigns them only", async () => {
  const bridge = installMockBridge((request: FinoraRequest) => {
    if (request.path === `${BASE}/lookup`) {
      const codes = (request.body as { codes: string[] }).codes;
      return ok({ found: codes.map((c) => ({ ...row(Number(c), 50000, 5000, ""), code: c })), missing: [] });
    }
    if (request.path === `${BASE}/agent-report`)
      return ok({ report_id: 5, report_number: "AGT-2-20261015-0001", already_exists: false, message: "" });
    if (request.path.startsWith("/orders/"))
      return { ok: true as const, status: 200, data: { success: true } };
    return { ok: false, failure: "http", status: 404, data: { error: "not found" } };
  });
  const user = userEvent.setup();
  const onClose = vi.fn();
  wrap(
    <DispatchDialog
      carriers={[{ id: 5, name: "شركة البرق" }]}
      agents={[{ id: 2, name: "مندوب علي" }]}
      initialIds={[401]}
      onClose={onClose}
    />,
  );
  const dialog = await screen.findByRole("dialog", { name: "تسليم وإسناد الطلبات" });
  expect(await within(dialog).findByText("#401")).toBeInTheDocument();
  await user.type(within(dialog).getByLabelText("مسح الطلبات"), "402{Enter}");
  expect(await within(dialog).findByText("#402")).toBeInTheDocument();
  await user.click(within(dialog).getByRole("button", { name: "إنشاء كشف المندوب" }));
  await waitFor(() =>
    expect(
      bridge.finora.request.mock.calls.find(([r]) => r.path === `${BASE}/agent-report`)?.[0].body,
    ).toEqual({
      agent_id: 2,
      order_ids: [401, 402],
    }),
  );
  await waitFor(() => expect(onClose).toHaveBeenCalled());
});
