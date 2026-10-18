/** Shapes copied from FINORA's real endpoints (routes/orders.py, inventory.py, purchases.py) for renderer tests. */
import type { FinoraRequest, FinoraResponse } from "@shared/ipc";
import { SESSION_PAYLOAD } from "./mockBridge";

export function orderRow(id: number, overrides: Record<string, unknown> = {}) {
  return {
    id,
    checkbox: "",
    order_id: id,
    date: "2026-10-07 10:25",
    customer_name: "أحمد سالم",
    phone: "07701234567",
    phone2: "—",
    city: "بغداد",
    address: "شارع الجامعة قرب المكتبة",
    total: 450000,
    paid_amount: 0,
    remaining: 450000,
    status: "تم الطلب",
    payment_status: "غير مسدد",
    shipping_company_id: null,
    shipping_company: "—",
    delivery_agent_id: null,
    delivery_agent: "—",
    employee: "سارة",
    note: "",
    quantity: 2,
    is_stock_locked: false,
    can_pay: true,
    can_cancel: true,
    ...overrides,
  };
}

export function productRow(id: number, overrides: Record<string, unknown> = {}) {
  return {
    id,
    name: "شاشة LG 50 إنش 4K",
    sku: "TV-LG-50-2026",
    barcode: "6290000000011",
    category: "شاشات",
    image_url: "/static/uploads/products/lg50.png",
    buy_price: 280000,
    sale_price: 325000,
    quantity: 28,
    low_stock_threshold: 5,
    stock_state: "available",
    active: true,
    ...overrides,
  };
}

export function purchaseRow(id: number, overrides: Record<string, unknown> = {}) {
  return {
    id,
    invoice_no: `P-2026-00${id}`,
    date: "2026-10-07",
    supplier_id: 3,
    supplier: "شركة الرافدين للإلكترونيات",
    status: "confirmed",
    tab: "unpaid",
    branch_code: "",
    reference_no: "",
    supplier_invoice_no: "RF-991",
    payment_term: "",
    address: "",
    notes: "شاشات متنوعة",
    shipping_details: "",
    extra_cost_note: "",
    item_count: 2,
    first_product: "شاشة LG 50",
    sub_total: 12450000,
    discount_value: 0,
    shipping_extra: 0,
    grand_total: 12450000,
    paid_total: 2450000,
    remaining_total: 10000000,
    later_paid_total: 0,
    purchase_mode: "credit",
    items: [
      {
        product_id: 1,
        product: "شاشة LG 50",
        color: "",
        quantity: 10,
        unit_cost_before_discount: 0,
        discount_value: 0,
        unit_cost: 1245000,
        line_total: 12450000,
      },
    ],
    payments: [
      {
        amount: 2450000,
        paid_at: "2026-10-07 12:00",
        payment_method: "cash",
        account_name: "الصندوق",
        note: "",
      },
    ],
    attachments: [],
    ...overrides,
  };
}

export const ADMIN_SESSION = {
  ...SESSION_PAYLOAD,
  permissions: [
    "can_see_orders",
    "can_see_orders_placed",
    "can_see_orders_packed",
    "can_see_orders_shipped",
    "can_see_orders_delivered",
    "can_see_orders_returned",
    "manage_orders",
    "return_orders",
    "delete_orders",
    "print_pos_invoice",
    "can_manage_inventory",
    "view_pos",
    "view_reports",
    "view_financial",
    "view_expenses",
    "view_accounts",
    "pay_orders",
    "can_manage_suppliers",
    "edit_price",
    "edit_current_stock",
  ],
};

const ok = (data: unknown): FinoraResponse => ({ ok: true, status: 200, data });
const REPORT_KEYS = [
  "sales",
  "profit",
  "expenses",
  "cash",
  "customers",
  "purchases",
  "inventory",
  "invoices",
  "employees",
  "cashflow",
  "equity",
];

