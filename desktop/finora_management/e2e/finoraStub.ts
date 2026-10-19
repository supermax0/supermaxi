/**
 * Minimal stand-in for FINORA (test fixture only). Mirrors the real contracts:
 * JSON desktop sign-in with an HttpOnly session cookie, session-protected
 * pages that redirect to /login, and the orders/inventory/purchases JSON the
 * desktop reads (shapes from routes/orders.py, inventory.py, purchases.py).
 */
import { randomUUID, createHash } from "node:crypto";
import type { SnapshotManifest } from "../shared/snapshot";
import { createServer, type IncomingMessage, type Server, type ServerResponse } from "node:http";
import type { AddressInfo } from "node:net";
import { createSupplierFixture } from "./supplierFixture";
import { createHRFixture, HR_PERMISSIONS } from "./hrFixture";
import { createFinanceFixture, FINANCE_PERMISSIONS } from "./financeFixture";
import { createCustomersFixture } from "./customersFixture";
import { handleBranches } from "./branchesStub";
import { handleShipping } from "./shippingStub";

export const STUB_CREDENTIALS = { tenantSlug: "e2e-co", username: "sara", password: "Stub-Pass-123" };

const SESSION = {
  user: { id: 7, name: "سارة", username: "sara", role: "admin" },
  tenant: { id: 1, slug: "e2e-co", name: "شركة الاختبار", business_type: "general" },
  branch: { id: 1, name: "الفرع الرئيسي" },
  roles: ["admin"],
  permissions: [
    "can_see_orders",
    "can_see_orders_placed",
    "can_see_orders_packed",
    "can_see_orders_shipped",
    "can_see_orders_delivered",
    "can_see_orders_returned",
    "manage_orders",
    "return_orders",
    "print_pos_invoice",
    "can_manage_inventory",
    "view_pos",
    "pay_orders",
    "can_manage_suppliers",
    "edit_price",
    "edit_current_stock",
    "view_expenses",
    "can_see_shipping",
    "can_manage_shipping",
  ],
  session_max_age_seconds: 604800,
  offline_pos_enabled: true,
};

// 1×1 PNG
const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  "base64",
);

function order(id: number, name: string, city: string, status: string, total: number) {
  return {
    id,
    order_id: id,
    date: "2026-10-07 10:25",
    customer_name: name,
    phone: "07701234567",
    phone2: "—",
    city,
    address: "شارع الجامعة",
    total,
    paid_amount: 0,
    remaining: total,
    status,
    payment_status: "غير مسدد",
    shipping_company_id: null,
    shipping_company: "—",
    delivery_agent_id: null,
    delivery_agent: "—",
    employee: "سارة",
    note: "",
    quantity: 1,
    is_stock_locked: false,
  };
}

export interface FinoraStub {
  url: string;
  requests: string[];
  bodies: Array<{ path: string; body: unknown }>;
  setOnline(online: boolean): void;
  close(): Promise<void>;
}

function send(res: ServerResponse, status: number, body: unknown, headers: Record<string, string> = {}) {
  res.writeHead(status, { "Content-Type": "application/json", "Cache-Control": "no-store", ...headers });
  res.end(JSON.stringify(body));
}

async function readJson(req: IncomingMessage): Promise<Record<string, unknown>> {
  const chunks: Buffer[] = [];
  for await (const chunk of req) chunks.push(chunk as Buffer);
  try {
    const parsed: unknown = JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}");
    return typeof parsed === "object" && parsed !== null ? (parsed as Record<string, unknown>) : {};
  } catch {
    return {};
  }
}

