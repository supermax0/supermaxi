/**
 * IPC contract between the Electron main process and the renderer.
 *
 * Every payload crossing the bridge is validated with these schemas on the
 * main side; the renderer only ever sees the typed `FinoraDesktopBridge`.
 */
import { z } from "zod";
import type { OfflineBridge } from "./offline";
import type { CustomerRecoveryBridge } from "./customerRecovery";
import type { LocalAssistantBridge } from "./localAssistant";

export { IPC } from "./channels";

/** FINORA areas the desktop client may call. Anything else is refused in main. */
export const ALLOWED_PATH_PREFIXES = [
  "/api/v1/desktop/",
  "/orders/",
  "/purchases/",
  "/inventory/",
  "/suppliers/",
  "/hr/api/",
  "/api/finance/",
  "/shipping/",
  "/delivery/",
  "/pos/",
  "/reports/api/v2/",
  // Only the read-only assistant's desktop adapters; provider settings stay inaccessible here.
  "/finora-ai/api/desktop/",
  // expenses window: JSON API + the page's own delete / add-category actions (not the HTML page)
  "/expenses/api/",
  "/expenses/delete/",
  "/expenses/categories/add",
  // exact helpers reused by the order payment dialog (not whole /api areas)
  "/api/delivery-fee/quote",
  "/api/branch/list",
] as const;

const QUERY_VALUE = z.union([z.string().max(500), z.number().finite(), z.boolean()]);

export const requestPathSchema = z
  .string()
  .min(2)
  .max(300)
  .refine((path) => /^\/[A-Za-z0-9\-._~/%]*$/.test(path), "invalid characters")
  .refine((path) => !path.includes("//") && !/(^|\/)\.\.?(\/|$)/.test(path), "path traversal")
  .refine((path) => ALLOWED_PATH_PREFIXES.some((prefix) => path.startsWith(prefix)), "path not allowed");

type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };
const jsonValueSchema: z.ZodType<JsonValue> = z.lazy(() =>
  z.union([
    z.string(),
    z.number().finite(),
    z.boolean(),
    z.null(),
    z.array(jsonValueSchema),
    z.record(jsonValueSchema),
  ]),
);

export const finoraRequestSchema = z
  .object({
    method: z.enum(["GET", "POST"]),
    path: requestPathSchema,
    query: z.record(z.union([QUERY_VALUE, z.array(QUERY_VALUE).max(100)])).optional(),
    body: jsonValueSchema.optional(),
    timeoutMs: z.number().int().min(1000).max(60000).optional(),
  })
  .strict();

export type FinoraRequest = z.infer<typeof finoraRequestSchema>;

export const MAX_UPLOAD_BYTES = 8 * 1024 * 1024;
export const MAX_TOTAL_UPLOAD_BYTES = 32 * 1024 * 1024;
const formFileSchema = z
  .object({
    field: z.string().regex(/^[a-z_][a-z_0-9]{0,39}$/),
    name: z.string().max(200),
    type: z.enum([
      "image/png",
      "image/jpeg",
      "image/webp",
      "image/gif",
      "application/pdf",
      // catalogue imports (supplier lists)
      "text/csv",
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ]),
    data: z.instanceof(Uint8Array).refine((bytes) => bytes.byteLength <= MAX_UPLOAD_BYTES, "file too large"),
  })
  .strict();

/** Multipart POST for FINORA forms that accept files (product images). */
export const finoraFormSchema = z
  .object({
    path: requestPathSchema,
    fields: z.array(z.tuple([z.string().max(80), z.string().max(20_000)])).max(200),
    file: formFileSchema.optional(),
    files: z.array(formFileSchema).max(40).optional(),
    timeoutMs: z.number().int().min(1000).max(120_000).optional(),
  })
  .strict()
  .superRefine((request, ctx) => {
    const files = [...(request.file ? [request.file] : []), ...(request.files ?? [])];
    if (files.reduce((total, file) => total + file.data.byteLength, 0) > MAX_TOTAL_UPLOAD_BYTES)
      ctx.addIssue({ code: z.ZodIssueCode.custom, message: "uploads too large" });
    if (new Set(files.map((file) => file.field)).size !== files.length)
      ctx.addIssue({ code: z.ZodIssueCode.custom, message: "duplicate file field" });
  });
