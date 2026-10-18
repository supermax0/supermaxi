import { z } from "zod";
import { finoraRequestSchema, type ReportQuery } from "@shared/ipc";
import { desktopBridge } from "@/services/bridge";
import { finoraCall } from "./transport";

const option = z.object({
  id: z.number().int(),
  name: z.string(),
  branch_id: z.number().nullable().optional(),
});
const attendance = z
  .object({
    id: z.number().nullable(),
    date: z.string(),
    state: z.string(),
    check_in: z.string(),
    check_out: z.string(),
    worked_minutes: z.number(),
    late_minutes: z.number(),
    overtime_minutes: z.number(),
    early_minutes: z.number(),
    version: z.number(),
    shift: z.object({ id: z.number(), name: z.string(), version: z.number() }).passthrough().nullable(),
  })
  .passthrough();
const person = z.object({
  id: z.number().int(),
  code: z.string(),
  name: z.string(),
  photo_data: z
    .string()
    .regex(/^data:image\/jpeg;base64,[A-Za-z0-9+/=]+$/)
    .max(150000)
    .nullable()
    .optional(),
  phone: z.string(),
  phone2: z.string(),
  email: z.string(),
  address: z.string(),
  job_title: z.string(),
  status: z.string(),
  contract_type: z.string(),
  notes: z.string(),
  branch_id: z.number(),
  branch: z.string(),
  department_id: z.number().nullable(),
  department: z.string(),
  employee_id: z.number().nullable(),
  manager_id: z.number().nullable(),
  joined_on: z.string(),
  contract_end: z.string(),
  updated_at: z.string(),
  version: z.number(),
  salary: z.number().optional(),
  salary_type: z.string().optional(),
  overtime_hourly_bonus: z.number().optional(),
  late_minute_penalty: z.number().optional(),
  absence_daily_penalty: z.number().optional(),
  emergency_name: z.string().optional(),
  emergency_phone: z.string().optional(),
  attendance: attendance.nullable().optional(),
});
export type HRPerson = z.infer<typeof person>;
export type HRAttendance = z.infer<typeof attendance>;
const lookupSchema = z.object({
  calendar: z
    .array(
      z.object({
        id: z.number(),
        branch_id: z.number(),
        on_date: z.string(),
        title: z.string(),
        working: z.boolean(),
        version: z.number(),
      }),
    )
    .default([]),
  permissions: z.array(z.string()),
  branches: z.array(option),
  departments: z.array(option.extend({ version: z.number() })),
  shifts: z.array(
    option.extend({
      starts: z.string(),
      ends: z.string(),
      weekdays: z.array(z.number()),
      break_minutes: z.number(),
      grace_minutes: z.number(),
      overtime_enabled: z.boolean(),
      version: z.number(),
    }),
  ),
  leave_types: z.array(option.extend({ paid: z.boolean(), yearly_half_days: z.number().nullable() })),
  treasury_accounts: z.array(option),
  accounts: z.array(option),
  assets: z.array(option),
  access_scopes: z
    .array(
      z.object({
        employee_id: z.number(),
        mode: z.string(),
        department_id: z.number().nullable(),
        version: z.number(),
      }),
    )
    .default([]),
});
export type HRLookups = z.infer<typeof lookupSchema>;
const pagination = { total: z.number(), page: z.number(), page_size: z.number(), total_pages: z.number() };
const directory = z.object({ ...pagination, rows: z.array(person) });
const workspaceRow = z
  .object({
    id: z.number().nullable(),
    person_id: z.number(),
    person_name: z.string(),
    code: z.string(),
    state: z.string().optional(),
    status: z.string().optional(),
    date: z.string().optional(),
    version: z.number().optional(),
    check_in: z.string().optional(),
    check_out: z.string().optional(),
    check_in_at: z.string().nullable().optional(),
    check_out_at: z.string().nullable().optional(),
    worked_minutes: z.number().optional(),
    late_minutes: z.number().optional(),
    overtime_minutes: z.number().optional(),
    starts: z.string().optional(),
    ends: z.string().optional(),
    type: z.string().optional(),
    days: z.number().optional(),
    reason: z.string().optional(),
    run_id: z.number().optional(),
    run_version: z.number().optional(),
    gross: z.number().optional(),
    deductions: z.number().optional(),
    net: z.number().optional(),
    paid: z.number().optional(),
    remaining: z.number().optional(),
    amount: z.number().optional(),
    repaid: z.number().optional(),
    instalments: z.number().optional(),
    first_month: z.string().optional(),
    invoice_id: z.number().optional(),
    entity_id: z.number().optional(),
    source: z.enum(["hr", "legacy", "change"]).optional(),
    has_changes: z.boolean().optional(),
    kind: z.string().optional(),
    detail: z.record(z.unknown()).optional(),
    calculation: z.record(z.unknown()).optional(),
  })
  .passthrough();
