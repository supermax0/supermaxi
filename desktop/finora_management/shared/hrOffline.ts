import { z } from "zod";
export const hrCommandSchema = z
  .object({ id: z.string().uuid(), action: z.string().min(1).max(80), payload: z.record(z.unknown()) })
  .strict();
export type HRCommandInput = z.infer<typeof hrCommandSchema>;
const short = z.string().max(1000);
const employee = z
  .object({
    name: z.string().trim().min(1).max(150),
    code: short.optional(),
    phone: short.optional(),
    phone2: short.optional(),
    email: short.optional(),
    address: short.optional(),
    emergency_name: short.optional(),
    emergency_phone: short.optional(),
    notes: short.optional(),
    job_title: short.optional(),
    joined_on: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
    branch_id: z.number().int().positive(),
    department_id: z.number().int().positive().nullable().optional(),
  })
  .strict();
const localPayloads = {
  "employee.create": employee,
  "employee.update": employee
    .partial()
    .omit({ branch_id: true, joined_on: true })
    .extend({ person_id: z.number().int().positive(), version: z.number().int().positive() })
    .strict(),
  "attendance.record": z
    .object({
      person_id: z.number().int().positive(),
      event: z.enum(["check_in", "check_out"]),
      occurred_at: z.string().datetime(),
      shift_version: z.number().int().nonnegative().optional(),
      shift_id: z.number().int().positive().nullable().optional(),
      attendance_id: z.number().int().positive().optional(),
      check_in_command_id: z.string().uuid().optional(),
      source: z.literal("offline").optional(),
    })
    .strict(),
  "leave.request": z
    .object({
      person_id: z.number().int().positive(),
      type_id: z.number().int().positive(),
      starts: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
      ends: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
      half_day: z.boolean().optional(),
      reason: z.string().max(500).optional(),
    })
    .strict(),
  "attendance.correction_request": z
    .object({
      person_id: z.number().int().positive(),
      attendance_id: z.number().int().positive(),
      attendance_version: z.number().int().positive(),
      check_in: z.string().datetime(),
      check_out: z.string().datetime().or(z.literal("")).optional(),
      reason: z.string().min(1).max(500),
    })
    .strict(),
  "resource.record": z
    .object({
      person_id: z.number().int().positive(),
      kind: z.enum(["review", "goal", "warning", "note"]),
      title: z.string().min(1).max(150),
      note: z.string().max(2000).optional(),
      period: z.string().max(30).optional(),
      score: z.number().int().min(0).max(100).optional(),
    })
    .strict(),
};
export function offlineHRAllowed(command: HRCommandInput, permissions: readonly string[]): boolean {
  const has = (value: string) => permissions.includes(value);
  const key = command.action as keyof typeof localPayloads;
  const schema = localPayloads[key];
  if (!schema || !schema.safeParse(command.payload).success) return false;
  const grants: Record<keyof typeof localPayloads, boolean> = {
    "employee.create": has("hr.employees.create"),
    "employee.update": has("hr.employees.edit"),
    "attendance.record": has("hr.attendance.record") || has("hr.self"),
    "leave.request": has("hr.leave.manage") || has("hr.self"),
    "attendance.correction_request": has("hr.attendance.record") || has("hr.self"),
    "resource.record": has("hr.resources.manage"),
  };
  return grants[key];
}
export const hrOperationSchema = z
  .object({
    kind: z.literal("hr"),
    command: hrCommandSchema,
    localAllowed: z.boolean(),
    transmitted: z.boolean().optional(),
    modifiedAt: z.number().optional(),
    acknowledgedAt: z.number().optional(),
  })
  .strict();
export const HR_ACTION_LABELS: Record<string, string> = {
  "employee.create": "إضافة ملف موظف",
  "employee.update": "تعديل ملف موظف",
  "employee.bulk": "إجراء جماعي للموظفين",
  "attendance.record": "حدث دوام",
  "attendance.correction_request": "طلب تصحيح حضور",
  "attendance.correction_decide": "قرار تصحيح حضور",
  "leave.request": "طلب إجازة",
  "resource.record": "سجل وظيفي",
  "payroll.pay": "تأكيد صرف راتب",
  "payroll.decide": "تأكيد مسير الرواتب",
  "advance.pay": "تأكيد صرف سلفة",
  "advance.decide": "قرار سلفة",
  "commission.pay": "صرف عمولة",
  "commission.approve": "اعتماد عمولة",
  "commission.change": "تسوية عمولة",
  "commission.policy": "سياسة عمولة",
  "commission.assign": "ربط فاتورة بيع",
  "document.create": "مستند موظف",
  "calendar.save": "تقويم العمل",
};
