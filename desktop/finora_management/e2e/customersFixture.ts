/* UI fixture only. Real customer balances and branch guards are tested in Python. */
type ScheduleRow = { id: number; number: number; date: string; total: number; paid: number };
type CustomerSchedule = {
  id: number;
  customer_id: number;
  invoice_id: number | null;
  total: number;
  paid: number;
  revision: string;
  installments: ScheduleRow[];
  history_total: number;
  protected_ids?: number[];
  history: {
    id: number;
    actor: string;
    date: string;
    reason: string;
    before: ScheduleRow[];
    after: ScheduleRow[];
  }[];
};
type ScheduleEdit = { reason: string; installments: Pick<ScheduleRow, "id" | "date" | "total">[] };

export function createCustomersFixture(
  includePlanBuilder = false,
  includeDebtBuilder = false,
  priorPayments = false,
  voucherHistory = false,
  reversedHistory = false,
) {
  const historicalPaid = reversedHistory ? 0 : 30000;
  let createdDebt: CustomerSchedule | null = null;
  let schedule: CustomerSchedule = {
    id: 1,
    customer_id: 1,
    invoice_id: 10,
    total: 300000,
    paid: 100000,
    revision: "d".repeat(64),
    history: [],
    history_total: 0,
    protected_ids: [1, 2],
    installments: [
      { id: 1, number: 1, date: "2026-10-01", total: 75000, paid: 25000 },
      { id: 2, number: 2, date: "2026-10-10", total: 75000, paid: 75000 },
      { id: 3, number: 3, date: "2026-12-01", total: 150000, paid: 0 },
    ],
  };
  const scheduleReceipts = new Map<string, CustomerSchedule>();
  let createdSchedule: CustomerSchedule | null = null;
  const items = Array.from({ length: 31 }, (_, index) => ({
    id: index + 1,
    name: index === 0 ? "أحمد العميل" : `عميل ${index + 1}`,
    phone: `077${String(index).padStart(8, "0")}`,
    phone2: "",
    city: "بغداد",
    address: "شارع الجامعة",
    notes: "عميل مسجل",
    branch_id: 1,
    debt: index === 0 ? 250000 : 0,
    overdue: index === 0 ? 50000 : 0,
    created_at: "2026-10-10T12:00:00",
    revision: "a".repeat(64),
  }));
  return {
    handle(path: string, url: URL, method = "GET", body: Record<string, unknown> = {}) {
      const ok = (data: unknown) => ({ status: 200, data: { success: true, data } });
      const page = Number(url.searchParams.get("page") ?? 1);
      const size = Number(url.searchParams.get("page_size") ?? 25);
      if (path === "/api/v1/desktop/customers/1/transactions/export")
        return ok({
          filename: "customer-1-collections.csv",
          content: "\ufeffالتاريخ,الحركة\n2026-10-11,تحصيل دين",
        });
      if (path === "/api/v1/desktop/customers/1/transactions") {
        const rows = Array.from({ length: 32 }, (_, i) => ({
          kind: i === 0 ? "voucher" : "invoice_payment",
          id: i + 1,
          date: "2026-10-11",
          description: i === 0 ? "تسوية رصيد مقدم" : "تحصيل فاتورة",
          document: i === 0 ? "ST-000001" : "فاتورة #10",
          amount: 25000,
          cash: i === 0 ? 0 : 25000,
          debt_change: -25000,
          advance_change: i === 0 ? -25000 : 0,
          invoice_id: i === 0 ? null : 10,
          voucher_id: i === 0 ? 1 : null,
          plan_id: null,
          status: "posted",
          note: "",
        }));
        return ok({
          items: rows.slice((page - 1) * size, page * size),
          page,
          page_size: size,
          total: rows.length,
          as_of: "2026-10-11",
          summary: {
            debt: 250000,
            advance: 15000,
            net_due: 235000,
            unexplained_documents: 1,
            unexplained_amount: 50000,
          },
        });
      }
      if (path === "/api/v1/desktop/customers/1/plans/1") return ok(schedule);
      if (path === "/api/v1/desktop/customers/1/plans/4" && createdSchedule) return ok(createdSchedule);
      if (path === "/api/v1/desktop/customers/1/plans/5" && createdDebt) return ok(createdDebt);
      const createPlan = path === "/api/v1/desktop/customers/1/invoices/11/schedule";
      const createDebt = includeDebtBuilder && path === "/api/v1/desktop/customers/1/debts";
      if (createDebt && method === "GET")
        return ok({
          customer_id: 1,
          total: 0,
          paid: 0,
          revision: "f".repeat(64),
          eligible: true,
          blocked_reason: "",
        });
      if (includePlanBuilder && path === "/api/v1/desktop/customers/1/invoices/10/schedule")
        return ok({
          customer_id: 1,
          invoice_id: 10,
          total: 300000,
          paid: 100000,
          revision: "d".repeat(64),
          plan_id: 1,
          eligible: false,
          blocked_reason: "الفاتورة مرتبطة بجدول أقساط؛ افتح جدولها الحالي",
        });
      if (includePlanBuilder && createPlan && method === "GET")
        return ok({
          customer_id: 1,
          invoice_id: 11,
          total: 90000,
          paid: priorPayments ? historicalPaid : 0,
          revision: "f".repeat(64),
          plan_id: createdSchedule?.id ?? null,
          eligible: !createdSchedule,
          blocked_reason: createdSchedule ? "الفاتورة مرتبطة بجدول" : "",
          historical: priorPayments
            ? {
                date: "2026-10-01",
                paid: historicalPaid,
                payment_count: 2,
                ...(voucherHistory
                  ? {
                      vouchers: [
                        {
                          id: 6,
                          number: "RC-000006",
                          date: "2026-10-03",
                          amount: 30000,
                          reversed: reversedHistory,
                        },
                      ],
                    }
                  : {}),
              }
            : null,
        });
      if (
        (includePlanBuilder || createDebt) &&
        method === "POST" &&
        (createPlan || createDebt || path === "/api/v1/desktop/customers/1/plans/1/repartition")
      ) {
        const key = String(body.idempotency_key);
        const receipt = scheduleReceipts.get(key);
        if (receipt) return ok(receipt);
        const before = createPlan || createDebt ? [] : structuredClone(schedule.installments);
        const fixed =
          createPlan && priorPayments
            ? [{ id: 19, number: 1, date: "2026-10-01", total: historicalPaid, paid: historicalPaid }]
            : before.filter((row) => row.paid > 0 || schedule.protected_ids?.includes(row.id));
        const count = Number(body.count),
          total = createDebt ? Number(body.amount) : createPlan ? 90000 : schedule.total;
        const free = total - fixed.reduce((sum, row) => sum + row.total, 0);
        const first = new Date(`${String(body.first_due_date)}T00:00:00Z`);
        const after = [
          ...fixed,
          ...Array.from({ length: count }, (_, index) => {
            const due =
              body.interval === "weekly"
                ? new Date(first.getTime() + index * 7 * 86400000)
                : new Date(
                    Date.UTC(
                      first.getUTCFullYear(),
                      first.getUTCMonth() + index,
                      Math.min(
                        first.getUTCDate(),
                        new Date(
                          Date.UTC(first.getUTCFullYear(), first.getUTCMonth() + index + 1, 0),
                        ).getUTCDate(),
                      ),
                    ),
                  );
            return {
              id: 20 + index,
              number: Math.max(0, ...fixed.map((row) => row.number)) + index + 1,
              date: due.toISOString().slice(0, 10),
              total: Math.floor(free / count) + (index === count - 1 ? free % count : 0),
              paid: 0,
            };
          }),
        ];
        const value: CustomerSchedule = {
          ...schedule,
          id: createDebt ? 5 : createPlan ? 4 : 1,
          invoice_id: createDebt ? null : createPlan ? 11 : 10,
          total,
          paid: createPlan ? (priorPayments ? historicalPaid : 0) : createDebt ? 0 : schedule.paid,
          revision: "9".repeat(64),
          installments: after,
          protected_ids: fixed.map((row) => row.id),
          history_total: 1,
          history: [
            {
              id: 1,
              actor: "مدير الاختبار",
              date: "2026-10-11T12:00:00Z",
              reason: createDebt
                ? `${String(body.source_reference)} — ${String(body.reason)}`
                : String(body.reason),
              before,
              after,
            },
          ],
        };
        if (createDebt) {
          createdDebt = value;
          const customer = items[0];
          if (customer) customer.debt += total;
        } else if (createPlan) createdSchedule = value;
        else schedule = value;
        scheduleReceipts.set(key, structuredClone(value));
        return ok(value);
      }
      if (
        (path === "/api/v1/desktop/customers/1/plans/1/schedule" ||
          (path === "/api/v1/desktop/customers/1/plans/4/schedule" && createdSchedule)) &&
        method === "POST"
      ) {
        const current = path.includes("/plans/4/") ? createdSchedule : schedule;
        if (!current) throw new Error("Missing created schedule fixture");
        const data = body as unknown as ScheduleEdit & { idempotency_key: string };
        const previous = scheduleReceipts.get(data.idempotency_key);
        if (previous) return ok(previous);
        const before = structuredClone(current.installments);
        const after = before.map((row) => ({
          ...row,
          ...data.installments.find((item) => item.id === row.id),
        }));
        const updated = {
          ...current,
          revision: "e".repeat(64),
          installments: after,
          history_total: current.history_total + 1,
          history: [
            {
              id: current.history_total + 1,
              actor: "مدير الاختبار",
              date: "2026-10-11T12:00:00Z",
              reason: data.reason,
              before,
              after,
            },
            ...current.history,
          ],
        };
        if (path.includes("/plans/4/")) createdSchedule = updated;
        else schedule = updated;
        scheduleReceipts.set(data.idempotency_key, structuredClone(updated));
        return ok(updated);
      }
      if (path === "/api/v1/desktop/customers/commands" && method === "POST") {
        const data = body.data as Record<string, string>;
        if (body.operation === "create") {
          const template = items[0];
          if (!template) throw new Error("Missing customer fixture template");
          const row = {
            ...template,
            id: items.length + 1,
            name: data.name ?? "",
            phone: data.phone ?? "",
            phone2: data.phone2 ?? "",
            city: data.city ?? "",
            address: data.address ?? "",
            notes: data.notes ?? "",
            debt: 0,
            overdue: 0,
            revision: "b".repeat(64),
          };
          items.push(row);
          return ok(row);
        }
        const row = items.find((item) => item.id === body.id);
        if (!row) return { status: 404, data: { success: false, error: "العميل غير موجود" } };
        Object.assign(row, data, { revision: "c".repeat(64) });
        return ok(row);
      }
      if (path === "/api/v1/desktop/customers") {
        const q = url.searchParams.get("q") ?? "";
        const tab = url.searchParams.get("tab") ?? "all";
        const matched = items.filter(
          (row) =>
            (!q || row.name.includes(q) || row.phone.includes(q)) &&
            (tab === "all" ||
              (tab === "debt" && row.debt > 0) ||
              (tab === "overdue" && row.overdue > 0) ||
              (tab === "settled" && row.debt === 0)),
        );
        return ok({
          items: matched.slice((page - 1) * size, page * size),
          page,
          page_size: size,
          total: matched.length,
          as_of: "2026-10-11",
          stats: { customers: 31, debt: 250000 + (createdDebt?.total ?? 0), overdue: 50000, debtors: 1 },
        });
      }
      const match = path.match(/^\/api\/v1\/desktop\/customers\/(\d+)(\/history)?$/);
      if (!match) return null;
      const row = items.find((item) => item.id === Number(match[1]));
      if (!row) return { status: 404, data: { success: false, error: "العميل غير موجود" } };
      if (!match[2]) return ok(row);
      if (url.searchParams.get("kind") === "receivables") {
        const documents =
          row.id === 1
            ? [
                {
                  kind: "invoice",
                  id: 10,
                  branch_id: 1,
                  invoice_id: 10,
                  date: "2026-10-10T12:00:00",
                  description: "فاتورة بيع",
                  total: 300000,
                  paid: 100000,
                  remaining: 200000,
                },
                {
                  kind: "credit_plan",
                  id: 2,
                  branch_id: 1,
                  invoice_id: null,
                  date: "2026-10-01T12:00:00",
                  description: "رصيد افتتاحي",
                  total: 50000,
                  paid: 0,
                  remaining: 50000,
                },
              ]
            : [];
        if (row.id === 1 && createdDebt)
          documents.push({
            kind: "credit_plan",
            id: createdDebt.id,
            branch_id: 1,
            invoice_id: null,
            date: "2026-10-11T12:00:00",
            description: "دين افتتاحي · EXT-2026-001 · كشف خارجي",
            total: createdDebt.total,
            paid: 0,
            remaining: createdDebt.total,
          });
        return ok({
          items: documents.slice((page - 1) * size, page * size),
          total: documents.length,
          page,
          page_size: size,
          as_of: "2026-10-11",
          summary:
            row.id === 1
              ? {
                  total: 350000 + (createdDebt?.total ?? 0),
                  paid: 100000,
                  remaining: 250000 + (createdDebt?.total ?? 0),
                }
              : { total: 0, paid: 0, remaining: 0 },
        });
      }
      const history =
        url.searchParams.get("kind") === "installments"
          ? schedule.installments.map((item) => ({
              ...item,
              plan_id: 1,
              invoice_id: 10,
              remaining: item.total - item.paid,
              status: item.paid === item.total ? "paid" : item.date < "2026-10-11" ? "overdue" : "pending",
            }))
          : [
              {
                id: 10,
                number: "10",
                date: "2026-10-10T12:00:00",
                total: 300000,
                paid: 100000,
                status: "تم التوصيل",
                payment_status: "جزئي",
              },
              ...(includePlanBuilder
                ? [
                    {
                      id: 11,
                      number: "11",
                      date: priorPayments ? "2026-10-01T12:00:00" : "2026-10-11T12:00:00",
                      total: 90000,
                      paid: priorPayments ? historicalPaid : 0,
                      status: "مكتمل",
                      payment_status: priorPayments && historicalPaid ? "جزئي" : "غير مسدد",
                    },
                  ]
                : []),
            ];
      const customerHistory = row.id === 1 ? history : [];
      return ok({
        items: customerHistory.slice((page - 1) * size, page * size),
        total: customerHistory.length,
        page,
        page_size: size,
      });
    },
  };
}