export type FinoraFormRequest = z.infer<typeof finoraFormSchema>;

export type FinoraTransportFailure =
  | "not_configured"
  | "network"
  | "timeout"
  | "unauthenticated"
  | "password_change_required"
  | "invalid_response"
  | "refused";

export type FinoraResponse =
  | {
      ok: true;
      status: number;
      data: unknown;
      source?: "offline";
      cachedAt?: number;
      customerCommandScope?: string;
      auditCommandScope?: string;
      auditCommandPath?: string;
    }
  | { ok: false; failure: "http"; status: number; data: unknown }
  | { ok: false; failure: FinoraTransportFailure; status?: number; detail?: string };

/** Server address the operator typed: http(s) origin only, no credentials, path or query. */
export const serverUrlSchema = z
  .string()
  .trim()
  .max(200)
  .transform((value, ctx) => {
    let url: URL;
    try {
      url = new URL(value);
    } catch {
      ctx.addIssue({ code: z.ZodIssueCode.custom, message: "invalid url" });
      return z.NEVER;
    }
    if (url.protocol !== "http:" && url.protocol !== "https:") {
      ctx.addIssue({ code: z.ZodIssueCode.custom, message: "http or https only" });
      return z.NEVER;
    }
    if (url.username || url.password || url.search || url.hash || (url.pathname && url.pathname !== "/")) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, message: "origin only" });
      return z.NEVER;
    }
    return url.origin;
  });

export const rememberIdentitySchema = z
  .object({
    tenantSlug: z
      .string()
      .trim()
      .toLowerCase()
      .regex(/^[a-z0-9][a-z0-9_-]{0,62}$/),
    username: z.string().trim().min(1).max(120),
  })
  .strict();

/** FINORA print pages the desktop may open (loaded in a sandboxed window on the FINORA session). */
export const printRequestSchema = z.discriminatedUnion("kind", [
  z
    .object({
      kind: z.literal("stock_document"),
      ledger: z.enum(["branch", "warehouse"]),
      document: z.enum(["transfers", "writeoffs"]),
      id: z.number().int().positive().safe(),
    })
    .strict(),
  z
    .object({
      kind: z.literal("inventory_activity"),
      q: z.string().max(150).optional(),
      branch_id: z.number().int().positive().optional(),
      product_id: z.number().int().positive().optional(),
      direction: z.enum(["in", "out"]).optional(),
      from: z
        .string()
        .regex(/^\d{4}-\d{2}-\d{2}$/)
        .optional(),
      to: z
        .string()
        .regex(/^\d{4}-\d{2}-\d{2}$/)
        .optional(),
    })
    .strict(),
  z
    .object({
      kind: z.literal("finance_report"),
      report: z.enum([
        "trial-balance",
        "profit-loss",
        "balance-sheet",
        "cash-flow",
        "customer-aging",
        "supplier-aging",
        "instalments",
        "employee-advances",
        "reconciliation-differences",
      ]),
      date_from: z
        .string()
        .regex(/^\d{4}-\d{2}-\d{2}$/)
        .optional(),
      date_to: z
        .string()
        .regex(/^\d{4}-\d{2}-\d{2}$/)
        .optional(),
    })
    .strict(),
  z.object({ kind: z.literal("finance_voucher"), id: z.number().int().positive() }).strict(),
  z.object({ kind: z.literal("finance_loan"), id: z.number().int().positive() }).strict(),
  z.object({ kind: z.literal("finance_cash_shift"), id: z.number().int().positive() }).strict(),
  z
    .object({ kind: z.literal("financial_control_snapshot"), id: z.number().int().positive().safe() })
    .strict(),
  z
    .object({
      kind: z.literal("financial_control_comparison"),
      start: z.number().int().positive().safe(),
      end: z.number().int().positive().safe(),
    })
    .strict(),
  z.object({ kind: z.literal("orders"), ids: z.array(z.number().int().positive()).min(1).max(500) }).strict(),
  z.object({ kind: z.literal("purchase"), id: z.number().int().positive() }).strict(),
  z.object({ kind: z.literal("supplier"), id: z.number().int().positive() }).strict(),
  z.object({ kind: z.literal("customer_statement"), id: z.number().int().positive() }).strict(),
  z.object({ kind: z.literal("customer_transactions"), id: z.number().int().positive() }).strict(),
  z.object({ kind: z.literal("shipping_receipt"), id: z.number().int().positive() }).strict(),
  z
    .object({
      kind: z.literal("customer_history"),
      id: z.number().int().positive(),
      date_from: z
        .string()
        .regex(/^\d{4}-\d{2}-\d{2}$/)
        .optional(),
      date_to: z
        .string()
        .regex(/^\d{4}-\d{2}-\d{2}$/)
        .optional(),
    })
    .strict(),
]);
export type PrintRequest = z.infer<typeof printRequestSchema>;

