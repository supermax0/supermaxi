import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { FinoraResponse, FinoraDesktopBridge } from "@shared/ipc";
import type { SavedCustomerCommand } from "@shared/customerRecovery";
import { installMockBridge, removeMockBridge, SESSION_PAYLOAD } from "@/test/mockBridge";
import { useSession } from "@/stores/session";
import { useConnection } from "@/stores/connection";
import { CustomerRecovery } from "./CustomerRecovery";
import { finora } from "@/api/finora";

const scope = "a".repeat(64),
  key = "ea9b2e0c-b377-467f-a214-9c7204df0f38";
const item: SavedCustomerCommand = {
  key,
  created: Date.now(),
  state: "uncertain",
  request: {
    method: "POST",
    path: "/api/v1/desktop/customers/1/debts",
    body: {
      idempotency_key: key,
      source_reference: "EXT-001",
      amount: 90000,
      count: 3,
      reason: "كشف خارجي",
      first_due_date: "2027-01-31",
      interval: "monthly",
    },
  },
};
const schedule = {
  id: 8,
  customer_id: 1,
  invoice_id: null,
  total: 90000,
  paid: 0,
  revision: "b".repeat(64),
  installments: [],
  history: [],
  history_total: 0,
};
afterEach(removeMockBridge);
it("refuses a customer write through an older main bridge without durable recovery", async () => {
  const f = setup();
  f.bridge.customerRecovery = undefined;
  await expect(
    finora.customers.createDebt(
      1,
      {
        revision: "a".repeat(64),
        reason: "كشف خارجي",
        amount: 90000,
        source_type: "opening",
        source_reference: "EXT-001",
        count: 3,
        first_due_date: "2027-01-31",
        interval: "monthly",
      },
      key,
    ),
  ).rejects.toMatchObject({ kind: "refused" });
  expect(f.bridge.finora.request).not.toHaveBeenCalled();
});
function setup(
  response: FinoraResponse = {
    ok: true,
    status: 200,
    customerCommandScope: scope,
    data: { success: true, data: schedule },
  },
  editing = false,
) {
  const bridge: FinoraDesktopBridge = installMockBridge(() => ({ ok: false, failure: "network" }));
  let saved = [item];
  const acknowledge = vi.fn(async () => {
    saved = [];
  });
  const retry = vi.fn(async () => ({ request: item.request, response }));
  bridge.customerRecovery = { list: async () => ({ available: true, items: saved }), retry, acknowledge };
  useSession
    .getState()
    .signedIn({ ...SESSION_PAYLOAD, permissions: ["manage_customers", "finance.view", "finance.settings"] });
  useConnection.setState({ status: "online" });
  const onRecovered = vi.fn();
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <CustomerRecovery active editing={editing} onRecovered={onRecovered} />
    </QueryClientProvider>,
  );
  return { bridge, acknowledge, retry, onRecovered };
}
it("reviews the original debt reference, amount and schedule, explains recovery, then validates and acknowledges the same key and scope", async () => {
  const f = setup(),
    user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "شرح استرجاع طلبات الحفظ" }));
  expect(screen.getByRole("note")).toHaveTextContent("مشفراً");
  await user.keyboard("{Escape}");
  await user.click(screen.getByRole("button", { name: "طلبات الحفظ المحفوظة" }));
  expect(screen.getByRole("complementary", { name: "طلبات الحفظ المحفوظة" })).toHaveStyle({ zIndex: 40 });
  await waitFor(() => {
    expect(screen.getByText("المرجع: EXT-001")).toBeVisible();
    expect(screen.getByText(/90,000/)).toBeVisible();
    expect(screen.getByText(/2027-01-31/)).toBeVisible();
  });
  await user.click(screen.getByRole("button", { name: "تأكيد نفس الطلب" }));
  await waitFor(() => expect(f.onRecovered).toHaveBeenCalledWith(1));
  expect(f.retry).toHaveBeenCalledWith(key);
  expect(f.acknowledge).toHaveBeenCalledWith({ key, path: item.request.path, scope });
});
it.each(["network", "malformed", "missing-scope"])(
  "keeps the original request reviewable after an %s recovery failure",
  async (kind) => {
    const response: FinoraResponse =
      kind === "network"
        ? { ok: false, failure: "network" }
        : {
            ok: true,
            status: 200,
            ...(kind !== "missing-scope" ? { customerCommandScope: scope } : {}),
            data: { success: true, data: kind === "malformed" ? { id: 8 } : schedule },
          };
    const f = setup(response),
      user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "طلبات الحفظ المحفوظة" }));
    await user.click(screen.getByRole("button", { name: "تأكيد نفس الطلب" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("يبقى الطلب محفوظاً");
    expect(f.acknowledge).not.toHaveBeenCalled();
    expect(f.onRecovered).not.toHaveBeenCalled();
  },
);
it("shows stored requests offline but prevents transmission", async () => {
  const f = setup();
  useConnection.setState({ status: "offline" });
  await userEvent.setup().click(await screen.findByRole("button", { name: "طلبات الحفظ المحفوظة" }));
  expect(screen.getByRole("button", { name: "تأكيد نفس الطلب" })).toBeDisabled();
  expect(f.retry).not.toHaveBeenCalled();
});
it("preserves an open customer editor by requiring it to close before opening recovery", async () => {
  const f = setup(undefined, true);
  const button = await screen.findByRole("button", { name: "طلبات الحفظ المحفوظة" });
  expect(button).toBeDisabled();
  await userEvent.setup().click(button);
  expect(screen.queryByRole("complementary", { name: "طلبات الحفظ المحفوظة" })).not.toBeInTheDocument();
  expect(f.retry).not.toHaveBeenCalled();
});
it("does not acknowledge an incomplete normal save response", async () => {
  const f = setup();
  const request = vi.fn(async (): Promise<FinoraResponse> => ({
    ok: true,
    status: 200,
    customerCommandScope: scope,
    data: { success: true, data: { id: 8 } },
  }));
  f.bridge.finora.request = request;
  await expect(
    finora.customers.createDebt(
      1,
      {
        revision: "a".repeat(64),
        reason: "كشف خارجي",
        amount: 90000,
        source_type: "opening",
        source_reference: "EXT-001",
        count: 3,
        first_due_date: "2027-01-31",
        interval: "monthly",
      },
      key,
    ),
  ).rejects.toMatchObject({ kind: "invalid_response" });
  expect(f.acknowledge).not.toHaveBeenCalled();
});
it("selects another saved request and keeps confirmation in the pinned footer", async () => {
  const f = setup(),
    user = userEvent.setup();
  const otherKey = "acf451af-5b7a-4dd0-8712-2392bbebfd63";
  const other = {
    ...item,
    key: otherKey,
    request: {
      ...item.request,
      path: "/api/v1/desktop/customers/2/debts",
      body: { idempotency_key: otherKey, reason: "طلب العميل الثاني" },
    },
  };
  if (!f.bridge.customerRecovery) throw Error("No recovery bridge");
  f.bridge.customerRecovery.list = async () => ({
    available: true,
    items: [item, other],
  });
  f.retry.mockImplementationOnce(async () => ({
    request: other.request,
    response: {
      ok: true,
      status: 200,
      customerCommandScope: scope,
      data: { success: true, data: { ...schedule, customer_id: 2 } },
    },
  }));
  await user.click(await screen.findByRole("button", { name: "طلبات الحفظ المحفوظة" }));
  await user.click(screen.getByRole("button", { name: "تحديث الطلبات" }));
  await user.click(await screen.findByRole("button", { name: "اختيار هذا الطلب" }));
  const confirm = screen.getByRole("button", { name: "تأكيد نفس الطلب" });
  expect(confirm.closest("footer")).not.toBeNull();
  expect(screen.getByText(/الطلب المختار:.*العميل #2/)).toBeVisible();
  await user.click(confirm);
  await waitFor(() => expect(f.retry).toHaveBeenCalledWith(otherKey));
  await waitFor(() => expect(f.onRecovered).toHaveBeenCalledWith(2));
  expect(f.acknowledge).toHaveBeenCalledWith({ key: otherKey, path: other.request.path, scope });
});
