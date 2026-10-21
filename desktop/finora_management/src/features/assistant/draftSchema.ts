import { z } from "zod";
const text = z.string().trim().max(150);
const note = z.string().max(2000);
const id = z.number().int().positive();
const phone = z.string().max(20);
const money = z.number().finite().nonnegative().max(1e12);
const item = z
  .object({
    product_id: z.number().int().positive(),
    quantity: z.number().finite().positive().max(10000),
    color: z.string().max(100).optional(),
  })
  .strict();
export const draftSchemas = {
  product: z
    .object({
      name: text.optional(),
      sku: text.optional(),
      barcode: text.optional(),
      description: note.optional(),
      buyPrice: money.optional(),
      salePrice: money.optional(),
    })
    .strict(),
  customer: z
    .object({
      name: text.optional(),
      phone: z.string().max(20).optional(),
      city: z.string().max(100).optional(),
      address: z.string().max(255).optional(),
      note: note.optional(),
    })
    .strict(),
  expense: z.object({ title: text.optional(), amount: money.optional(), note: note.optional() }).strict(),
  receipt: z.object({ amount: money.optional(), note: note.optional() }).strict(),
  sale: z.object({ items: z.array(item).max(12).optional() }).strict(),
  purchase: z
    .object({
      items: z
        .array(
          z
            .object({
              product_id: id,
              quantity: z.number().finite().positive().max(10000),
              color: z.string().max(100).optional(),
              // Supplier invoice price, read from a photo or typed by the user; reviewed in the form.
              unitCost: money.optional(),
            })
            .strict(),
        )
        .max(12)
        .optional(),
      note: note.optional(),
      supplierInvoiceNo: text.optional(),
    })
    .strict(),
  supplier: z
    .object({
      name: text.optional(),
      phone: phone.optional(),
      phone2: phone.optional(),
      address: z.string().max(255).optional(),
    })
    .strict(),
  supplier_payment: z
    .object({
      supplier_id: id,
      amount: money.optional(),
      documentNumber: text.optional(),
      note: note.optional(),
    })
    .strict(),
  return: z.object({ order_id: id }).strict(),
  transfer: z.object({ items: z.array(item).min(1).max(12), note: note.optional() }).strict(),
};
export type DraftKind = keyof typeof draftSchemas;
export function validateDraft(kind: string, fields: unknown): Record<string, unknown> {
  if (!Object.hasOwn(draftSchemas, kind)) throw Error("نوع المسودة غير مدعوم");
  const parsed = draftSchemas[kind as DraftKind].safeParse(fields);
  if (!parsed.success)
    throw Error(
      "المسودة تتضمن حقولاً غير مدعومة أو قيماً غير صالحة. اطلب حقولاً أساسية فقط، وحدد الأطراف والحسابات داخل النموذج الأصلي.",
    );
  return parsed.data;
}