export function printPath(request: PrintRequest): string {
  if (request.kind === "stock_document")
    return `/api/v1/desktop/stock-operations/${request.ledger}/${request.document}/${request.id}/print`;
  if (request.kind === "inventory_activity") {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(request))
      if (key !== "kind" && value !== undefined) params.set(key, String(value));
    return `/api/v1/desktop/inventory-activity/print${params.size ? `?${params}` : ""}`;
  }
  if (request.kind === "finance_report") {
    const q = new URLSearchParams();
    if (request.date_from) q.set("date_from", request.date_from);
    if (request.date_to) q.set("date_to", request.date_to);
    return `/accounts/finance/reports/${request.report}/print?${q}`;
  }
  if (request.kind === "finance_voucher") return `/accounts/finance/vouchers/${request.id}/print`;
  if (request.kind === "finance_cash_shift") return `/accounts/finance/cash-shifts/${request.id}/print`;
  if (request.kind === "financial_control_snapshot")
    return `/accounts/finance/control/snapshots/${request.id}/print`;
  if (request.kind === "financial_control_comparison")
    return `/accounts/finance/control/compare/print?start=${request.start}&end=${request.end}`;
  if (request.kind === "finance_loan") return `/accounts/finance/loans/${request.id}/print`;
  if (request.kind === "supplier") return `/suppliers/statement/print/${request.id}`;
  if (request.kind === "customer_statement") return `/api/v1/desktop/customers/${request.id}/statement/print`;
  if (request.kind === "customer_history") {
    const dates = new URLSearchParams();
    if (request.date_from) dates.set("date_from", request.date_from);
    if (request.date_to) dates.set("date_to", request.date_to);
    return `/api/v1/desktop/customers/${request.id}/account-history/print${dates.size ? `?${dates}` : ""}`;
  }
  if (request.kind === "shipping_receipt")
    return `/api/v1/desktop/shipping-center/receipts/${request.id}/print`;
  if (request.kind === "customer_transactions")
    return `/api/v1/desktop/customers/${request.id}/transactions/print`;
  return request.kind === "orders"
    ? `/orders/print-invoices?ids=${request.ids.join(",")}`
    : `/purchases/print/${request.id}`;
}

/** Reports (FINORA services/reports_service.py): print / PDF / Excel of one section with its filters. */
export const REPORT_SECTIONS = [
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
] as const;
export type ReportSection = (typeof REPORT_SECTIONS)[number];

const isoDate = z.string().regex(/^\d{4}-\d{2}-\d{2}$/);
const viewKey = z.string().regex(/^[a-z_]{1,20}$/);
export const reportQuerySchema = z
  .object({
    period: z.enum(["today", "yesterday", "this_week", "this_month", "last_month", "this_year", "custom"]),
    date_from: isoDate.optional(),
    date_to: isoDate.optional(),
    branch_id: z.number().int().positive().optional(),
    employee_id: z.number().int().positive().optional(),
    audit_id: z.number().int().positive().optional(),
    tab: viewKey.optional(),
    state: viewKey.optional(),
    by: viewKey.optional(),
    sort: viewKey.optional(),
    grain: viewKey.optional(),
    month: z
      .string()
      .regex(/^\d{4}-\d{2}$/)
      .optional(),
    date: isoDate.optional(),
    person_id: z.number().int().positive().optional(),
    department_id: z.number().int().positive().optional(),
    status: viewKey.optional(),
    search: z.string().max(80).optional(),
  })
  .strict();
export type ReportQuery = z.infer<typeof reportQuerySchema>;

export const reportExportSchema = z
  .object({
    section: z.enum([
      ...REPORT_SECTIONS,
      "hr_employees",
      "hr_attendance",
      "hr_payroll",
      "hr_advances",
      "hr_commissions",
      "hr_leave",
      "hr_resources",
      "hr_settlement",
      "hr_statement",
      "inventory_audit",
    ]),
    format: z.enum(["print", "pdf", "xlsx"]),
    title: z.string().min(1).max(80),
    query: reportQuerySchema,
  })
  .strict();
