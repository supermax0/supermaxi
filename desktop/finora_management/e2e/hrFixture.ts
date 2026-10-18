/** Isolated HR data for the real Electron renderer; never imported by production. */
export const HR_PERMISSIONS = [
  "hr.view",
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
];
export function createHRFixture() {
  const today = () => new Date(Date.now() + 3 * 3600000).toISOString().slice(0, 10);
  const shift = {
    id: 1,
    name: "الوردية الصباحية",
    branch_id: 1,
    starts: "08:00",
    ends: "16:00",
    weekdays: [0, 1, 2, 3, 4, 5, 6],
    break_minutes: 30,
    grace_minutes: 10,
    overtime_enabled: true,
    version: 1,
  };
  const attendance = (id: number) => ({
    id: null as number | null,
    date: today(),
    state: "scheduled",
    check_in: "",
    check_out: "",
    check_in_at: null as string | null,
    check_out_at: null as string | null,
    worked_minutes: 0,
    late_minutes: 0,
    overtime_minutes: 0,
    early_minutes: 0,
    version: 0,
    shift,
    person_id: id,
  });
  const people = [
    "أحمد محمد علي",
    "علي حسين خضير",
    "مصطفى كريم",
    "زهراء أحمد",
    "محمد جبار",
    "سارة خالد",
    "حسين عادل",
    "نور مهدي",
  ].map((name, index) => ({
    id: index + 1,
    name,
    code: `EMP-${String(index + 1).padStart(3, "0")}`,
    phone: `0770123456${index}`,
    phone2: "",
    email: "",
    address: "الكرادة",
    emergency_name: "",
    emergency_phone: "",
    notes: "",
    job_title: "مندوب مبيعات",
    status: "active",
    branch_id: 1,
    branch: "الكرادة",
    department_id: 1 as number | null,
    department: "المبيعات",
    employee_id: null,
    manager_id: null,
    joined_on: "2026-01-01",
    contract_end: "",
    contract_type: "full_time",
    salary: 650000,
    salary_type: "monthly",
    version: 1,
    updated_at: new Date().toISOString(),
    attendance: attendance(index + 1),
  }));
  let revision = 1;
  const receipts = new Map<string, { signature: string; data: unknown }>();
  const calendar: Array<{
    id: number;
    branch_id: number;
    on_date: string;
    title: string;
    working: boolean;
    version: number;
  }> = [];
  const lookups = () => ({
    permissions: HR_PERMISSIONS,
    branches: [{ id: 1, name: "الكرادة" }],
    departments: [{ id: 1, name: "المبيعات", branch_id: 1, version: 1 }],
    shifts: [shift],
    leave_types: [{ id: 1, name: "سنوية", paid: true, yearly_half_days: 42 }],
    treasury_accounts: [{ id: 1, name: "الصندوق الرئيسي" }],
    accounts: [],
    assets: [],
    calendar,
  });
  const overview = () => ({
    employees: people.length,
    attendance: { present: people.filter((p) => p.attendance.check_in).length },
    salaries: 12450000,
    salary_paid: 2000000,
    advances: 2800000,
    commissions: 5320000,
  });
  const details = (p: (typeof people)[number]) => ({
    person: p,
    attendance: p.attendance,
    history: [],
    contracts: [
      {
        id: p.id,
        effective_from: "2026-01-01",
        salary: p.salary,
        salary_type: p.salary_type,
        contract_type: p.contract_type,
      },
    ],
    documents: [],
    assets: [],
    leave_balances: [{ id: 1, name: "سنوية", used: 0, remaining: 21 }],
    adjustments: [],
    commission_policies: [],
    private_info: {},
  });
  const corrections: Array<{
    id: number;
    person_id: number;
    person_name: string;
    code: string;
    status: string;
    version: number;
    date: string;
    decision: string;
    detail: { check_in: string; check_out: string; reason: string };
  }> = [];
  const success = (data: unknown) => ({ status: 200, data });
  const page = (rows: unknown[], url: URL) => {
    const index = Number(url.searchParams.get("page") ?? 1),
      size = Number(url.searchParams.get("page_size") ?? 25);
    return {
      rows: rows.slice((index - 1) * size, index * size),
      page: index,
      page_size: size,
      total: rows.length,
      total_pages: Math.max(1, Math.ceil(rows.length / size)),
    };
  };
  return {
    handle(
      path: string,
      method: string,
      url: URL,
      body: Record<string, unknown>,
    ): { status: number; data: unknown } | null {
      if (path === "/hr/api/offline/revision")
        return success({ revision: String(revision), scope_revision: "scope" });
      if (path === "/hr/api/notifications") {
        const items = corrections
          .filter((r) => r.status === "pending")
          .map((r) => ({
            key: `correction:${r.id}`,
            type: "correction",
            title: "طلب تصحيح حضور ينتظر المراجعة",
            body: r.person_name,
            date: r.date,
            tone: "warning",
            tab: "corrections",
            person_id: r.person_id,
            month: null,
          }));
        return success({ items, total: items.length });
      }
      if (path === "/hr/api/statement") {
        const person = people.find((p) => p.id === Number(url.searchParams.get("person_id")));
        if (!person) return { status: 404, data: { success: false, error: "الموظف غير موجود" } };
        const rows = [
          {
            key: "journal:1",
            date: `${today()}T06:00:00Z`,
            label: "راتب مستحق",
            due: 650000,
            paid: 0,
            adjustment: 0,
            balance: 650000,
            document: {
              kind: "journal",
              id: 1,
              number: "JE-HR-1",
              reference_type: "hr_payroll_accrual",
              reference_id: 1,
              description: "استحقاق راتب تجريبي",
              debit: "مصروف رواتب",
              credit: "مستحقات الموظفين",
              amount: 650000,
            },
          },
        ];
        return success({
          ...page(rows, url),
          person_id: person.id,
          name: person.name,
          code: person.code,
          opening: 0,
          balance: 650000,
          due: 650000,
          paid: 0,
          adjustment: 0,
          advance_remaining: 0,
          advances: [],
        });
      }
      if (path === "/hr/api/corrections") return success(page(corrections, url));
      if (path === "/hr/api/calendar") {
        const month = url.searchParams.get("month") ?? today().slice(0, 7);
        const person = people.find((p) => p.id === Number(url.searchParams.get("person_id")));
        const count = new Date(Number(month.slice(0, 4)), Number(month.slice(5)), 0).getDate();
        return success({
          month,
          person_id: person?.id,
          rows: Array.from({ length: count }, (_, i) => {
            const date = `${month}-${String(i + 1).padStart(2, "0")}`;
            return { ...(person?.attendance ?? attendance(0)), date, holiday: "", leave_days: 0, shift };
          }),
        });
      }
      if (path === "/hr/api/lookups") return success(lookups());
      if (path === "/hr/api/overview") return success(overview());
      if (path === "/hr/api/page" || path === "/hr/api/offline") {
        const query = url.searchParams.get("search") ?? "";
        const filtered = people.filter(
          (p) =>
            (!query || [p.name, p.phone, p.code].some((v) => v.includes(query))) &&
            (!url.searchParams.get("status") || p.status === url.searchParams.get("status")),
        );
        const directory = page(filtered, url);
        return success(
          path.endsWith("/offline")
            ? {
                directory,
                details: (directory.rows as typeof people).map(details),
                lookups: lookups(),
                overview: overview(),
                revision: String(revision),
                scope_revision: "scope",
              }
            : directory,
        );
      }
      if (path === "/hr/api/recruitment") return success({ ...page([], url), forms: [], links: [] });
      if (path.startsWith("/hr/api/people/")) {
        const person = people.find((p) => p.id === Number(path.split("/").at(-1)));
        return person
          ? success(details(person))
          : { status: 404, data: { success: false, error: "الموظف غير موجود" } };
      }
      if (path === "/hr/api/workspace") {
        const selected = people.filter(
          (p) => !url.searchParams.get("person_id") || p.id === Number(url.searchParams.get("person_id")),
        );
        const tab = url.searchParams.get("tab");
        const rows =
          tab === "attendance"
            ? selected.map((p) => ({
                ...p.attendance,
                date: url.searchParams.get("date") ?? today(),
                person_id: p.id,
                person_name: p.name,
                code: p.code,
              }))
            : tab === "payroll"
              ? selected.slice(0, 1).map((p) => ({
                  id: 1,
                  person_id: p.id,
                  person_name: p.name,
                  code: p.code,
                  run_id: 1,
                  run_version: 1,
                  status: "approved",
                  gross: 650000,
                  deductions: 0,
                  net: 650000,
                  paid: 200000,
                  remaining: 450000,
                  calculation: { days: [] },
                }))
              : [];
        return success(page(rows, url));
      }
      if (path === "/hr/api/commands" && method === "POST") {
        const id = String(body.id),
          action = String(body.action),
          payload = body.payload as Record<string, unknown>,
          signature = JSON.stringify([action, payload]);
        const receipt = receipts.get(id);
        if (receipt)
          return receipt.signature === signature
            ? success(receipt.data)
            : { status: 409, data: { success: false, error: "معرف مستخدم" } };
        let result: Record<string, unknown>;
        if (action === "employee.create") {
          const next = people.length + 1;
          const person = {
            ...people[0],
            ...payload,
            id: next,
            name: String(payload.name),
            code: `EMP-${String(next).padStart(3, "0")}`,
            version: 1,
            attendance: attendance(next),
          } as (typeof people)[number];
          people.push(person);
          result = { id: next, version: 1 };
        } else if (action === "employee.update" || action === "attendance.record") {
          const person = people.find((p) => p.id === payload.person_id);
          if (!person) return { status: 404, data: { success: false, error: "الموظف غير موجود" } };
          if (action === "employee.update") {
            if (person.version !== payload.version)
              return { status: 409, data: { success: false, error: "تغيرت البيانات" } };
            Object.assign(person, payload, { version: person.version + 1 });
            result = { id: person.id, version: person.version };
          } else {
            const key = payload.event === "check_in" ? "check_in" : "check_out";
            const utc = String(payload.occurred_at);
            Object.assign(person.attendance, {
              [key]: new Date(Date.parse(utc) + 3 * 3600000).toISOString().slice(11, 16),
              [key + "_at"]: utc,
              id: 100 + person.id,
              state: "present",
              version: person.attendance.version + 1,
            });
            result = {
              id: person.attendance.id,
              version: person.attendance.version,
              attendance: person.attendance,
            };
          }
        } else if (action === "attendance.correction_request") {
          const person = people.find((p) => p.id === payload.person_id);
          if (!person || person.attendance.version !== payload.attendance_version)
            return { status: 409, data: { success: false, error: "تغير الدوام" } };
          const row = {
            id: corrections.length + 1,
            person_id: person.id,
            person_name: person.name,
            code: person.code,
            status: "pending",
            version: 1,
            date: new Date().toISOString(),
            decision: "",
            detail: {
              check_in: String(payload.check_in),
              check_out: String(payload.check_out ?? ""),
              reason: String(payload.reason),
            },
          };
          corrections.push(row);
          result = { id: row.id };
        } else if (action === "attendance.correction_decide") {
          const row = corrections.find((r) => r.id === payload.correction_id);
          if (!row || row.version !== payload.version || row.status !== "pending")
            return { status: 409, data: { success: false, error: "تغير الطلب" } };
          row.status = String(payload.status);
          row.decision = String(payload.reason);
          row.version++;
          if (row.status === "approved") {
            const person = people.find((p) => p.id === row.person_id);
            if (person) person.attendance.version++;
          }
          result = { id: row.id, version: row.version };
        } else if (action === "calendar.save") {
          const existing = calendar.find(
            (c) => c.branch_id === payload.branch_id && c.on_date === payload.on_date,
          );
          const row = {
            id: existing?.id ?? calendar.length + 1,
            branch_id: Number(payload.branch_id),
            on_date: String(payload.on_date),
            title: String(payload.title),
            working: payload.working === true,
            version: (existing?.version ?? 0) + 1,
          };
          if (existing) Object.assign(existing, row);
          else calendar.push(row);
          result = { id: row.id, version: row.version };
        } else
          return { status: 400, data: { success: false, error: "الإجراء غير مفعّل في بيانات الاختبار" } };
        revision++;
        const data = { success: true, ...result };
        receipts.set(id, { signature, data: structuredClone(data) });
        return success(data);
      }
      return null;
    },
  };
}
