import { canReturnOrder } from "./status";

it("offers full return for shipped/delivered orders and preserves the server's refusal", () => {
  expect(canReturnOrder({ status: "جاري الشحن", payment_status: "ملغي" })).toBe(true);
  expect(canReturnOrder({ status: "تم التوصيل", payment_status: "مسدد" })).toBe(true);
  for (const status of ["تم الطلب", "ملغي", "راجع", "مرتجع"]) expect(canReturnOrder({ status })).toBe(false);
  expect(canReturnOrder({ status: "جاري الشحن", is_stock_locked: true, can_return: true })).toBe(false);
  expect(canReturnOrder({ status: "جاري الشحن", can_return: false })).toBe(false);
});