export async function startFinoraStub(
  options: {
    hr?: boolean;
    orderEditing?: boolean;
    orderCollection?: boolean;
    finance?: boolean;
    financeVouchers?: Record<string, unknown>[];
    customers?: boolean;
    customerPlanBuilder?: boolean;
    customerDebtBuilder?: boolean;
    customerPriorPayments?: boolean;
    customerVoucherHistory?: boolean;
    customerReversedHistory?: boolean;
    customerStatementHtml?: string;
    customerTransactionsHtml?: string;
    customerAccountHistory?: { data: Record<string, unknown>; html: string; csv: string };
    dropFirstCustomerSaveResponse?: boolean;
    stockOperationsServer?: string;
    cashShiftServer?: string;
    posStorageServer?: string;
    orderLifecycleServer?: string;
    dropFirstStockWriteoffResponse?: boolean;
    productSaveDelayMs?: number;
    failFirstProductSave?: boolean;
  } = {},
): Promise<FinoraStub> {
  let productSaveAttempts = 0;
  const saveProduct = async (res: ServerResponse, productId: number) => {
    productSaveAttempts++;
    if (options.productSaveDelayMs)
      await new Promise((resolve) => setTimeout(resolve, options.productSaveDelayMs));
    if (options.failFirstProductSave && productSaveAttempts === 1)
      return send(res, 500, { success: false, message: "تعذر حفظ المنتج، حاول مجدداً." });
    return send(res, 200, { success: true, product_id: productId, image_url: "/static/uploads/lg.png" });
  };
  const hrFixture = options.hr ? createHRFixture() : null;
  const financeFixture = options.finance
    ? createFinanceFixture(options.financeVouchers, options.customers)
    : null;
  const customersFixture = options.customers
    ? createCustomersFixture(
        !!options.customerPlanBuilder,
        !!options.customerDebtBuilder,
        !!options.customerPriorPayments,
        !!options.customerVoucherHistory,
        !!options.customerReversedHistory,
      )
    : null;
  const activeSession = {
    ...SESSION,
    permissions: [
      ...SESSION.permissions,
      ...(options.orderCollection ? ["pay_orders"] : []),
      ...(options.orderLifecycleServer ? ["pay_orders", "return_orders"] : []),
      ...(options.hr ? HR_PERMISSIONS : []),
      ...(options.finance ? FINANCE_PERMISSIONS : []),
      ...(options.customers ? ["manage_customers"] : []),
      ...(options.stockOperationsServer
        ? [
            "can_manage_inventory",
            "edit_current_stock",
            "edit_product",
            "finance.view",
            "finance.approve",
            "view_reports",
            "view_financial",
          ]
        : []),
    ],
  };
  const snapshots = new Map<string, { manifest: SnapshotManifest; datasets: Record<string, unknown[]> }>();
  const supplierFixture = createSupplierFixture();
  const sessions = new Set<string>();
  const requests: string[] = [];
  const bodies: Array<{ path: string; body: unknown }> = [];
  let droppedCustomerSaveResponse = false;
  let droppedStockSaveResponse = false;
  let online = true;
  const syncReceipts = new Map<string, unknown>();
  const stockGrants = new Map<string, unknown>();
  const posReceipts = new Map<string, unknown>();
  const orders = [
    order(10045, "أحمد سالم", "بغداد", "تم الطلب", 450000),
    order(10044, "فاطمة محمد", "البصرة", "معباة", 180000),
    order(10043, "حسن علاء", "أربيل", "جاري الشحن", 720000),
  ];
  if (options.customers)
    orders.unshift({
      ...order(10, "أحمد العميل", "بغداد", "تم التوصيل", 300000),
      paid_amount: 100000,
      payment_status: "جزئي",
    });
  const purchases = [
    { id: 48, invoice_no: "P-2026-0048", tab: "unpaid", status: "confirmed" },
    { id: 47, invoice_no: "P-2026-0047", tab: "draft", status: "draft" },
  ].map((p) => ({
    ...p,
    date: "2026-10-07",
    supplier_id: 3,
    supplier: "شركة الرافدين",
    supplier_invoice_no: "",
    notes: "شاشات",
    item_count: 2,
    first_product: "شاشة LG",
    grand_total: 12450000,
    paid_total: 0,
    remaining_total: 12450000,
    purchase_mode: "credit",
    items: [],
    payments: [],
  }));

  const sessionOf = (req: IncomingMessage) => {
    const match = /(?:^|;\s*)session=([^;]+)/.exec(req.headers.cookie ?? "");
    return match?.[1] && sessions.has(match[1]) ? match[1] : null;
  };

  const server: Server = createServer((req, res) => {
    if (!online) {
      req.socket.destroy();
      return;
    }
    const url = new URL(req.url ?? "/", "http://stub");
    const path = url.pathname;
    requests.push(`${req.method} ${path}`);
    void (async () => {
      if (req.method === "POST" && path === "/api/v1/desktop/auth/login") {
        const body = await readJson(req);
        const ok =
          body.tenant_slug === STUB_CREDENTIALS.tenantSlug &&
          body.username === STUB_CREDENTIALS.username &&
          body.password === STUB_CREDENTIALS.password;
        if (!ok) {
          return send(res, 401, { ok: false, error: "بيانات الدخول غير صحيحة", code: "invalid_credentials" });
        }
        const id = randomUUID();
        sessions.add(id);
        return send(
          res,
          200,
          { ok: true, session: activeSession },
          { "Set-Cookie": `session=${id}; HttpOnly; Path=/; SameSite=Lax; Max-Age=604800` },
        );
      }
      if (req.method === "GET" && path === "/api/v1/desktop/auth/session") {
        return sessionOf(req)
          ? send(res, 200, { ok: true, session: activeSession })
          : send(res, 401, {
              ok: false,
              error: "انتهت الجلسة، سجّل الدخول من جديد",
              code: "unauthenticated",
            });
      }
      if (req.method === "POST" && path === "/api/v1/desktop/auth/logout") {
        const id = sessionOf(req);
        if (id) sessions.delete(id);
        return send(
          res,
          200,
          { ok: true, signed_out: true },
          { "Set-Cookie": "session=; Path=/; Max-Age=0" },
        );
      }

      // Everything below is session-protected like FINORA's pages.
      if (!sessionOf(req)) {
        res.writeHead(302, { Location: "/login" });
        return res.end();
      }
      if (path === "/api/v1/desktop/workspace")
        return send(res, 200, { ok: true, pages: ["notes", "messages"] });
      if (path === "/notes" || path === "/messages") {
        res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
        return res.end(
          '<!doctype html><html><body><h1>FINORA workspace</h1><form><label>ملاحظة<input name="note"></label></form></body></html>',
        );
      }
      if (
        options.cashShiftServer &&
        (path.startsWith("/api/finance/") ||
          path.startsWith("/accounts/finance/cash-shifts/") ||
          path.startsWith("/accounts/finance/control/"))
      ) {
        const target = new URL(options.cashShiftServer);
        if (target.hostname !== "127.0.0.1" || target.protocol !== "http:")
          throw Error("Cash shift test server must be loopback");
        const body = req.method === "POST" ? await readJson(req) : undefined;
        if (body) bodies.push({ path, body });
        const response = await fetch(new URL(url.pathname + url.search, target), {
          method: req.method,
          headers: { "Content-Type": "application/json" },
          ...(body ? { body: JSON.stringify(body) } : {}),
        });
        res.writeHead(response.status, {
          "Content-Type": response.headers.get("content-type") ?? "application/json",
          "Cache-Control": "no-store",
        });
        return res.end(Buffer.from(await response.arrayBuffer()));
      }
      if (options.orderLifecycleServer && (path.startsWith("/orders/") || path === "/api/branch/list")) {
        const target = new URL(options.orderLifecycleServer);
        if (target.hostname !== "127.0.0.1" || target.protocol !== "http:")
          throw Error("Order test server must be loopback");
        const body = req.method === "POST" ? await readJson(req) : undefined;
        if (body) bodies.push({ path, body });
        const response = await fetch(new URL(url.pathname + url.search, target), {
          method: req.method,
          headers: { "Content-Type": "application/json" },
          ...(body ? { body: JSON.stringify(body) } : {}),
        });
        res.writeHead(response.status, {
          "Content-Type": response.headers.get("content-type") ?? "application/json",
          "Cache-Control": "no-store",
        });
        res.end(Buffer.from(await response.arrayBuffer()));
        return;
      }
      if (
        options.posStorageServer &&
        (path.startsWith("/pos/") || path === "/orders/payment-accounts" || path === "/orders/payment")
      ) {
        const target = new URL(options.posStorageServer);
        if (target.hostname !== "127.0.0.1" || target.protocol !== "http:")
          throw Error("POS test server must be loopback");
        const body = req.method === "POST" ? await readJson(req) : undefined;
        if (body) bodies.push({ path, body });
        const reply = await fetch(new URL(url.pathname + url.search, target), {
          method: req.method,
          headers: { "Content-Type": "application/json" },
          ...(body ? { body: JSON.stringify(body) } : {}),
        });
        res.writeHead(reply.status, {
          "Content-Type": reply.headers.get("content-type") ?? "application/json",
          "Cache-Control": "no-store",
        });
        res.end(Buffer.from(await reply.arrayBuffer()));
        return;
      }
      if (
        options.stockOperationsServer &&
        (path.startsWith("/api/v1/desktop/stock-operations/") ||
          (req.method === "GET" && path.startsWith("/reports/api/v2/")))
      ) {
        const target = new URL(options.stockOperationsServer);
        if (target.hostname !== "127.0.0.1" || target.protocol !== "http:")
          throw Error("Stock test server must be loopback");
        const body = req.method === "POST" ? await readJson(req) : undefined;
        if (body) bodies.push({ path, body });
        const response = await fetch(new URL(url.pathname + url.search, target), {
          method: req.method,
          headers: { "Content-Type": "application/json" },
          ...(body ? { body: JSON.stringify(body) } : {}),
        });
        const content = Buffer.from(await response.arrayBuffer());
        if (
          options.dropFirstStockWriteoffResponse &&
          !droppedStockSaveResponse &&
          req.method === "POST" &&
          path.endsWith("/branch/writeoffs") &&
          response.ok
        ) {
          droppedStockSaveResponse = true;
          // Keep the committed receipt while the real client timeout aborts
          // the response. Chromium can transparently retry a socket reset.
          return;
        }
        res.writeHead(response.status, {
          "Content-Type": response.headers.get("content-type") ?? "application/json",
          "Cache-Control": "no-store",
        });
        res.end(content);
        return;
      }
      if (path === "/api/v1/desktop/snapshots") {
        const body = await readJson(req);
        const id = String(body.id);
        if (!snapshots.has(id)) {
          const data = supplierFixture.snapshotData();
          const page = supplierFixture.handle(
            "/suppliers/api/page",
            "GET",
            new URL("http://stub/suppliers/api/page"),
            {},
          );
          const meta = page?.data as { counts: Record<string, number>; summary: Record<string, number> };
          const datasets: Record<string, unknown[]> = {
            suppliers: data.rows,
            "supplier-products": data.products,
            "supplier-details": data.rows.map((row) => ({
              id: row.id,
              value: supplierFixture.handle(`/suppliers/api/${row.id}`, "GET", new URL("http://stub"), {})
                ?.data,
            })),
          };
          snapshots.set(id, {
            datasets,
            manifest: {
              success: true,
              version: 1,
              id,
              tenant_slug: SESSION.tenant.slug,
              user_id: SESSION.user.id,
              branch_id: 1,
              branch_scope: "branch",
              permissions: activeSession.permissions,
              started_at: Date.now(),
              captured_at: Date.now(),
              expires_at: Date.now() + 86400000,
              datasets: [
                {
                  name: "suppliers",
                  total: data.rows.length,
                  page_size: 100,
                  meta: { success: true, counts: meta.counts, summary: meta.summary },
                },
                { name: "supplier-products", total: data.products.length, page_size: 100, meta: {} },
                { name: "supplier-details", total: data.rows.length, page_size: 100, meta: {} },
              ],
            },
          });
        }
        const generation = snapshots.get(id);
        if (!generation) throw new Error("Fixture snapshot was not created");
        return send(res, 200, generation.manifest);
      }
      const snapshotPage = path.match(/^\/api\/v1\/desktop\/snapshots\/([^/]+)\/([^/]+)$/);
      if (snapshotPage) {
        const generationId = snapshotPage[1] ?? "";
        const dataset = snapshotPage[2] ?? "";
        const snapshot = snapshots.get(generationId);
        const cursor = Number(url.searchParams.get("cursor"));
        const rows = snapshot?.datasets[dataset]?.slice(cursor, cursor + 100);
        if (!rows) return send(res, 404, { success: false });
        const rowsJson = JSON.stringify(rows);
        return send(res, 200, {
          success: true,
          id: snapshotPage[1],
          dataset: snapshotPage[2],
          cursor,
          next_cursor: cursor + rows.length,
          rows_json: rowsJson,
          digest: createHash("sha256").update(rowsJson).digest("hex"),
        });
      }
      if (path === "/api/v1/desktop/stock/reserve") {
        const body = await readJson(req);
        bodies.push({ path, body });
        const id = String(body.id);
        if (!stockGrants.has(id)) {
          const items = body.items as Array<{ product_id: number; qty: number; variant_color?: string }>;
          stockGrants.set(id, {
            success: true,
            id,
            device_id: body.device_id,
            employee_id: SESSION.user.id,
            branch_id: SESSION.branch.id,
            allocations: items.map((i) => ({
              id: randomUUID(),
              product_id: i.product_id,
              name: "شاشة LG 50 بوصة",
              variant_color: i.variant_color ?? "",
              quantity: i.qty,
              sale_price: 282000,
            })),
          });
        }
        return send(res, 200, stockGrants.get(id));
      }
      if (path === "/api/v1/desktop/sync/pos-sale") {
        const body = await readJson(req);
        bodies.push({ path, body });
        const id = String(body.operation_id),
          sale = body.sale as { total: number };
        if (!posReceipts.has(id))
          posReceipts.set(id, { success: true, invoice_no: "10047", invoice_id: 10047, total: sale.total });
        return send(res, 200, posReceipts.get(id));
      }
      if (path === "/api/v1/desktop/sync/supplier-sale") {
        const body = await readJson(req);
        bodies.push({ path, body });
        const id = String(body.operation_id);
        if (syncReceipts.has(id)) return send(res, 200, syncReceipts.get(id));
        const response = supplierFixture.handle(
          `/suppliers/api/${Number(body.supplier_id)}/sale`,
          "POST",
          url,
          body,
        );
        if (response) {
          if (response.status === 200) syncReceipts.set(id, response.data);
          return send(res, response.status, response.data);
        }
      }
      if (hrFixture && path.startsWith("/hr/api/")) {
        const body = req.method === "POST" ? await readJson(req) : {};
        if (req.method === "POST") bodies.push({ path, body });
        const response = hrFixture.handle(path, req.method ?? "GET", url, body);
        if (response) return send(res, response.status, response.data);
      }
      if (financeFixture && path.startsWith("/api/finance/")) {
        const body = req.method === "POST" ? await readJson(req) : {};
        if (req.method === "POST") bodies.push({ path, body });
        const response = financeFixture.handle(path, req.method ?? "GET", url, body);
        if (response) return send(res, response.status, response.data);
      }
      if (customersFixture && path.startsWith("/api/v1/desktop/customers")) {
        const historical = options.customerAccountHistory;
        if (
          historical &&
          /^\/api\/v1\/desktop\/customers\/\d+\/account-history(?:\/(?:print|export))?$/.test(path)
        ) {
          if (req.method !== "GET") return send(res, 405, { success: false });
          if (path.endsWith("/print")) {
            res.writeHead(200, { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" });
            return res.end(historical.html);
          }
          if (path.endsWith("/export"))
            return send(res, 200, {
              success: true,
              data: { content: historical.csv, filename: "account-history.csv" },
            });
          return send(res, 200, { success: true, data: historical.data });
        }
        if (
          options.customerTransactionsHtml &&
          /^\/api\/v1\/desktop\/customers\/\d+\/transactions\/print$/.test(path)
        ) {
          res.writeHead(200, { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" });
          return res.end(options.customerTransactionsHtml);
        }
        if (
          options.customerStatementHtml &&
          /^\/api\/v1\/desktop\/customers\/\d+\/statement\/print$/.test(path)
        ) {
          res.writeHead(200, { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" });
          return res.end(options.customerStatementHtml);
        }
        const body = req.method === "POST" ? await readJson(req) : {};
        if (req.method === "POST") bodies.push({ path, body });
        const response = customersFixture.handle(path, url, req.method, body);
        if (
          response &&
          response.status === 200 &&
          req.method === "POST" &&
          options.dropFirstCustomerSaveResponse &&
          !droppedCustomerSaveResponse
        ) {
          droppedCustomerSaveResponse = true;
          // Commit the fixture but withhold its reply until the client's real
          // timeout aborts the socket. Recovery receives the saved receipt.
          return;
        }
        if (response) return send(res, response.status, response.data);
      }
      if (path.startsWith("/suppliers/api/")) {
        const body = req.method === "POST" ? await readJson(req) : {};
        if (req.method === "POST") bodies.push({ path, body });
        const response = supplierFixture.handle(path, req.method ?? "GET", url, body);
        if (response) return send(res, response.status, response.data);
      }
      if (path === "/orders/data") {
        const search = url.searchParams.get("search") ?? "";
        const rows = orders.filter(
          (o) => !search || o.customer_name.includes(search) || String(o.id).includes(search),
        );
        return send(res, 200, {
          success: true,
          rows: options.orderCollection ? rows.map((row) => ({ ...row, can_pay: true })) : rows,
          page: 1,
          page_size: 25,
          total: rows.length,
          total_pages: 1,
          total_amount: 0,
        });
      }
      if (options.orderEditing && path.startsWith("/orders/details/")) {
        const row = orders.find((entry) => entry.id === Number(path.split("/").pop()));
        if (!row) return send(res, 404, { error: "الطلب غير موجود" });
        return send(res, 200, {
          order: {
            id: row.id,
            customer_id: options.customers && row.id === 10 ? 1 : 9,
            customer: row.customer_name,
            phone: row.phone,
            phone2: "",
            city: row.city,
            address: row.address,
            employee: row.employee,
            total: row.total,
            paid_amount: row.paid_amount,
            discount_amount: 0,
            status: row.status,
            payment: row.payment_status,
            created_at: "2026-10-07 10:25:00",
            shipping_company: null,
            note: row.note,
            can_edit_invoice: true,
            can_edit_customer: true,
            can_edit_price: true,
          },
          items: [
            {
              id: 1,
              product_id: 1,
              name: "شاشة LG",
              qty: row.quantity,
              price: row.total / row.quantity,
              total: row.total,
              variant_color: "أسود",
              sale_mode: "normal",
            },
          ],
        });
      }
      if (options.orderEditing && req.method === "POST" && path.startsWith("/orders/quick-edit/")) {
        const body = await readJson(req);
        bodies.push({ path, body });
        const row = orders.find((entry) => entry.id === Number(path.split("/").pop()));
        const items = body.items as Array<{ qty: number; price: number }>;
        if (!row || !items?.length) return send(res, 400, { error: "بيانات الطلب غير صالحة" });
        const customer = body.customer as { name: string } | undefined;
        if (customer) row.customer_name = customer.name;
        row.note = String(body.note ?? "");
        row.quantity = items.reduce((sum, item) => sum + item.qty, 0);
        row.total =
          items.reduce((sum, item) => sum + item.qty * item.price, 0) - Number(body.discount_amount ?? 0);
        row.remaining = row.total;
        return send(res, 200, { success: true, invoice_id: row.id });
      }
      if (path === "/orders/api/counts") {
        return send(res, 200, {
          success: true,
          counts: { all: 3, ordered: 1, packed: 1, shipping: 1, delivered: 0, returned: 0 },
        });
      }
      if (path === "/orders/api/lookups") {
        return send(res, 200, {
          success: true,
          cities: ["أربيل", "البصرة", "بغداد"],
          shipping_companies: [{ id: 1, name: "النقل السريع" }],
          delivery_agents: [{ id: 2, name: "مندوب علي" }],
          branches: [{ id: 1, name: "الفرع الرئيسي" }],
        });
      }
      if (req.method === "POST" && path === "/orders/bulk-status") {
        const body = (await readJson(req)) as { order_ids?: number[]; status?: string };
        bodies.push({ path, body });
        for (const o of orders) if (body.order_ids?.includes(o.id) && body.status) o.status = body.status;
        const ids = body.order_ids ?? [];
        return send(res, 200, { success: true, updated: ids.length, updated_ids: ids, skipped_ids: [] });
      }
      if (path.startsWith("/reports/api/v2/print/")) {
        res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
        return res.end(
          `<!doctype html><html lang="ar" dir="rtl"><body><h1>تقرير ${path.split("/").pop()}</h1><p>${url.searchParams.get("period")}</p></body></html>`,
        );
      }
      if (await handleBranches(req, res, path, url, send, readJson)) return;
      if (await handleShipping(req, res, path, url, send, readJson)) return;
      if (path === "/expenses/api/meta") {
        return send(res, 200, {
          success: true,
          categories: [
            { key: "rent", label: "إيجار", icon: "🏠", builtin: true },
            { key: "salary", label: "رواتب", icon: "💰", builtin: true },
            { key: "electricity", label: "كهرباء", icon: "⚡", builtin: true },
            { key: "internet", label: "إنترنت", icon: "🌐", builtin: true },
            { key: "advertising", label: "إعلان", icon: "📢", builtin: true },
            { key: "maintenance", label: "صيانة", icon: "🔧", builtin: true },
            { key: "other", label: "أخرى", icon: "📦", builtin: true },
          ],
          treasury_accounts: [
            { id: 4, name: "الصندوق الرئيسي", type: "cash", is_default: true, branch_name: "مشترك" },
            { id: 5, name: "مصرف الرافدين", type: "bank", is_default: false, branch_name: "مشترك" },
          ],
          today: "2026-10-15",
        });
      }
      if (path === "/expenses/api/page") {
        const expense = (
          id: number,
          title: string,
          key: string,
          label: string,
          icon: string,
          amount: number,
          date: string,
          status: "posted" | "scheduled",
          note = "",
          repeat: [number, number] | null = null,
        ) => ({
          id,
          title,
          category: key,
          category_key: key,
          category_label: label,
          category_icon: icon,
          amount,
          note,
          base_note: note,
          expense_date: date,
          post_time: status === "scheduled" ? "09:00" : "",
          treasury_account_id: 4,
          treasury_account_name: "الصندوق الرئيسي",
          cash_posted: status === "posted",
          status,
          repeat_index: repeat ? repeat[0] : null,
          repeat_total: repeat ? repeat[1] : null,
          repeat_series_id: repeat ? "s-1" : null,
          is_payroll: false,
          created_at: `${date} 09:00`,
        });
        return send(res, 200, {
          success: true,
          rows: [
            expense(
              58,
              "إيجار المحل — تشرين الأول",
              "rent",
              "إيجار",
              "🏠",
              1500000,
              "2026-10-15",
              "posted",
              "الدفعة الشهرية",
              [10, 12],
            ),
            expense(
              57,
              "فاتورة كهرباء المولدة",
              "electricity",
              "كهرباء",
              "⚡",
              240000,
              "2026-10-14",
              "posted",
            ),
            expense(
              56,
              "حملة إعلانية — إنستغرام",
              "advertising",
              "إعلان",
              "📢",
              350000,
              "2026-10-12",
              "posted",
              "حملة الخصومات",
            ),
            expense(55, "صيانة مكيف الصالة", "maintenance", "صيانة", "🔧", 85000, "2026-10-10", "posted"),
            expense(
              54,
              "اشتراك الإنترنت",
              "internet",
              "إنترنت",
              "🌐",
              60000,
              "2026-10-05",
              "posted",
              "",
              [4, 12],
            ),
            expense(
              59,
              "إيجار المحل — تشرين الثاني",
              "rent",
              "إيجار",
              "🏠",
              1500000,
              "2026-11-15",
              "scheduled",
              "الدفعة الشهرية",
              [11, 12],
            ),
          ],
          page: 1,
          page_size: 25,
          total: 6,
          total_pages: 1,
          counts: { all: 6, posted: 5, scheduled: 1 },
          summary: {
            today_total: 1500000,
            month_total: 2235000,
            year_total: 18640000,
            scheduled_total: 3000000,
            scheduled_count: 2,
            filtered_total: 3735000,
          },
          by_category: [
            { key: "rent", label: "إيجار", icon: "🏠", amount: 3000000, count: 2 },
            { key: "advertising", label: "إعلان", icon: "📢", amount: 350000, count: 1 },
            { key: "electricity", label: "كهرباء", icon: "⚡", amount: 240000, count: 1 },
            { key: "maintenance", label: "صيانة", icon: "🔧", amount: 85000, count: 1 },
            { key: "internet", label: "إنترنت", icon: "🌐", amount: 60000, count: 1 },
          ],
        });
      }
      if (path === "/orders/print-invoices") {
        res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
        return res.end(
          `<!doctype html><html lang="ar" dir="rtl"><body><h1>فواتير ${url.searchParams.get("ids")}</h1></body></html>`,
        );
      }
      if (path === "/inventory/api/products") {
        return send(res, 200, {
          success: true,
          rows: [
            {
              id: 1,
              name: "شاشة LG 50 إنش",
              sku: "TV-LG-50-2026",
              barcode: "6290000000011",
              category: "شاشات",
              image_url: "/static/uploads/lg.png",
              buy_price: 280000,
              sale_price: 325000,
              quantity: 28,
              low_stock_threshold: 5,
              stock_state: "available",
              active: true,
            },
          ],
          page: 1,
          page_size: 25,
          total: 1,
          total_pages: 1,
          stats: { total: 542, available: 418, low: 86, out: 38 },
          categories: ["شاشات", "مكيفات"],
          branch_scope_label: "كل الفروع",
        });
      }
      if (path === "/static/uploads/lg.png") {
        res.writeHead(200, { "Content-Type": "image/png" });
        return res.end(PNG);
      }
      if (path === "/purchases/api/page") {
        const tab = url.searchParams.get("tab") ?? "all";
        const rows = purchases.filter((p) => tab === "all" || p.tab === tab);
        return send(res, 200, {
          success: true,
          rows,
          page: 1,
          page_size: 25,
          total: rows.length,
          total_pages: 1,
          counts: { all: 2, draft: 1, confirmed: 0, unpaid: 1, cancelled: 0 },
          summary: { total_amount: 158750000, count: 42, draft: 1, unpaid: 5, remaining_amount: 0 },
          suppliers: [{ id: 3, name: "شركة الرافدين" }],
        });
      }
      if (path === "/pos/api/bootstrap") {
        return send(res, 200, {
          success: true,
          provinces: ["بغداد", "البصرة", "كربلاء"],
          branch_id: 1,
          can_edit_price: true,
          can_print: true,
          can_pay: true,
        });
      }
      if (path === "/pos/api/products") {
        const search = url.searchParams.get("search") ?? "";
        const all = [
          {
            id: 1,
            name: "شاشة LG 50 بوصة",
            sku: "4K - Smart - LED",
            barcode: "6290000000011",
            price: 282000,
            quantity: 5,
            image_url: "/static/uploads/lg.png",
            category: "شاشات",
            has_colors: false,
            colors: [],
          },
          {
            id: 2,
            name: "مكيف جنرال 1 طن",
            sku: "بارد - انفرتر",
            barcode: "6290000000035",
            price: 415000,
            quantity: 4,
            image_url: "/static/uploads/lg.png",
            category: "مكيفات",
            has_colors: false,
            colors: [],
          },
          {
            id: 3,
            name: "Samsung A55",
            sku: "128GB - 5G",
            barcode: "6290000000042",
            price: 320000,
            quantity: 7,
            image_url: "/static/uploads/lg.png",
            category: "هواتف",
            has_colors: false,
            colors: [],
          },
          {
            id: 4,
            name: "ASUS X515",
            sku: "15.6 - Core i5",
            barcode: "6290000000059",
            price: 725000,
            quantity: 2,
            image_url: "/static/uploads/lg.png",
            category: "لابتوبات",
            has_colors: false,
            colors: [],
          },
        ];
        const rows = all.filter((p) => !search || p.name.includes(search) || p.barcode === search);
        return send(res, 200, {
          success: true,
          rows,
          page: 1,
          page_size: 24,
          total: rows.length,
          total_pages: 1,
          categories: ["شاشات", "مكيفات", "هواتف", "لابتوبات"],
        });
      }
      if (path === "/pos/search-customer") {
        return send(res, 200, [
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
      if (req.method === "POST" && path === "/pos/create-order") {
        const body = (await readJson(req)) as {
          items?: Array<{ qty: number; price: number }>;
          discount_amount?: number;
        };
        bodies.push({ path, body });
        const total =
          (body.items ?? []).reduce((sum, item) => sum + item.qty * item.price, 0) -
          (body.discount_amount ?? 0);
        return send(res, 200, {
          success: true,
          invoice_id: 10046,
          order_id: 10046,
          total,
          updated: false,
          stock_locked: false,
        });
      }
      if (path === "/orders/payment-accounts") {
        return send(res, 200, {
          success: true,
          accounts: [
            {
              id: 4,
              name: "صندوق الفرع",
              type: "cash",
              is_default: true,
              branch_id: 1,
              branch_name: "الفرع الرئيسي",
              label: "",
            },
            {
              id: 5,
              name: "بطاقة ماستر",
              type: "bank",
              is_default: false,
              branch_id: 1,
              branch_name: "الفرع الرئيسي",
              label: "",
            },
            {
              id: 6,
              name: "أقساط كي كارد",
              type: "bank",
              is_default: false,
              branch_id: 1,
              branch_name: "الفرع الرئيسي",
              label: "",
            },
            {
              id: 7,
              name: "بطاقة ماستر",
              type: "bank",
              is_default: false,
              branch_id: 2,
              branch_name: "فرع البصرة",
              label: "",
            },
            {
              id: 8,
              name: "أقساط كي كارد",
              type: "bank",
              is_default: false,
              branch_id: 2,
              branch_name: "فرع البصرة",
              label: "",
            },
          ],
        });
      }
      if (req.method === "POST" && path === "/orders/payment") {
        bodies.push({ path, body: await readJson(req) });
        return send(res, 200, { success: true });
      }
      if (path === "/purchases/api/products/search") {
        const q = url.searchParams.get("q") ?? "";
        const all = [
          {
            id: 1,
            name: "شاشة LG 50 بوصة",
            sku: "TV-LG-50-2026",
            barcode: "6290000000011",
            buy_price: 270000,
            quantity: 28,
            has_colors: false,
            colors: [],
          },
          {
            id: 2,
            name: "ثلاجة ايفولي 7 قدم",
            sku: "FR-EV-7",
            barcode: "6290000000077",
            buy_price: 337500,
            quantity: 4,
            has_colors: true,
            colors: [
              { name: "أبيض", qty: 2 },
              { name: "فضي", qty: 2 },
            ],
          },
          {
            id: 3,
            name: "غسالة دنكا 16 كيلو",
            sku: "WM-DN-16",
            barcode: "6290000000084",
            buy_price: 205000,
            quantity: 6,
            has_colors: false,
            colors: [],
          },
        ];
        return send(
          res,
          200,
          all.filter((p) => p.name.includes(q) || p.barcode === q || p.sku.includes(q)),
        );
      }
      if (req.method === "POST" && path === "/purchases/create") {
        bodies.push({ path, body: await readJson(req) });
        return send(res, 200, {
          success: true,
          purchase_id: 301,
          invoice_no: "PUR-20261007-E2E",
          message: "ok",
        });
      }
      if (req.method === "POST" && path === "/inventory/add") {
        const chunks: Buffer[] = [];
        for await (const chunk of req) chunks.push(chunk as Buffer);
        const raw = Buffer.concat(chunks).toString("utf8");
        bodies.push({ path, body: { contentType: req.headers["content-type"] ?? "", raw } });
        return saveProduct(res, 777);
      }
      if (path === "/inventory/api/products/1") {
        return send(res, 200, {
          success: true,
          product: {
            id: 1,
            name: "شاشة LG 50 إنش",
            sku: "TV-LG-50-2026",
            barcode: "6290000000011",
            buy_price: 280000,
            sale_price: 325000,
            exchange_sale_price: 300000,
            trade_in_sales_enabled: true,
            editor_settings_supported: true,
            pos_visible: true,
            store_visible: true,
            low_stock_threshold: 5,
            description: "",
            image_url: "/static/uploads/lg.png",
            active: true,
            has_colors: false,
            current_stock: 28,
            colors_supported: true,
            options_supported: true,
            color_images_supported: true,
            colors: [],
            category: "شاشات",
            brand: "LG",
            unit: "قطعة",
          },
        });
      }
      if (req.method === "POST" && path === "/inventory/api/products/1/update") {
        const chunks: Buffer[] = [];
        for await (const chunk of req) chunks.push(chunk as Buffer);
        bodies.push({ path, body: { raw: Buffer.concat(chunks).toString("utf8") } });
        return saveProduct(res, 1);
      }
      return send(res, 404, { error: "not found" });
    })();
  });

  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address() as AddressInfo;
  return {
    url: `http://127.0.0.1:${port}`,
    requests,
    bodies,
    setOnline: (next: boolean) => {
      online = next;
    },
    close: () =>
      new Promise<void>((resolve) => {
        server.closeAllConnections();
        server.close(() => resolve());
      }),
  };
}
