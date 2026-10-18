import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { FinoraRequest } from "@shared/ipc";
import type { StorageDocument } from "@/api/finora/storageLocations";
import { installMockBridge, removeMockBridge } from "@/test/mockBridge";
import { StorageLocations } from "./StorageLocations";

const main = {
  id: null,
  key: "storage:2:main",
  branch_id: 2,
  branch_name: "الفرع الرئيسي",
  name: "الموقع الأساسي للفرع",
  code: "MAIN",
  kind: "main",
  is_active: true,
  revision: null,
};
const child = {
  ...main,
  id: 4,
  key: "storage:2:4",
  name: "المخزن الخلفي",
  code: "BACK",
  kind: "storage",
  revision: "site-version",
};
const source = {
  product_id: 8,
  variant_name: "أسود | L",
  location_id: null,
  quantity: 6,
  available: 6,
  movable: 6,
  basis_valid: true,
  cost: 1200,
  revision: "source-version",
};
const row = {
  ...source,
  id: 1,
  name: "شاشة اختبار",
  sku: "TV55",
  barcode: "123456789",
  image_url: "",
  model: "55",
  variant_id: 3,
  unit: "قطعة",
};
const draft: StorageDocument = {
  id: 9,
  number: "ST-TEST",
  branch_id: 2,
  branch_name: main.branch_name,
  from_location_id: null,
  to_location_id: 4,
  from_name: main.name,
  to_name: child.name,
  product_id: 8,
  product_name: row.name,
  sku: row.sku,
  image_url: "",
  variant_name: row.variant_name,
  quantity: 2,
  reason: "نقل للرف",
  status: "draft",
  revision: "document-version",
  created_at: "2026-10-14T00:00:00Z",
  cost: null,
  can_send: true,
  can_receive: false,
  can_cancel: true,
  source,
  layers: [],
};
function setup({ editable = true, cost = true, uncertain = false } = {}) {
  const requests: FinoraRequest[] = [];
  let document = { ...draft };
  const bridge = installMockBridge((request) => {
    requests.push(structuredClone(request));
    if (request.method === "POST") {
      if (uncertain && requests.filter((row) => row.method === "POST").length === 1)
        return { ok: false, failure: "network" };
      if (request.path.includes("/locations"))
        return {
          ok: true,
          status: 200,
          customerCommandScope: "scope",
          data: { success: true, data: { id: 4, type: "storage_location", location: child } },
        };
      if (request.path.endsWith("/send"))
        document = {
          ...document,
          status: "sent",
          can_send: false,
          can_receive: true,
          source: null,
          revision: "sent-version",
        };
      return {
        ok: true,
        status: 200,
        customerCommandScope: "scope",
        data: { success: true, data: { id: 9, type: "storage_transfer", document } },
      };
    }
    const data = request.path.endsWith("/meta")
      ? {
          places: [main, child, { ...child, id: 5, key: "storage:3:5", branch_id: 3, name: "فرع آخر" }],
          can_edit: editable,
          show_cost: cost,
        }
      : request.path.endsWith("/stocks")
        ? { items: [{ ...row, cost: cost ? row.cost : null }], page: 1, page_size: 25, total: 1 }
        : request.path.endsWith("/transfers")
          ? { items: requests.some((row) => row.method === "POST") ? [document] : [], page: 1, total: 1 }
          : document;
    return { ok: true, status: 200, data: { success: true, data } };
  });
  const acknowledge = vi.fn(async () => undefined);
  window.finoraDesktop = {
    ...bridge,
    stockRecovery: {
      acknowledge,
      list: vi.fn(async () => ({
        available: true,
        items: requests
          .filter((row) => row.method === "POST")
          .map((request) => ({
            key: String((request.body as Record<string, unknown>).operation_id),
            request,
            created: 0,
            state: "uncertain" as const,
          })),
      })),
      retry: vi.fn(async (): Promise<never> => {
        throw Error("not requested");
      }),
    },
  };
  const onBusyChange = vi.fn();
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <div dir="rtl">
        <StorageLocations
          scope="test:7:2"
          active
          serverUrl={null}
          onBusyChange={onBusyChange}
          onActivity={vi.fn()}
        />
      </div>
    </QueryClientProvider>,
  );
  return { requests, acknowledge, onBusyChange };
}
afterEach(removeMockBridge);
it("a reader sees balances without cost or mutation controls", async () => {
  const f = setup({ editable: false, cost: false });
  expect(await screen.findByText(row.name)).toBeInTheDocument();
  expect(screen.queryByText("إضافة مخزن")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "نقل" })).not.toBeInTheDocument();
  expect(screen.queryByText("قيمة القطع")).not.toBeInTheDocument();
  expect(f.requests.every((row) => row.method === "GET")).toBe(true);
});
it("changing page size uses the selected number in the API request", async () => {
  const f = setup();
  await screen.findByText(row.name);
  await userEvent.selectOptions(screen.getByRole("combobox", { name: "عدد الصفوف" }), "50");
  await waitFor(() =>
    expect(f.requests.some((row) => row.path.endsWith("/stocks") && row.query?.page_size === 50)).toBe(true),
  );
});
it("editing a location submits its current revision and branch without changing the primary site", async () => {
  const f = setup();
  await screen.findByText(row.name);
  await userEvent.click(screen.getByRole("button", { name: "إدارة المواقع" }));
  await userEvent.click(screen.getByRole("button", { name: "تعديل المخزن" }));
  await userEvent.clear(screen.getByLabelText("اسم المخزن"));
  await userEvent.type(screen.getByLabelText("اسم المخزن"), "مخزن الأجهزة");
  await userEvent.click(screen.getByRole("button", { name: "حفظ المخزن" }));
  await waitFor(() => expect(f.acknowledge).toHaveBeenCalledTimes(1));
  const writes = f.requests.filter((row) => row.method === "POST");
  expect(writes).toHaveLength(1);
  expect(writes[0]?.path).toMatch(/\/locations\/4$/);
  expect(writes[0]?.body).toMatchObject({
    branch_id: 2,
    revision: "site-version",
    name: "مخزن الأجهزة",
    kind: "storage",
    is_active: true,
  });
});
async function openTransfer() {
  await screen.findByText(row.name);
  await userEvent.click(screen.getByRole("button", { name: "نقل" }));
  const panel = screen.getByRole("complementary", { name: "تحويل داخلي جديد" });
  expect(within(panel).queryByRole("option", { name: "فرع آخر" })).not.toBeInTheDocument();
  await userEvent.clear(within(panel).getByLabelText("كمية القطع"));
  await userEvent.type(within(panel).getByLabelText("كمية القطع"), "2");
  await userEvent.type(within(panel).getByLabelText("سبب النقل"), "نقل للرف");
  return panel;
}
it("preserves product variant and source, creates only a draft, then confirms physical sending separately", async () => {
  const f = setup();
  await openTransfer();
  expect(f.requests.filter((row) => row.method === "POST")).toHaveLength(0);
  await userEvent.click(screen.getByRole("button", { name: "حفظ المسودة" }));
  const send = await screen.findByRole("button", { name: "إرسال القطع" });
  const writes = () => f.requests.filter((row) => row.method === "POST");
  expect(writes()).toHaveLength(1);
  expect(writes()[0]?.body).toMatchObject({
    branch_id: 2,
    product_id: 8,
    variant_name: row.variant_name,
    from_location_id: null,
    to_location_id: 4,
    quantity: 2,
  });
  await userEvent.click(send);
  expect(writes()).toHaveLength(1);
  await userEvent.click(screen.getByRole("button", { name: "تأكيد العملية" }));
  await waitFor(() => expect(writes()).toHaveLength(2));
  expect(writes()[1]?.body).toMatchObject({
    revision: "document-version",
    source_revision: "source-version",
    branch_id: 2,
  });
  await waitFor(() => expect(f.acknowledge).toHaveBeenCalledTimes(2));
});
it("an uncertain save freezes edits and retries the exact UUID and payload", async () => {
  const f = setup({ uncertain: true });
  const panel = await openTransfer();
  await userEvent.click(screen.getByRole("button", { name: "حفظ المسودة" }));
  await screen.findByRole("button", { name: "إعادة نفس الطلب" });
  expect(within(panel).getByLabelText("كمية القطع")).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "إعادة نفس الطلب" }));
  await waitFor(() => expect(f.requests.filter((row) => row.method === "POST")).toHaveLength(2));
  const writes = f.requests.filter((row) => row.method === "POST");
  expect(writes[1]).toEqual(writes[0]);
});