/** A small in-memory FINORA that answers like the real endpoints. */
export function createFinoraFixture() {
  const orders = [
    orderRow(10045),
    orderRow(10044, { customer_name: "فاطمة محمد", city: "البصرة", status: "معباة", total: 180000 }),
  ];
  const purchases = [
    purchaseRow(48),
    purchaseRow(47, { tab: "draft", status: "draft", supplier: "مستودع النور" }),
  ];
  const calls: FinoraRequest[] = [];

  const handler = (request: FinoraRequest): FinoraResponse => {
    calls.push(request);
    const { path } = request;
    if (path.startsWith("/api/v1/desktop/auth/")) return ok({ ok: true, session: ADMIN_SESSION });
    if (path === "/orders/data") {
      const search = String(request.query?.search ?? "");
      const rows = orders.filter(
        (o) => !search || o.customer_name.includes(search) || String(o.id).includes(search),
      );
      return ok({
        success: true,
        rows,
        page: 1,
        page_size: 25,
        total: rows.length,
        total_pages: 1,
        total_amount: 630000,
        total_quantity: 4,
      });
    }
    if (path === "/orders/api/counts")
      return ok({
        success: true,
        counts: { all: 2, ordered: 1, packed: 1, shipping: 0, delivered: 0, returned: 0 },
      });
    if (path === "/orders/api/lookups") {
      return ok({
        success: true,
        cities: ["البصرة", "بغداد"],
        shipping_companies: [{ id: 1, name: "النقل السريع" }],
        delivery_agents: [{ id: 2, name: "مندوب علي" }],
        branches: [{ id: 1, name: "الفرع الرئيسي" }],
      });
    }
    if (path === "/orders/bulk-status") {
      const body = request.body as { order_ids: number[]; status: string };
      for (const order of orders) if (body.order_ids.includes(order.id)) order.status = body.status;
      return ok({
        success: true,
        updated: body.order_ids.length,
        updated_ids: body.order_ids,
        skipped_ids: [],
      });
    }
    if (path === "/inventory/api/products") {
      const search = String(request.query?.search ?? "");
      const all = [
        productRow(1),
        productRow(2, {
          name: "مكيف جنرال",
          sku: "AC-GEN-1",
          barcode: "6290000000035",
          category: "مكيفات",
          quantity: 0,
          stock_state: "out",
        }),
      ];
      const rows = all.filter(
        (p) =>
          !search ||
          p.name.includes(search) ||
          p.barcode === search ||
          p.sku.toLowerCase().includes(search.toLowerCase()),
      );
      return ok({
        success: true,
        rows,
        page: 1,
        page_size: 25,
        total: rows.length,
        total_pages: 1,
        stats: { total: 542, available: 418, low: 86, out: 38 },
        categories: ["شاشات", "مكيفات"],
        branch_scope_label: "كل الفروع",
      });
    }
    if (path.startsWith("/inventory/api/movements/")) return ok({ summary: {}, movements: [] });
    if (path === "/purchases/api/page") {
      const tab = String(request.query?.tab ?? "all");
      const rows = purchases.filter((p) => tab === "all" || p.tab === tab);
      return ok({
        success: true,
        rows,
        page: 1,
        page_size: 25,
        total: rows.length,
        total_pages: 1,
        counts: { all: purchases.length, draft: 1, confirmed: 0, unpaid: 1, cancelled: 0 },
        summary: { total_amount: 158750000, count: 42, draft: 1, unpaid: 5, remaining_amount: 10000000 },
        suppliers: [{ id: 3, name: "شركة الرافدين للإلكترونيات" }],
      });
    }
    const cancel = /^\/purchases\/api\/(\d+)\/cancel$/.exec(path);
    if (cancel) {
      const target = purchases.find((p) => p.id === Number(cancel[1]));
      if (target) target.tab = "cancelled";
      return ok({ success: true, message: `تم إلغاء الفاتورة ${target?.invoice_no ?? ""}` });
    }
    if (path === "/pos/api/bootstrap") {
      return ok({
        success: true,
        provinces: ["بغداد", "البصرة"],
        branch_id: 1,
        can_edit_price: true,
        can_print: true,
        can_pay: true,
      });
    }
    if (path === "/pos/api/products") {
      const search = String(request.query?.search ?? "");
      const all = [
        {
          id: 1,
          name: "شاشة LG 50 بوصة",
          sku: "TV-LG-50",
          barcode: "6290000000011",
          price: 282000,
          quantity: 5,
          image_url: "",
          category: "شاشات",
          has_colors: false,
          colors: [],
        },
        {
          id: 2,
          name: "Samsung A55",
          sku: "SM-A55",
          barcode: "6290000000028",
          price: 320000,
          quantity: 3,
          image_url: "",
          category: "هواتف",
          has_colors: true,
          colors: [
            { name: "أزرق", qty: 2 },
            { name: "أسود", qty: 1 },
          ],
        },
      ];
      const rows = all.filter((p) => !search || p.name.includes(search) || p.barcode === search);
      return ok({
        success: true,
        rows,
        page: 1,
        page_size: 24,
        total: rows.length,
        total_pages: 1,
        categories: ["شاشات", "هواتف"],
      });
    }
    if (path === "/pos/search-customer") {
      return ok([
        {
          id: 9,
          name: "علي حسين",
          phone: "07705556633",
          city: "كربلاء",
          address: "شارع الكورنيش",
          blacklisted: false,
          blacklist_message: "",
        },
      ]);
    }
    if (path === "/pos/add-customer") {
      const body = request.body as { name: string; phone: string };
      return ok({ status: "success", id: 77, name: body.name, phone: body.phone });
    }
    if (path === "/pos/create-order") {
      const body = request.body as { items: Array<{ qty: number; price: number }>; discount_amount: number };
      const total = body.items.reduce((sum, item) => sum + item.qty * item.price, 0) - body.discount_amount;
      return ok({
        success: true,
        invoice_id: 10046,
        order_id: 10046,
        total,
        updated: false,
        stock_locked: false,
      });
    }
    if (path === "/orders/payment-accounts") {
      return ok({
        success: true,
        accounts: [
          { id: 4, name: "صندوق الفرع", type: "cash", is_default: true, branch_id: 1, label: "" },
          { id: 5, name: "مصرف الرافدين", type: "bank", is_default: false, branch_id: 1, label: "" },
        ],
      });
    }
    if (path === "/orders/payment") {
      const body = request.body as { id: number; payment: string; paid_amount: number | null };
      const order = orders.find((o) => o.id === body.id);
      const total = order?.total ?? 0;
      const paid = body.payment === "مسدد" ? total : (body.paid_amount ?? 0);
      return ok({
        success: true,
        order: {
          id: body.id,
          total,
          paid_amount: paid,
          remaining: total - paid,
          status: body.payment === "مسدد" ? "تم التوصيل" : (order?.status ?? ""),
          payment_status: paid >= total ? "مسدد" : "جزئي",
          payment_allocations: [],
        },
      });
    }
    const orderDetailsMatch = /^\/orders\/details\/(\d+)$/.exec(path);
    if (orderDetailsMatch) {
      const order = orders.find((o) => o.id === Number(orderDetailsMatch[1]));
      if (!order) return { ok: false, failure: "http", status: 404, data: { error: "الطلب غير موجود" } };
      return ok({
        success: true,
        order: {
          id: order.id,
          customer: order.customer_name,
          phone: order.phone,
          city: order.city,
          address: order.address,
          employee: order.employee,
          total: order.total,
          discount_amount: 0,
          paid_amount: order.paid_amount,
          status: order.status,
          payment: order.payment_status,
          created_at: "2026-10-07 10:25:00",
          shipping_company: null,
          shipping_company_id: null,
          shipping_barcode: null,
          shipping_barcodes: [],
          note: "",
          returned_count: 0,
          branch_id: 1,
          branch_name: "الفرع الرئيسي",
          stock_is_deducted: false,
          is_stock_locked: false,
        },
        items: [
          { id: 1, product_id: 1, name: "شاشة LG 50 إنش 4K", qty: 1, price: order.total, total: order.total },
        ],
      });
    }
    if (path === "/api/branch/list") {
      return ok({
        ok: true,
        branches: [
          { id: 1, name: "الفرع الرئيسي", is_active: true },
          { id: 2, name: "فرع البصرة", is_active: true },
        ],
        scheduled_branch_id: null,
      });
    }
    if (path === "/api/delivery-fee/quote") return ok({ ok: true, fee: 5000, breakdown: [] });
    if (/^\/orders\/history\/\d+$/.test(path)) {
      return ok({
        success: true,
        events: [
          {
            id: "created",
            created_at: "2026-10-07T10:25:00",
            movement: "إنشاء الطلب",
            details: "تم إنشاء الطلب",
            employee: "سارة",
            type: "create",
          },
        ],
        stats: {},
      });
    }
    if (/^\/orders\/cancel\/\d+$/.test(path)) return ok({ success: true });
    if (path === "/reports/api/v2/meta") {
      return ok({
        success: true,
        company: "شركة النور",
        sections: Object.fromEntries(REPORT_KEYS.map((key) => [key, true])),
        can_export: true,
        can_pick_branch: true,
        branches: [
          { id: 1, name: "الفرع الرئيسي" },
          { id: 2, name: "فرع الكرادة" },
        ],
        employees: [{ id: 7, name: "سارة" }],
        periods: ["today", "yesterday", "this_week", "this_month", "last_month", "this_year", "custom"],
      });
    }
    const appliedFilters = () => ({
      period: String(request.query?.period ?? "this_month"),
      date_from: "2026-10-01",
      date_to: "2026-10-31",
      branch_id: request.query?.branch_id ? Number(request.query.branch_id) : null,
      employee_id: null,
    });
    if (path === "/reports/api/v2/dashboard") {
      return ok({
        success: true,
        filters: appliedFilters(),
        comparison_range: { previous: ["2026-09-01", "2026-09-30"], last_year: ["2025-10-01", "2025-10-31"] },
        allowed: Object.fromEntries(REPORT_KEYS.map((key) => [key, true])),
        employee_scoped: false,
        kpis: [
          {
            key: "sales",
            label: "المبيعات",
            value: 2480000,
            previous: 2202500,
            change_pct: 12.6,
            tone: "good",
            section: "sales",
          },
          {
            key: "net_profit",
            label: "صافي الربح",
            value: 1017000,
            previous: 882800,
            change_pct: 15.2,
            tone: "good",
            section: "profit",
          },
          {
            key: "expenses",
            label: "المصاريف",
            value: 310400,
            previous: 296200,
            change_pct: 4.8,
            tone: "bad",
            section: "expenses",
          },
          {
            key: "cash",
            label: "النقد المتوفر",
            value: 620750,
            previous: 585000,
            change_pct: 6.1,
            tone: "good",
            section: "cash",
          },
          {
            key: "receivables",
            label: "ديون العملاء",
            value: 285300,
            previous: null,
            change_pct: null,
            tone: "neutral",
            section: "customers",
          },
          {
            key: "inventory",
            label: "قيمة المخزون",
            value: 1420500,
            previous: null,
            change_pct: null,
            tone: "neutral",
            section: "inventory",
          },
        ],
        comparison: [
          { key: "sales", label: "المبيعات", current: 2480000, previous: 2202500, last_year: 1900000 },
          { key: "purchases", label: "المشتريات", current: 1320000, previous: 1100000, last_year: 900000 },
        ],
        sales_series: [
          { key: "2026-10-01", amount: 90000 },
          { key: "2026-10-02", amount: 120000 },
        ],
        sections: {
          sales: { gross: 2600000, net: 2480000, invoices: 425, average: 5835, change_pct: 12.6 },
          profit: { revenue: 2480000, cogs: 1150000, expenses: 310400, net_profit: 1017000 },
          customers: {
            credit_sales: 964000,
            collections: 1850000,
            receivables: 285300,
            top_debtors: [{ customer_id: 3, name: "مؤسسة النور التجارية", amount: 215000 }],
          },
          invoices: {
            paid: 425,
            partial: 314,
            credit: 230,
            cancelled: 12,
            returned: 8,
            total: 989,
            amount: 2480000,
          },
          cashflow: { inflow: 1850000, outflow: 1229250, net: 620750 },
        },
      });
    }
    if (path === "/reports/api/v2/section/equity") {
      const line = (key: string, label: string, amount: number) => ({ key, label, amount });
      return ok({
        success: true,
        filters: appliedFilters(),
        position: {
          assets: [
            line("cash", "النقد في الصناديق", 13000000),
            line("inventory", "البضاعة في المخازن (بسعر الكلفة)", 129524050),
          ],
          liabilities: [line("suppliers", "ديون للموردين", 70185000)],
          total_assets: 142524050,
          total_liabilities: 70185000,
          equity: 72339050,
          balanced: true,
          note: "حقوق الملكية = كل ما تملكه الشركة − كل ما عليها.",
        },
        profit: {
          net_revenue: 2480000,
          cogs: 1150000,
          gross_profit: 1330000,
          operating_expenses: 310400,
          other_expenses: 2600,
          net_profit: 1017000,
        },
        bridge: [
          line("stock_build", "بضاعة اشتريتها ولم تُبع بعد — تحولت إلى مخزون", -600000),
          line("owner", "سحوبات المالك", -200000),
          line("credit_sales", "بيع آجل لم يُقبض بعد — بقي عند الزبائن", 0),
        ],
        cash: { opening: 5000000, net_change: 217000, closing: 5217000 },
        went_to: { stock: 600000, owner: 200000, customers: 0, assets: 0 },
        summary: [
          "ربحت 1,017,000 د.ع في هذه الفترة (بعد الكلفة والمصاريف).",
          "600,000 د.ع تحول إلى بضاعة في المخازن.",
        ],
      });
    }
    if (path === "/reports/api/v2/section/sales") {
      return ok({
        success: true,
        filters: appliedFilters(),
        metrics: {
          gross: 2600000,
          net: 2480000,
          invoices: 2,
          items: 3,
          average: 1240000,
          discounts: 120000,
          returns: 0,
          returns_count: 0,
          cogs: 1150000,
          gross_profit: 1330000,
          change_pct: 12.6,
        },
        breakdown: {
          by: String(request.query?.by ?? "day"),
          rows: [{ key: "2026-10-01", label: "2026-10-01", count: 2, amount: 2480000 }],
        },
        rows: [
          {
            id: 10045,
            date: "2026-10-07 10:25",
            customer_id: 3,
            customer: "أحمد سالم",
            employee_id: 7,
            employee: "سارة",
            branch: "الفرع الرئيسي",
            gross: 450000,
            discount: 0,
            total: 450000,
            paid: 450000,
            remaining: 0,
            sale_type: "cash",
            status: "تم التوصيل",
            state: "مدفوعة",
          },
        ],
        pagination: { page: 1, page_size: 50, total: 1, total_pages: 1 },
      });
    }
    if (/^\/orders\/update-shipping-barcode\/\d+$/.test(path)) {
      return ok({
        success: true,
        message: "تم حفظ باركود شركة النقل وتحويل الطلب إلى جاري الشحن",
        status_changed: true,
        status: "جاري الشحن",
      });
    }
    if (path === "/orders/search-by-barcode") {
      const code = String(request.query?.barcode ?? "");
      const order = orders.find((o) => String(o.id) === code);
      return order
        ? ok({ success: true, invoice: { id: order.id } })
        : {
            ok: false,
            failure: "http",
            status: 404,
            data: { success: false, error: "لم يتم العثور على فاتورة" },
          };
    }
    if (path === "/purchases/api/products/search") {
      const q = String(request.query?.q ?? "");
      const all = [
        {
          id: 11,
          name: "شاشة LG 50 بوصة",
          sku: "TV-LG-50",
          barcode: "6290000000011",
          buy_price: 270000,
          quantity: 5,
          has_colors: false,
          colors: [],
        },
        {
          id: 12,
          name: "ثلاجة ايفولي 7 قدم",
          sku: "FR-EV-7",
          barcode: "6290000000077",
          buy_price: 337500,
          quantity: 2,
          has_colors: true,
          colors: [
            { name: "أبيض", qty: 1 },
            { name: "فضي", qty: 1 },
          ],
        },
      ];
      return ok(all.filter((p) => p.name.includes(q) || p.barcode === q || p.sku.includes(q)));
    }
    if (path === "/purchases/create")
      return ok({ success: true, purchase_id: 300, invoice_no: "PUR-TEST-300", message: "ok" });
    if (path === "/suppliers/api/quick-create") {
      const body = request.body as { name: string };
      return ok({ success: true, supplier: { id: 99, name: body.name } });
    }
    if (path === "/inventory/add") return ok({ success: true, product_id: 501, name: "x" });
    const detailsMatch = /^\/inventory\/api\/products\/(\d+)$/.exec(path);
    if (detailsMatch) {
      return ok({
        success: true,
        product: {
          id: Number(detailsMatch[1]),
          name: "شاشة LG 50 إنش 4K",
          sku: "TV-LG-50-2026",
          barcode: "6290000000011",
          buy_price: 280000,
          sale_price: 325000,
          exchange_sale_price: 300000,
          trade_in_sales_enabled: true,
          editor_settings_supported: true,
          pos_visible: true,
          store_visible: false,
          low_stock_threshold: 5,
          description: "",
          image_url: "",
          active: true,
          has_colors: false,
          current_stock: 28,
          colors_supported: true,
          options_supported: true,
          color_images_supported: true,
          colors: [],
          category: "شاشات",
          brand: "LG",
          unit: "",
        },
      });
    }
    if (/^\/inventory\/api\/products\/\d+\/update$/.test(path))
      return ok({ success: true, product_id: 1, image_url: "" });
    if (/^\/inventory\/adjust-stock\/\d+$/.test(path)) {
      const body = request.body as { adjustment: number };
      return ok({
        success: true,
        message: "تم الحفظ بنجاح: المخزون 28 → " + (28 + body.adjustment),
        new_quantity: 28 + body.adjustment,
        new_sale_price: 325000,
      });
    }
    return { ok: false, failure: "http", status: 404, data: null };
  };
  return { handler, calls, orders, purchases };
}
