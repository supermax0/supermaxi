/**
 * POS cart. Prices shown here are FINORA's list prices; the final invoice is
 * priced by FINORA's checkout (create_pos_order), whose total is what the
 * cashier sees in the confirmation.
 */
import { create } from "zustand";
import type { PosCustomer, PosProduct } from "@/api/finora/pos";

export type SaleType = "cash" | "credit" | "bank";
export type DiscountMode = "amount" | "percent";
export type SaleMode = "normal" | "exchange";

export interface CartLine {
  key: string;
  productId: number;
  name: string;
  detail: string;
  imageUrl: string;
  color: string;
  saleMode?: SaleMode;
  unitPrice: number;
  qty: number;
  available: number;
  storageSource?: { key: string; id: number | null; automatic: boolean; name: string };
}

interface CartState {
  lines: CartLine[];
  customer: PosCustomer | null;
  saleType: SaleType;
  discountMode: DiscountMode;
  discountValue: number;
  editingOrderId: number | null;
  /** Last line added/incremented — the cart briefly highlights it. */
  lastAdded: { key: string; at: number } | null;
  /** Kept until a checkout succeeds so a retry is de-duplicated by FINORA. */
  submissionToken: string | null;
  add(product: PosProduct, color?: string, saleMode?: SaleMode): CartLine;
  setQty(key: string, qty: number): void;
  setPrice(key: string, price: number): void;
  setStorageSource(key: string, source: CartLine["storageSource"]): void;
  remove(key: string): void;
  clearLines(): void;
  setCustomer(customer: PosCustomer | null): void;
  setSaleType(type: SaleType): void;
  setDiscount(mode: DiscountMode, value: number): void;
  loadForEdit(orderId: number, customer: PosCustomer, lines: CartLine[], discount: number): void;
  takeSubmissionToken(): string;
  reset(saleType?: SaleType): void;
}

export function lineKey(productId: number, color = "", saleMode: SaleMode = "normal"): string {
  return `${productId}::${color}${saleMode === "exchange" ? "::exchange" : ""}`;
}

function newToken(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

const EMPTY = {
  lines: [] as CartLine[],
  customer: null,
  discountMode: "amount" as DiscountMode,
  discountValue: 0,
  editingOrderId: null,
  submissionToken: null,
  lastAdded: null,
};

export const useCart = create<CartState>()((set, get) => ({
  ...EMPTY,
  saleType: "cash",
  setStorageSource(key, storageSource) {
    set({
      lines: get().lines.map((line) => (line.key === key ? { ...line, storageSource } : line)),
      submissionToken: null,
    });
  },
  add(product, color = "", saleMode = "normal") {
    const exchangePrice = product.exchange_sale_price ?? 0;
    if (saleMode === "exchange" && (!product.has_exchange_sale || exchangePrice <= 0))
      throw new Error("الاستبدال غير مفعّل لهذا المنتج.");
    const key = lineKey(product.id, color, saleMode);
    const existing = get().lines.find((line) => line.key === key);
    if (existing) {
      const updated = { ...existing, qty: existing.qty + 1 };
      set({
        lines: get().lines.map((line) => (line.key === key ? updated : line)),
        submissionToken: null,
        lastAdded: { key, at: Date.now() },
      });
      return updated;
    }
    const colorRow = color ? product.colors.find((c) => c.name === color) : undefined;
    const line: CartLine = {
      key,
      productId: product.id,
      name: product.name,
      detail: color || product.sku || product.category,
      imageUrl: colorRow?.image_url || product.image_url,
      color,
      saleMode,
      unitPrice: saleMode === "exchange" ? exchangePrice : colorRow?.sale_price || product.price,
      qty: 1,
      available: colorRow ? Number(colorRow.qty ?? 0) : product.quantity,
    };
    set({ lines: [...get().lines, line], submissionToken: null, lastAdded: { key, at: Date.now() } });
    return line;
  },
  setQty(key, qty) {
    if (qty <= 0) return get().remove(key);
    set({
      lines: get().lines.map((line) => (line.key === key ? { ...line, qty } : line)),
      submissionToken: null,
    });
  },
  setPrice(key, price) {
    set({
      lines: get().lines.map((line) =>
        line.key === key ? { ...line, unitPrice: Math.max(0, Math.round(price)) } : line,
      ),
      submissionToken: null,
    });
  },
  remove(key) {
    set({ lines: get().lines.filter((line) => line.key !== key), submissionToken: null });
  },
  clearLines() {
    set({ lines: [], submissionToken: null });
  },
  setCustomer(customer) {
    set({ customer, submissionToken: null });
  },
  setSaleType(saleType) {
    set({ saleType });
  },
  setDiscount(discountMode, discountValue) {
    set({ discountMode, discountValue: Math.max(0, discountValue), submissionToken: null });
  },
  loadForEdit(orderId, customer, lines, discount) {
    set({
      ...EMPTY,
      editingOrderId: orderId,
      customer,
      lines,
      discountMode: "amount",
      discountValue: discount,
    });
  },
  takeSubmissionToken() {
    const current = get().submissionToken;
    if (current) return current;
    const token = newToken();
    set({ submissionToken: token });
    return token;
  },
  reset(saleType) {
    set({ ...EMPTY, saleType: saleType ?? get().saleType });
  },
}));

export function cartTotals(lines: CartLine[], mode: DiscountMode, value: number) {
  const subtotal = lines.reduce((sum, line) => sum + line.unitPrice * line.qty, 0);
  const raw = mode === "percent" ? Math.round((subtotal * Math.min(value, 100)) / 100) : Math.round(value);
  const discount = Math.min(Math.max(0, raw), subtotal);
  return {
    subtotal,
    discount,
    total: subtotal - discount,
    items: lines.reduce((sum, line) => sum + line.qty, 0),
  };
}
