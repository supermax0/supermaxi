import { z } from "zod";

export const PERMISSIONS = [
  "can_see_orders",
  "can_see_orders_placed",
  "can_see_orders_packed",
  "can_see_orders_shipped",
  "can_see_orders_delivered",
  "can_see_orders_returned",
  "manage_orders",
  "manage_settings",
  "delete_orders",
  "return_orders",
  "pay_orders",
  "print_pos_invoice",
  "can_manage_inventory",
  "wholesale_warehouses",
  "inventory.audit.view",
  "inventory.audit.count",
  "inventory.audit.system",
  "inventory.audit.cost",
  "inventory.audit.investigate",
  "inventory.audit.review",
  "inventory.audit.approve",
  "inventory.audit.post",
  "inventory.audit.export",
  "edit_product",
  "edit_price",
  "edit_current_stock",
  "can_manage_suppliers",
  "manage_customers",
  "view_all_branches",
  "view_pos",
  "view_reports",
  "view_financial",
  "view_expenses",
  "view_accounts",
  "can_see_shipping",
  "can_manage_shipping",
  "manage_employees",
  "manage_permissions",
  "pricing.view",
  "pricing.manage",
  "pricing.approve",
  "manage_branches",
  "view_branch_reports",
  "manage_branch_staff",
  "run_branch_distribution",
  "allocate_branch_expenses",
  "merge_delivery_agents",
  "hr.view",
  "finance.view",
  "finance.create",
  "finance.approve",
  "finance.approve_large",
  "finance.reverse",
  "finance.print",
  "finance.loans",
  "finance.reconcile",
  "finance.ledger",
  "finance.settings",
  "hr.self",
  "hr.employees.create",
  "hr.employees.edit",
  "hr.employees.state",
  "hr.documents.view",
  "hr.attendance.view",
  "hr.attendance.record",
  "hr.attendance.approve",
  "hr.shifts.manage",
  "hr.payroll.view",
  "hr.payroll.prepare",
  "hr.payroll.review",
  "hr.payroll.approve",
  "hr.payroll.pay",
  "hr.advance.view",
  "hr.advance.create",
  "hr.advance.approve",
  "hr.advance.pay",
  "hr.commission.view",
  "hr.commission.manage",
  "hr.commission.pay",
  "hr.leave.manage",
  "hr.leave.approve",
  "hr.resources.manage",
  "hr.recruitment.manage",
  "hr.settings.manage",
  "hr.reports.view",
] as const;
export type Permission = (typeof PERMISSIONS)[number];

const permissionSchema = z.string().transform((value, ctx): Permission => {
  if ((PERMISSIONS as readonly string[]).includes(value)) return value as Permission;
  ctx.addIssue({ code: z.ZodIssueCode.custom, message: `unknown permission ${value}` });
  return z.NEVER;
});

export const sessionSchema = z.object({
  user: z.object({
    id: z.number().int(),
    name: z.string(),
    username: z.string(),
    role: z.string().nullable(),
  }),
  tenant: z.object({
    id: z.number().int().nullable(),
    slug: z.string(),
    name: z.string().nullable(),
    business_type: z.string(),
  }),
  branch: z.object({ id: z.number().int(), name: z.string() }).nullable(),
  branch_scope: z.enum(["branch", "all", "shared"]).optional(),
  roles: z.array(z.string()),
  // Unknown (newer) permission names are dropped, never trusted.
  permissions: z.array(z.unknown()).transform((items) =>
    items.flatMap((item) => {
      const parsed = permissionSchema.safeParse(item);
      return parsed.success ? [parsed.data] : [];
    }),
  ),
  session_max_age_seconds: z.number().int().nonnegative(),
  hr_scope_revision: z.string().optional(),
  offline_pos_enabled: z.boolean().optional(),
  display_time_format: z.enum(["12", "24"]).optional(),
});
export type FinoraSession = z.infer<typeof sessionSchema>;

export const sessionEnvelopeSchema = z
  .object({ ok: z.literal(true), session: sessionSchema })
  .transform((value) => value.session);

export const signOutSchema = z.object({ ok: z.literal(true), signed_out: z.literal(true) });
