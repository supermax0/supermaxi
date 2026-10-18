import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { SupplierRow } from "@/api/finora/suppliers";
import { useConnection } from "@/stores/connection";
import { installMockBridge, removeMockBridge } from "@/test/mockBridge";
import { SupplierSaleDialog } from "./SupplierSaleDialog";

const supplier: SupplierRow = {
  id: 7,
  name: "مورد التجربة",
  phone: "",
  phone2: "",
  address: "",
  opening_balance: 500,
  total_debt: 500,
  total_paid: 0,
  remaining: 500,
  total_purchases: 0,
  purchase_count: 0,
  payment_count: 0,
  last_transaction: "",
  created_at: "",
  member_count: 1,
};
const product = {
  id: 9,
  name: "شاشة التجربة",
  sku: "TV-TEST",
  barcode: "123456",
  quantity: 5,
  sale_price: 300,
  has_colors: false,
  colors: [],
};

afterEach(() => {
  removeMockBridge();
  useConnection.setState({ status: "online" });
});

it("keeps the sale draft after a stock rejection and prevents writes while offline", async () => {
  const bridge = installMockBridge((request) =>
    request.method === "GET"
      ? { ok: true, status: 200, data: [product] }
      : { ok: false, failure: "http", status: 400, data: { error: "تغير المخزون، الكمية غير متوفرة" } },
  );
  const close = vi.fn();
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <SupplierSaleDialog supplier={supplier} onClose={close} />
    </QueryClientProvider>,
  );
  const user = userEvent.setup();
  await user.type(screen.getByRole("searchbox"), "123456");
  await user.click(await screen.findByRole("button", { name: /شاشة التجربة.*المتوفر/ }));
  const quantity = screen.getByLabelText("كمية شاشة التجربة");
  await user.clear(quantity);
  await user.type(quantity, "2");
  await user.type(screen.getByLabelText(/ملاحظات/), "فاتورة تجربة");
  await user.click(screen.getByRole("button", { name: "تسجيل البيع" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("تغير المخزون");
  expect(quantity).toHaveValue(2);
  expect(screen.getByLabelText(/ملاحظات/)).toHaveValue("فاتورة تجربة");
  expect(close).not.toHaveBeenCalled();
  expect(bridge.finora.request.mock.calls.find(([r]) => r.method === "POST")?.[0]).toMatchObject({
    path: "/suppliers/api/7/sale",
    body: { items: [{ product_id: 9, qty: 2, price: 300 }], note: "فاتورة تجربة" },
  });
  act(() => useConnection.getState().setStatus("offline"));
  expect(screen.getByRole("button", { name: "حفظ مسودة للمزامنة" })).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "حفظ مسودة للمزامنة" }));
  await waitFor(() =>
    expect(bridge.finora.request.mock.calls.filter(([r]) => r.method === "POST")).toHaveLength(1),
  );
});