export type HRWorkspaceRow = z.infer<typeof workspaceRow>;
const detailsSchema = z.object({
  offboarding: z
    .object({ ends_on: z.string(), reason: z.string(), settlement: z.record(z.unknown()) })
    .nullable()
    .default(null),
  private_info: z
    .object({
      birth_date: z.string().optional(),
      national_id: z.string().optional(),
      gender: z.string().optional(),
      bank_name: z.string().optional(),
      bank_account: z.string().optional(),
    })
    .default({}),
  person,
  attendance: attendance.nullable(),
  history: z.array(z.object({ id: z.number(), action: z.string(), date: z.string(), reference: z.string() })),
  contracts: z.array(
    z.object({
      id: z.number(),
      effective_from: z.string(),
      salary: z.number(),
      salary_type: z.string(),
      contract_type: z.string(),
    }),
  ),
  documents: z.array(
    z.object({
      id: z.number(),
      title: z.string(),
      kind: z.string(),
      filename: z.string(),
      mime: z.string(),
      size: z.number(),
      expires_on: z.string(),
      date: z.string(),
      sha256: z.string(),
    }),
  ),
  assets: z.array(
    z.object({
      id: z.number(),
      asset_id: z.number(),
      name: z.string(),
      code: z.string(),
      version: z.number(),
      note: z.string(),
      returned_at: z.string().nullable(),
    }),
  ),
  leave_balances: z.array(
    z.object({ id: z.number(), name: z.string(), used: z.number(), remaining: z.number().nullable() }),
  ),
  adjustments: z.array(
    z.object({ id: z.number(), month: z.string(), kind: z.string(), title: z.string(), amount: z.number() }),
  ),
  commission_policies: z
    .array(
      z.object({
        id: z.number(),
        effective_from: z.string(),
        kind: z.string(),
        rules: z.record(z.unknown()),
      }),
    )
    .default([]),
});
export type HRDetails = z.infer<typeof detailsSchema>;
export type HRTab = "employees" | "attendance" | "payroll" | "advances" | "leave" | "resources";
export interface HRFilters {
  search: string;
  status: string;
  branch_id: string;
  department_id: string;
  page: number;
  page_size: number;
  sort: string;
}
const saved = z.object({
  success: z.literal(true),
  id: z.number(),
  version: z.number().optional(),
  remaining: z.number().optional(),
  pending: z.boolean().optional(),
  url: z.string().optional(),
});
const recruitField = z.object({
  key: z.string(),
  type: z.string(),
  label: z.string(),
  description: z.string(),
  required: z.boolean(),
  options: z.array(z.string()),
  max_length: z.number(),
  max_file_kb: z.number(),
  minimum: z.number().nullable(),
  maximum: z.number().nullable(),
  order: z.number(),
});
export type HRRecruitField = z.infer<typeof recruitField>;
const recruitForm = z.object({
  id: z.number(),
  branch_id: z.number(),
  title: z.string(),
  description: z.string(),
  fields: z.array(recruitField),
  version: z.number(),
});
export type HRRecruitForm = z.infer<typeof recruitForm>;
const application = z.object({
  id: z.number(),
  link_id: z.number(),
  status: z.string(),
  note: z.string(),
  version: z.number(),
  person_id: z.number().nullable(),
  answers: z.record(z.unknown()),
  fields: z.array(recruitField),
  date: z.string(),
  files: z.array(z.object({ id: z.number(), filename: z.string(), field_key: z.string() })),
});
export type HRApplication = z.infer<typeof application>;
export const hr = {
  notifications: () =>
    finoraCall(
      { method: "GET", path: "/hr/api/notifications" },
      z.object({
        total: z.number(),
        items: z.array(
          z.object({
            key: z.string(),
            type: z.string(),
            title: z.string(),
            body: z.string(),
            date: z.string(),
            tone: z.enum(["info", "warning", "success"]),
            tab: z.string(),
            person_id: z.number().nullable(),
            month: z.string().nullable(),
          }),
        ),
      }),
    ),
  export: (
    tab: HRTab | "commissions" | "settlement" | "statement",
    format: "print" | "pdf" | "xlsx",
    query: ReportQuery,
  ) =>
    desktopBridge().reports.export({ section: `hr_${tab}`, format, title: "FINORA الموارد البشرية", query }),
  statement: (query: { person_id: number; page?: number; date_from?: string; date_to?: string }) =>
    finoraCall(
      { method: "GET", path: "/hr/api/statement", query },
      z.object({
        person_id: z.number(),
        name: z.string(),
        code: z.string(),
        opening: z.number(),
        balance: z.number(),
        due: z.number(),
        paid: z.number(),
        adjustment: z.number(),
        total: z.number(),
        page: z.number(),
        total_pages: z.number(),
        advance_remaining: z.number(),
        advances: z.array(
          z.object({
            id: z.number(),
            amount: z.number(),
            repaid: z.number(),
            remaining: z.number(),
            reason: z.string(),
            status: z.string(),
          }),
        ),
        rows: z.array(
          z.object({
            key: z.string(),
            date: z.string(),
            label: z.string(),
            due: z.number(),
            paid: z.number(),
            adjustment: z.number(),
            balance: z.number(),
            document: z.object({
              kind: z.string(),
              id: z.number(),
              number: z.string(),
              reference_type: z.string(),
              reference_id: z.number(),
              description: z.string(),
              debit: z.string(),
              credit: z.string(),
              amount: z.number(),
            }),
          }),
        ),
      }),
    ),
  list: (query: HRFilters) =>
    finoraCall({ method: "GET", path: "/hr/api/page", query: { ...query } }, directory),
  lookups: () => finoraCall({ method: "GET", path: "/hr/api/lookups" }, lookupSchema),
  overview: () =>
    finoraCall(
      { method: "GET", path: "/hr/api/overview" },
      z.object({
        employees: z.number(),
        attendance: z.record(z.number()),
        salaries: z.number().nullable(),
        salary_paid: z.number().nullable(),
        advances: z.number().nullable(),
        commissions: z.number().nullable(),
      }),
    ),
  details: (id: number) => finoraCall({ method: "GET", path: `/hr/api/people/${id}` }, detailsSchema),
  calendar: (person_id: number, month: string) =>
    finoraCall(
      { method: "GET", path: "/hr/api/calendar", query: { person_id, month } },
      z.object({
        month: z.string(),
        person_id: z.number(),
        rows: z.array(
          z.object({
            id: z.number().nullable(),
            date: z.string(),
            state: z.string(),
            check_in: z.string(),
            check_out: z.string(),
            worked_minutes: z.number(),
            holiday: z.string(),
            leave_days: z.number(),
            shift: z.object({ name: z.string() }).passthrough().nullable(),
          }),
        ),
      }),
    ),
  corrections: (page: number) =>
    finoraCall(
      { method: "GET", path: "/hr/api/corrections", query: { page } },
      z.object({
        rows: z.array(
          z.object({
            id: z.number(),
            person_id: z.number(),
            person_name: z.string(),
            code: z.string(),
            status: z.string(),
            version: z.number(),
            date: z.string(),
            decision: z.string(),
            detail: z.object({ check_in: z.string(), check_out: z.string(), reason: z.string() }),
          }),
        ),
        total: z.number(),
        page: z.number(),
        total_pages: z.number(),
      }),
    ),
  document: (id: number) =>
    finoraCall(
      { method: "GET", path: `/hr/api/documents/${id}` },
      z.object({ filename: z.string(), mime: z.string(), content: z.string() }),
    ),
  applicantFile: (id: number) =>
    finoraCall(
      { method: "GET", path: `/hr/api/applicant-files/${id}` },
      z.object({ filename: z.string(), mime: z.string(), content: z.string() }),
    ),
  recruitment: (query: Record<string, string | number>) =>
    finoraCall(
      { method: "GET", path: "/hr/api/recruitment", query },
      z.object({
        ...pagination,
        forms: z.array(recruitForm),
        rows: z.array(application),
        links: z.array(
          z.object({
            id: z.number(),
            form_id: z.number(),
            expires_at: z.string(),
            received: z.number(),
            max_submissions: z.number(),
            active: z.boolean(),
            version: z.number(),
            private: z.boolean(),
          }),
        ),
      }),
    ),
  workspace: (
    tab: Exclude<HRTab, "employees"> | "commissions",
    query: Record<string, string | number> = {},
  ) =>
    finoraCall(
      { method: "GET", path: "/hr/api/workspace", query: { tab, ...query } },
      z.object({ ...pagination, rows: z.array(workspaceRow) }),
    ),
  command: (action: string, payload: Record<string, unknown>, id: string) =>
    finoraCall(
      finoraRequestSchema.parse({
        method: "POST",
        path: "/hr/api/commands",
        body: { id, action, payload },
        timeoutMs: 30000,
      }),
      saved,
    ),
};
