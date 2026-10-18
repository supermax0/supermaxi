/**
 * New-purchase composer state. Kept in memory while the app runs, so closing
 * the composer never loses an unfinished invoice. Totals mirror FINORA's
 * formula in routes/purchases.py (_create_purchase_from_payload); FINORA still
 * recomputes everything on save.
 */
import { create } from "zustand";
import type { NewPurchase, PurchaseProduct } from "@/api/finora/purchases";

export type PayMode = "cash" | "credit" | "bank";

export interface ComposerLine {
  key: string;
  productId: number;
  name: string;
  sku: string;
  stock: number;
  colors: string[];
  color: string;
  optionDetails?: PurchaseProduct["colors"];
  baseUnitCost?: number;
  qty: number;
  unitCost: number;
  discount: number;
}

export interface ComposerSupplier {
  id: number;
  name: string;
}

interface ComposerState {
  open: boolean;
  supplier: ComposerSupplier | null;
  supplierInvoiceNo: string;
  date: string;
  notes: string;
  lines: ComposerLine[];
  discount: number;
  shippingExtra: number;
  mode: PayMode;
  bankAccountId: number | null;
  downPayment: number;
  lastAdded: { key: string; at: number } | null;
  setOpen(open: boolean): void;
  patch(
    patch: Partial<
      Pick<
        ComposerState,
        | "supplier"
        | "supplierInvoiceNo"
        | "date"
        | "notes"
        | "discount"
        | "shippingExtra"
        | "mode"
        | "bankAccountId"
        | "downPayment"
      >
    >,
  ): void;
  addProduct(product: PurchaseProduct): ComposerLine;
  updateLine(
    key: string,
    patch: Partial<Pick<ComposerLine, "qty" | "unitCost" | "discount" | "color">>,
  ): void;
  removeLine(key: string): void;
  reset(): void;
}

export function today(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

let nextKey = 1;

function blank() {
  return {
    supplier: null,
    supplierInvoiceNo: "",
    date: today(),
    notes: "",
    lines: [] as ComposerLine[],
    discount: 0,
    shippingExtra: 0,
    mode: "credit" as PayMode,
    bankAccountId: null,
    downPayment: 0,
    lastAdded: null,
  };
}

export const useComposer = create<ComposerState>()((set, get) => ({
  open: false,
  ...blank(),
  setOpen(open) {
    set({ open });
  },
  patch(patch) {
    set(patch);
  },
  addProduct(product) {
    // Same product without colours → bump the quantity instead of a second line.
    const existing = product.has_colors ? undefined : get().lines.find((l) => l.productId === product.id);
    if (existing) {
      const updated = { ...existing, qty: existing.qty + 1 };
      set({
        lines: get().lines.map((l) => (l.key === existing.key ? updated : l)),
        lastAdded: { key: existing.key, at: Date.now() },
      });
      return updated;
    }
    const line: ComposerLine = {
      key: `l${nextKey++}`,
      productId: product.id,
      name: product.name,
      sku: product.sku || product.barcode,
      stock: product.quantity,
      colors: product.has_colors ? product.colors.filter((c) => c.active !== false).map((c) => c.name) : [],
      optionDetails: product.colors,
      baseUnitCost: product.buy_price,
      color: "",
      qty: 1,
      unitCost: product.buy_price,
      discount: 0,
    };
    set({ lines: [...get().lines, line], lastAdded: { key: line.key, at: Date.now() } });
    return line;
  },
  updateLine(key, patch) {
    set({
      lines: get().lines.map((l) => {
        if (l.key !== key) return l;
        const selected = patch.color
          ? l.optionDetails?.find((option) => option.name === patch.color)
          : undefined;
        return {
          ...l,
          ...(patch.color ? { unitCost: selected?.buy_price ?? l.baseUnitCost ?? l.unitCost } : {}),
          ...patch,
        };
      }),
    });
  },
  removeLine(key) {
    set({ lines: get().lines.filter((l) => l.key !== key) });
  },
  reset() {
    set(blank());
  },
}));

export function lineTotal(line: ComposerLine): number {
  return Math.max(line.unitCost - line.discount, 0) * line.qty;
}

export function composerTotals(state: Pick<ComposerState, "lines" | "discount" | "shippingExtra">) {
  const subtotal = state.lines.reduce((sum, line) => sum + lineTotal(line), 0);
  const grand = Math.max(subtotal - state.discount + state.shippingExtra, 0);
  return { subtotal, grand, units: state.lines.reduce((sum, line) => sum + line.qty, 0) };
}

/** Local checks with FINORA's own wording; returns the first problem or null. */
export function validateComposer(state: ComposerState): string | null {
  if (!state.supplier) return "اختر المورد أو أضف مورداً جديداً.";
  if (state.lines.length === 0) return "يجب إضافة عنصر واحد على الأقل.";
  for (const [index, line] of state.lines.entries()) {
    if (line.qty <= 0) return `كمية «${line.name}» يجب أن تكون أكبر من صفر.`;
    if (line.discount > line.unitCost) return `خصم العنصر رقم ${index + 1} أكبر من سعر الوحدة.`;
    if (line.colors.length > 0 && !line.color) return `يجب اختيار خيار للمنتج: ${line.name}`;
  }
  const { subtotal, grand } = composerTotals(state);
  if (state.discount > subtotal) return "الخصم الإجمالي لا يمكن أن يتجاوز مجموع المنتجات";
  if (state.mode === "credit" && state.downPayment > grand) return "الدفعة المقدمة أكبر من إجمالي الفاتورة.";
  return null;
}

export function toNewPurchase(state: ComposerState, confirm: boolean): NewPurchase {
  const { grand } = composerTotals(state);
  const payments: NewPurchase["payments"] = [];
  if (state.mode === "bank" && state.bankAccountId) {
    payments.push({ amount: grand, payment_method: "bank", treasury_account_id: state.bankAccountId });
  } else if (state.mode === "credit" && state.downPayment > 0) {
    payments.push({ amount: state.downPayment, payment_method: "cash" });
  }
  return {
    supplierId: state.supplier?.id ?? 0,
    purchaseDate: state.date,
    mode: state.mode,
    confirm,
    supplierInvoiceNo: state.supplierInvoiceNo,
    notes: state.notes,
    discount: state.discount,
    shippingExtra: state.shippingExtra,
    lines: state.lines.map((line) => ({
      product_id: line.productId,
      quantity: line.qty,
      unit_cost_before_discount: line.unitCost,
      discount_value: line.discount,
      color: line.color || undefined,
    })),
    payments,
  };
}
