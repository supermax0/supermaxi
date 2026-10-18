import { installMockBridge, removeMockBridge } from "@/test/mockBridge";
import { pos } from "./pos";
afterEach(removeMockBridge);
it("sends the exchange mode with its price and colour to the existing checkout", async () => {
  const bridge = installMockBridge(() => ({
    ok: true,
    status: 200,
    data: { success: true, invoice_id: 7, total: 650 },
  }));
  await pos.createOrder({
    customerId: 1,
    branchId: 2,
    orderId: null,
    discountAmount: 0,
    submissionToken: "exchange",
    lines: [{ product_id: 3, qty: 1, price: 650, color: "أزرق", sale_mode: "exchange" }],
  });
  expect(bridge.finora.request).toHaveBeenCalledWith(
    expect.objectContaining({
      body: expect.objectContaining({
        items: [{ product_id: 3, qty: 1, price: 650, color: "أزرق", sale_mode: "exchange" }],
      }),
    }),
  );
});
it("sends optional storage source as typed fields and leaves ordinary checkout unchanged", async () => {
  const bridge = installMockBridge(() => ({
    ok: true,
    status: 200,
    data: { success: true, invoice_id: 7, total: 400 },
  }));
  await pos.createOrder({
    customerId: 1,
    branchId: 2,
    orderId: null,
    discountAmount: 0,
    submissionToken: "original",
    lines: [{ product_id: 3, qty: 1, price: 400, storage_location_id: 7, storage_automatic: false }],
  });
  expect(bridge.finora.request).toHaveBeenLastCalledWith(
    expect.objectContaining({
      body: expect.objectContaining({
        items: [{ product_id: 3, qty: 1, price: 400, storage_location_id: 7, storage_automatic: false }],
      }),
    }),
  );
  await pos.createOrder({
    customerId: 1,
    branchId: 2,
    orderId: null,
    discountAmount: 0,
    submissionToken: "ordinary",
    lines: [{ product_id: 3, qty: 1, price: 400 }],
  });
  expect(bridge.finora.request).toHaveBeenLastCalledWith(
    expect.objectContaining({
      body: expect.objectContaining({
        items: [{ product_id: 3, qty: 1, price: 400 }],
      }),
    }),
  );
});
