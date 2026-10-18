/* UI-only fixture. Real ledger and treasury integration is tested by pytest. */
export const FINANCE_PERMISSIONS = [
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
];
export function createFinanceFixture(initialRecords: Record<string, unknown>[] = [], customers = false) {
  const records = structuredClone(initialRecords);
  let nextId = Math.max(0, ...records.map((r) => Number(r.id))) + 1;
  let debtsReviewed = false;
  const categories = [
    {
      id: "expense",
      label: "مصروف تشغيل جديد",
      kind: "payment",
      party_type: "other",
      activity: "operating",
      help: "مصروف جديد يخفض النقد والربح مرة واحدة.",
    },
    {
      id: "customer_payment",
      label: "تسديد زبون",
      kind: "receipt",
      party_type: "customer",
      activity: "operating",
      help: "يزيد النقد ويخفض دين الزبون دون إيراد جديد.",
    },
    {
      id: "account_transfer",
      label: "تحويل داخلي",
      kind: "transfer",
      party_type: "other",
      activity: "internal",
      help: "ينقل المال بين حسابين دون تغيير إجمالي النقد أو الربح.",
    },
  ];
  const policy = {
    allow_negative: false,
    separate_approval: false,
    approval_limit: 5000000,
    sensitive_threshold: 1000000,
    low_balance: 100000,
    due_warning_days: 7,
  };
  const accounts = [
    { id: 1, name: "صندوق الفرع", type: "cash", branch_id: 1, balance: 20000000 },
    { id: 2, name: "حساب المصرف", type: "bank", branch_id: 1, balance: 1000000 },
  ];
  const ok = (data: unknown) => ({ status: 200, data: { success: true, data } });
  return {
    handle(path: string, method: string, url: URL, body: Record<string, unknown>) {
      if (path === "/api/finance/meta")
        return ok({
          capabilities: Object.fromEntries(FINANCE_PERMISSIONS.map((p) => [p, true])),
          policy,
          accounts,
          categories,
          branches: [{ id: 1, name: "الفرع الرئيسي" }],
          expenses: [],
          asset_categories: [],
        });
      if (path === "/api/finance/vouchers" && method === "GET") {
        const q = url.searchParams.get("q") || "";
        const status = url.searchParams.get("status");
        const items = records.filter(
          (r) =>
            (!q || String(r.party_name).includes(q) || String(r.number).includes(q)) &&
            (!status || r.status === status),
        );
        const posted = records.filter((r) => r.status === "posted");
        const received = posted.filter((r) => r.kind === "receipt").reduce((n, r) => n + Number(r.amount), 0);
        const paid = posted.filter((r) => r.kind === "payment").reduce((n, r) => n + Number(r.amount), 0);
        return ok({
          items,
          total: items.length,
          page: 1,
          page_size: 25,
          stats: {
            received,
            paid,
            cash_flow: received - paid,
            pending: 0,
            drafts: records.filter((r) => r.status === "draft").length,
          },
        });
      }
      if (path === "/api/finance/notifications") return ok({ items: [] });
      if (path === "/api/finance/settings") return ok({ policy, mappings: [], chart: [] });
      if (path === "/api/finance/migration/preview")
        return ok({
          hash: "reviewed-debts",
          complete: customers,
          debt_upgrade_required: customers && !debtsReviewed,
          issues: [],
          rows: [
            {
              key: "receivable",
              name: "اعتماد الديون المستقلة السابقة",
              current: 200000,
              target: 250000,
              difference: 50000,
            },
          ],
        });
      if (path === "/api/finance/parties") return ok({ items: [{ id: 3, name: "زبون تجربة" }] });
      if (path === "/api/finance/parties/customer/3")
        return ok({
          id: 3,
          name: "زبون تجربة",
          branch_id: 1,
          debt: 250000,
          credit: 0,
          invoices: [
            { id: 10, number: "10", total: 400000, paid: 150000, remaining: 250000, type: "invoice" },
          ],
          movements: records.filter((r) => r.party_type === "customer" && r.party_id === 3),
        });
      if (customers && path === "/api/finance/parties/customer/1")
        return ok({
          id: 1,
          name: "أحمد العميل",
          branch_id: 1,
          debt: 250000,
          credit: 0,
          invoices: [
            { id: 10, number: "10", total: 300000, paid: 100000, remaining: 200000, type: "invoice" },
            { id: 2, number: "دين مستقل #2", total: 50000, paid: 0, remaining: 50000, type: "customer_debt" },
          ],
          movements: records.filter((r) => r.party_type === "customer" && r.party_id === 1),
        });
      if (path === "/api/finance/loans")
        return ok({
          items: [],
          total: 0,
          page: 1,
          page_size: 25,
          stats: { principal: 0, remaining: 0, monthly_due: 0, overdue: 0 },
        });
      if (path === "/api/finance/journal") return ok({ total: 0, rows: [] });
      if (path === "/api/finance/reports/customer-aging")
        return ok({
          rows: [
            {
              id: "invoice:10",
              name: "زبون تقرير",
              reference: "فاتورة #10",
              date: "2026-09-01",
              age: 40,
              amount: 250000,
              status: "31–60",
              source_type: "customer",
              source_id: 3,
            },
          ],
          total: 250000,
          title: "أعمار ديون العملاء",
          as_of: "2026-10-11",
          note: "الأرصدة الحالية؛ العمر من تاريخ المستند.",
        });
      if (path === "/api/finance/reports/trial-balance")
        return ok({
          rows: [],
          debit: 0,
          credit: 0,
          profit: 0,
          assets: 0,
          liabilities: 0,
          equity: 0,
          revenue: 0,
          expenses: 0,
          balanced: true,
          opening_migration_complete: false,
        });
      if (path === "/api/finance/commands") {
        const operation = String(body.operation);
        if (operation === "migration.apply") {
          debtsReviewed = true;
          return ok({ complete: true, rows: [] });
        }
        if (operation === "voucher.create") {
          const category = categories.find((c) => c.id === body.category);
          if (!category) return { status: 400, data: { success: false, error: "تصنيف غير صالح" } };
          const record = {
            id: nextId,
            number: `PY-${String(nextId++).padStart(6, "0")}`,
            kind: category.kind,
            category: category.id,
            category_label: category.label,
            party_type: category.party_type,
            party_id: Number(body.party_id) || null,
            party_name: String(body.party_name),
            amount: Number(body.amount),
            account_name: "صندوق الفرع",
            treasury_account_id: 1,
            target_account_id: null,
            branch_id: 1,
            transaction_date: String(body.transaction_date),
            status: body.intent === "post" ? "posted" : "draft",
            version: 1,
            notes: String(body.notes || ""),
            source_type: null,
            source_id: null,
            reversal_id: null,
            allocations: [],
            audit: [],
            attachments: [],
            journal: [],
            payload: { ...body },
          };
          records.push(record);
          return ok(record);
        }
        const record = records.find((r) => r.id === Number(body.id));
        if (!record) return { status: 404, data: { success: false, error: "السند غير موجود" } };
        if (operation === "voucher.edit") {
          record.amount = Number(body.amount);
          record.party_name = String(body.party_name);
          record.version = Number(record.version) + 1;
        }
        if (operation === "voucher.approve") {
          record.status = "posted";
          record.version = Number(record.version) + 1;
          const cash = accounts[0];
          if (!cash) throw Error("Missing test treasury");
          cash.balance -= Number(record.amount);
        }
        return ok(record);
      }
      const match = path.match(/^\/api\/finance\/vouchers\/(\d+)$/);
      if (match) return ok(records.find((r) => r.id === Number(match[1])));
      return null;
    },
  };
}
