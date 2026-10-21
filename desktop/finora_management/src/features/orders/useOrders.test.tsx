import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { useConnection } from "@/stores/connection";
import { installMockBridge, removeMockBridge } from "@/test/mockBridge";
import { useAssignOrders, usePayOrder, useQuickEditOrder, useReturnOrders } from "./useOrders";
import { useToasts } from "@/stores/toasts";

afterEach(() => {
  removeMockBridge();
  useConnection.getState().setStatus("online");
});

it.each([null, 25])("refreshes the open shipping manifest after assigning agent %s", async (targetId) => {
  useConnection.getState().setStatus("online");
  installMockBridge(() => ({ ok: true, status: 200, data: { success: true } }));
  const client = new QueryClient();
  client.setQueryData(["shipping", "manifest", 80], { amount: 100 });
  const { result, unmount } = renderHook(() => useAssignOrders(), {
    wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>,
  });
  await act(async () => {
    await result.current.mutateAsync({ kind: "agent", ids: [201], targetId });
  });
  expect(client.getQueryState(["shipping", "manifest", 80])?.isInvalidated).toBe(true);
  unmount();
  client.clear();
});

it("refreshes settlement amounts after a quick price edit", async () => {
  useConnection.getState().setStatus("online");
  installMockBridge(() => ({ ok: true, status: 200, data: { success: true } }));
  const client = new QueryClient();
  client.setQueryData(["shipping", "manifest", 80], { amount: 100 });
  const { result, unmount } = renderHook(() => useQuickEditOrder(), {
    wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>,
  });
  await act(async () => {
    await result.current.mutateAsync({
      id: 201,
      input: {
        note: null,
        discount_amount: 0,
        items: [{ product_id: 1, qty: 1, price: 150, color: "", sale_mode: "credit" }],
      },
    });
  });
  expect(client.getQueryState(["shipping", "manifest", 80])?.isInvalidated).toBe(true);
  unmount();
  client.clear();
});

it("reports partial returns and skipped replays honestly while refreshing every affected section", async () => {
  useConnection.getState().setStatus("online");
  useToasts.setState({ toasts: [] });
  const requests: unknown[] = [];
  installMockBridge((request) => {
    requests.push(request.body);
    return {
      ok: true,
      status: 200,
      data: {
        success: true,
        updated: 1,
        updated_ids: [12],
        skipped: [{ id: 13, message: "راجع مسبقاً" }],
        failed: [{ id: 14, error: "طلب تم الطلب يُلغى" }],
      },
    };
  });
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  const keys = ["orders", "products", "customers", "finance", "reports", "pos"];
  keys.forEach((key) => client.setQueryData([key, "cached"], { amount: 800 }));
  const { result, unmount } = renderHook(() => useReturnOrders(), {
    wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>,
  });
  await act(async () => {
    await result.current.mutateAsync({ ids: [12, 13, 14], branchId: 2 });
  });
  expect(requests).toEqual([{ order_ids: [12, 13, 14], return_branch_id: 2 }]);
  keys.forEach((key) => expect(client.getQueryState([key, "cached"])?.isInvalidated).toBe(true));
  const messages = useToasts.getState().toasts;
  expect(messages.find((row) => row.tone === "success")?.message).toContain("تم إرجاع الطلب");
  expect(messages.find((row) => row.tone === "success")?.message).not.toContain("3 طلبات");
  expect(messages.find((row) => row.tone === "info")?.message).toContain("#13");
  expect(messages.find((row) => row.tone === "error")?.message).toContain("#14");
  unmount();
  client.clear();
  useToasts.setState({ toasts: [] });
});

it("marks cached debt, accounts and sales figures stale after an order collection", async () => {
  useConnection.getState().setStatus("online");
  const paths: string[] = [];
  installMockBridge((request) => {
    paths.push(request.path);
    return { ok: true, status: 200, data: { success: true } };
  });
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  const affected = [
    ["orders", "details", 12],
    ["customers", "detail", 8],
    ["finance", "trial"],
    ["reports", "sales"],
    ["products", "list"],
    ["pos", "products"],
  ];
  affected.forEach((key) => client.setQueryData(key, { amount: 100_000 }));
  client.setQueryData(["settings", "printers"], { name: "Receipt printer" });
  const { result, unmount } = renderHook(() => usePayOrder(), {
    wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>,
  });
  await act(async () => {
    await result.current.mutateAsync({
      orderId: 12,
      mode: "partial",
      amount: 25_000,
      deliveryFee: 0,
      branchId: 1,
      allocations: [{ treasury_account_id: 4, amount: 25_000 }],
    });
  });
  expect(paths).toEqual(["/orders/payment"]);
  affected.forEach((key) => expect(client.getQueryState(key)?.isInvalidated).toBe(true));
  expect(client.getQueryState(["settings", "printers"])?.isInvalidated).toBe(false);
  unmount();
  client.clear();
});
