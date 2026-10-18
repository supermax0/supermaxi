/**
 * Shipping-company barcode slots — one per piece, exactly like FINORA's web
 * order modal (templates/orders.html buildShippingBarcodeSlots). FINORA
 * re-validates (company required, no empty or repeated barcode).
 */
export interface BarcodeSlot {
  label: string;
}

export function shippingSlots(items: Array<{ name: string | null; qty: number }>): BarcodeSlot[] {
  const slots: BarcodeSlot[] = [];
  for (const item of items) {
    const qty = Math.max(0, Math.floor(item.qty));
    const name = item.name?.trim() || "منتج";
    for (let i = 1; i <= qty; i++) slots.push({ label: qty > 1 ? `${name} — ${i}` : name });
  }
  return slots.length ? slots : [{ label: "باركود الشحن" }];
}

/** Saved barcodes laid onto the slots (missing ones stay empty). */
export function initialBarcodes(
  slotCount: number,
  saved: { shipping_barcodes?: string[] | null; shipping_barcode?: string | null },
): string[] {
  const list = saved.shipping_barcodes?.length
    ? saved.shipping_barcodes
    : saved.shipping_barcode && saved.shipping_barcode !== "—"
      ? [saved.shipping_barcode]
      : [];
  return Array.from({ length: slotCount }, (_, i) => (list[i] ?? "").trim());
}

export function shippingBarcodeProblem(companyId: number | null, barcodes: string[]): string | null {
  if (!companyId) return "اختر شركة النقل.";
  const cleaned = barcodes.map((b) => b.trim());
  if (cleaned.some((b) => b.length > 200)) return "رقم الوصل لا يتجاوز 200 حرف.";
  if (cleaned.some((b) => !b))
    return cleaned.length > 1 ? "أدخل باركود الشحن لكل قطعة." : "أدخل باركود الشحن.";
  if (new Set(cleaned).size !== cleaned.length) return "لا يمكن تكرار نفس باركود الشحن.";
  return null;
}

const LAST_COMPANY_KEY = "finora.orders.lastShippingCompany";

/** Last company used for scanning on this computer (per-viewer convenience). */
export function rememberedShippingCompany(): number | null {
  try {
    const value = Number(window.localStorage.getItem(LAST_COMPANY_KEY));
    return Number.isInteger(value) && value > 0 ? value : null;
  } catch {
    return null;
  }
}

export function rememberShippingCompany(id: number): void {
  try {
    window.localStorage.setItem(LAST_COMPANY_KEY, String(id));
  } catch {
    // storage unavailable: nothing to remember
  }
}
