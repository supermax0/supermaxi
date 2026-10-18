import { z } from "zod";

export const reserveStockSchema = z
  .array(
    z
      .object({
        product_id: z.number().int().positive(),
        qty: z.number().int().positive().max(2147483647),
        variant_color: z.string().trim().max(80).optional(),
      })
      .strict(),
  )
  .min(1)
  .max(100);
export type ReserveStock = z.infer<typeof reserveStockSchema>;
export const stockGrantSchema = z.object({
  success: z.literal(true),
  id: z.string().uuid(),
  device_id: z.string().uuid(),
  employee_id: z.number().int().positive(),
  branch_id: z.number().int().positive(),
  allocations: z
    .array(
      z.object({
        id: z.string().uuid(),
        product_id: z.number().int().positive(),
        name: z.string().min(1),
        variant_color: z.string().max(80),
        quantity: z.number().int().positive().max(2147483647),
        sale_price: z.number().int().nonnegative(),
      }),
    )
    .min(1)
    .max(100),
});
export const stockPartsSchema = z
  .array(z.object({ id: z.string().uuid(), qty: z.number().int().positive() }).strict())
  .min(1)
  .max(1000);
export interface LocalStock {
  id: string;
  productId: number;
  name: string;
  color: string;
  quantity: number;
  available: number;
  used: number;
  returned: number;
  frozen: boolean;
}
export interface DeviceStockStatus {
  rows: LocalStock[];
  pendingRequest: boolean;
  busy: boolean;
  error: string | null;
}
