import type { PosProduct } from "@/api/finora/pos";
import { cartTotals, useCart } from "./cart";
import { pickAccount } from "./useCheckout";

const product = (id: number, price: number, extra: Partial<PosProduct> = {}): PosProduct => ({
  id,
  name: `P${id}`,
  sku: `SKU${id}`,
  barcode: "",
  price,
  quantity: 5,
  image_url: "",
  category: "",
  has_colors: false,
  colors: [],
  ...extra,
});

describe("POS cart", () => {
  beforeEach(() => useCart.getState().reset("cash"));
  it("keeps an optional storage source and renews the submission token when it changes", () => {
    useCart.getState().add(product(1, 1000));
    const original = useCart.getState().takeSubmissionToken();
    const line = useCart.getState().lines[0];
    if (!line) throw Error("missing line");
    useCart
      .getState()
      .setStorageSource(line.key, { key: "7", id: 7, name: "المخزن الخلفي", automatic: false });
    expect(useCart.getState().lines[0]?.storageSource?.id).toBe(7);
    expect(useCart.getState().takeSubmissionToken()).not.toBe(original);
    useCart.getState().setStorageSource(line.key, undefined);
    expect(useCart.getState().lines[0]?.storageSource).toBeUndefined();
  });

  it("adds, merges the same product/colour, and keeps colours as separate lines", () => {
    const cart = useCart.getState();
    cart.add(product(1, 1000));
    cart.add(product(1, 1000));
    cart.add(
      product(2, 500, { has_colors: true, colors: [{ name: "أزرق", qty: 1, sale_price: 600 }] }),
      "أزرق",
    );
    const { lines } = useCart.getState();
    expect(lines.map((l) => [l.productId, l.qty, l.unitPrice, l.color])).toEqual([
      [1, 2, 1000, ""],
      [2, 1, 600, "أزرق"],
    ]);
  });

  it("qty 0 removes the line; edits invalidate the submission token", () => {
    const line = useCart.getState().add(product(1, 1000));
    const token = useCart.getState().takeSubmissionToken();
    expect(useCart.getState().takeSubmissionToken()).toBe(token);
    useCart.getState().setQty(line.key, 3);
    expect(useCart.getState().takeSubmissionToken()).not.toBe(token);
    useCart.getState().setQty(line.key, 0);
    expect(useCart.getState().lines).toHaveLength(0);
  });

  it("keeps sale and exchange separate for the same colour and uses the exchange price", () => {
    const item = product(2, 1000, {
      has_exchange_sale: true,
      exchange_sale_price: 650,
      has_colors: true,
      colors: [{ name: "أزرق", qty: 2, sale_price: 1200 }],
    });
    const cart = useCart.getState();
    cart.add(item, "أزرق");
    cart.add(item, "أزرق", "exchange");
    cart.add(item, "أزرق", "exchange");
    const lines = useCart.getState().lines;
    expect(lines.map((line) => [line.saleMode, line.unitPrice, line.qty, line.available])).toEqual([
      ["normal", 1200, 1, 2],
      ["exchange", 650, 2, 2],
    ]);
    expect(new Set(lines.map((line) => line.key)).size).toBe(2);
    expect(cartTotals(lines, "amount", 0).total).toBe(2500);
  });

  it("rejects exchange when the server has not enabled it for the product", () => {
    expect(() => useCart.getState().add(product(1, 1000), "", "exchange")).toThrow("غير مفعّل");
    expect(useCart.getState().lines).toEqual([]);
  });

  it("totals: fixed and percent discounts are clamped to the subtotal", () => {
    const base = { name: "", detail: "", imageUrl: "", color: "", available: 1 };
    const lines = [
      { ...base, key: "a", productId: 1, unitPrice: 282000, qty: 1 },
      { ...base, key: "b", productId: 2, unitPrice: 320000, qty: 2 },
    ];
    expect(cartTotals(lines, "amount", 22000)).toEqual({
      subtotal: 922000,
      discount: 22000,
      total: 900000,
      items: 3,
    });
    expect(cartTotals(lines, "percent", 10).discount).toBe(92200);
    expect(cartTotals(lines, "percent", 400).total).toBe(0);
    expect(cartTotals(lines, "amount", 5_000_000).total).toBe(0);
  });

  it("cash goes to the branch's cash drawer; bank needs the chosen account", () => {
    const accounts = [
      { id: 1, name: "صندوق فرع آخر", type: "cash", is_default: true, branch_id: 2, label: "" },
      { id: 2, name: "صندوق الفرع", type: "cash", is_default: false, branch_id: 1, label: "" },
      { id: 3, name: "مصرف", type: "bank", is_default: false, branch_id: 1, label: "" },
    ];
    expect(pickAccount(accounts, "cash", 1, null)?.id).toBe(2);
    expect(pickAccount(accounts, "bank", 1, null)).toBeNull();
    expect(pickAccount(accounts, "bank", 1, 3)?.id).toBe(3);
  });
});