export type ReportExportRequest = z.infer<typeof reportExportSchema>;
export interface ReportExportResult {
  saved: boolean;
  path?: string;
}

export function reportExportPath(request: ReportExportRequest): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(request.query)) {
    if (value !== undefined && value !== "") params.set(key, String(value));
  }
  if (request.section === "inventory_audit") {
    if (!Number.isSafeInteger(request.query.audit_id) || Number(request.query.audit_id) <= 0)
      throw Error("معرف تقرير الجرد غير صالح");
    return `/api/v1/desktop/inventory-audits/${request.query.audit_id}/${request.format === "xlsx" ? "xlsx" : "print"}`;
  }
  const base = request.section.startsWith("hr_")
    ? `/hr/api/reports/${request.section.slice(3)}/${request.format === "xlsx" ? "xlsx" : "print"}`
    : request.format === "xlsx"
      ? `/reports/api/v2/export/${request.section}.xlsx`
      : `/reports/api/v2/print/${request.section}`;
  return `${base}?${params.toString()}`;
}

/** Web pages the desktop hands over to the browser (full editors that live in FINORA web). */
export const finoraPagePathSchema = z
  .string()
  .regex(
    /^\/(orders\/\d+|purchases\/edit\/\d+|inventory\/report\/\d+|inventory\/transfers\/\d+|wholesale\/transfers|inventory\/smart-audit(?:\?session=[1-9]\d{0,14})?|inventory\/|purchases\/new|customers\/orders\/\d+|suppliers\/\d+|employees\/view-orders\/\d+)$/,
  );

/** Product images are proxied by main through the FINORA session (same-server paths only). */
export const MEDIA_SCHEME = "finora-media";
export const mediaPathSchema = z
  .string()
  .max(400)
  .regex(/^\/(static|uploads|media)\/[A-Za-z0-9\-._~/%]+\.(png|jpe?g|webp|gif|avif)$/i)
  .refine((path) => !path.includes("..") && !path.includes("//"), "path traversal");

export interface DesktopConfig {
  serverUrl: string | null;
  lastTenantSlug: string | null;
  lastUsername: string | null;
  appVersion: string;
}

export interface WindowState {
  maximized: boolean;
  focused: boolean;
}

export interface FinoraDesktopBridge {
  assistant?: LocalAssistantBridge;
  lifecycle?: {
    confirmLeave(): Promise<boolean>;
    activity(input: { dirty: boolean; saving: boolean }): Promise<void>;
    reload(): Promise<void>;
  };
  updates?: {
    check(): Promise<{ current: string; latest: string; available: boolean; size: number }>;
    download(): Promise<{ ready: boolean }>;
    install(): Promise<void>;
  };
  backup?: {
    export(password: string): Promise<{ saved: boolean }>;
    restore(password: string): Promise<{ restored: boolean }>;
  };
  customerRecovery?: CustomerRecoveryBridge;
  stockRecovery?: CustomerRecoveryBridge;
  offline?: OfflineBridge;
  window: {
    minimize(): Promise<void>;
    toggleMaximize(): Promise<WindowState>;
    close(): Promise<void>;
    getState(): Promise<WindowState>;
    onState(listener: (state: WindowState) => void): () => void;
  };
  finora: {
    request(request: FinoraRequest): Promise<FinoraResponse>;
    submitForm(request: FinoraFormRequest): Promise<FinoraResponse>;
    clearSession(): Promise<void>;
  };
  print: {
    open(request: PrintRequest): Promise<void>;
  };
  reports: {
    export(request: ReportExportRequest): Promise<ReportExportResult>;
  };
  app: {
    openInFinora(path: string): Promise<void>;
    /** Whether the app starts with Windows (per-user login item). */
    getAutoStart(): Promise<boolean>;
    setAutoStart(enabled: boolean): Promise<boolean>;
  };
  config: {
    get(): Promise<DesktopConfig>;
    setServer(serverUrl: string): Promise<DesktopConfig>;
    rememberIdentity(identity: { tenantSlug: string; username: string }): Promise<DesktopConfig>;
  };
}
