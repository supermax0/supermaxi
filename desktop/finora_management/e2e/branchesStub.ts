/** Branches & warehouses stub — mirrors modules/desktop_api/branches.py response shapes. */
import type { IncomingMessage, ServerResponse } from "node:http";

const BASE = "/api/v1/desktop/branches";
type Send = (res: ServerResponse, status: number, body: unknown) => void;

interface StubBranch {
  id: number;
  code: string;
  name: string;
  address: string;
  phone: string;
  is_active: boolean;
  is_default: boolean;
  created_at: string;
  short_name: string;
  branch_type: string;
  branch_type_label: string;
  governorate: string;
  city: string;
  email: string;
  manager_name: string;
  opened_on: string;
  archived_at: string;
  archive_reason: string;
}

const TYPES = [
  { id: "sales", label: "فرع مبيعات" },
  { id: "showroom", label: "معرض" },
  { id: "distribution", label: "مركز توزيع" },
  { id: "warehouse", label: "مستودع" },
  { id: "service", label: "مركز خدمة" },
  { id: "hq", label: "مقر إدارة" },
];

const base = (id: number, code: string, name: string, extra: Partial<StubBranch> = {}): StubBranch => ({
  id,
  code,
  name,
  address: "",
  phone: "",
  is_active: true,
  is_default: false,
  created_at: "2026-01-10 09:00",
  short_name: "",
  branch_type: "sales",
  branch_type_label: "فرع مبيعات",
  governorate: "",
  city: "",
  email: "",
  manager_name: "",
  opened_on: "",
  archived_at: "",
  archive_reason: "",
  ...extra,
});

const BRANCHES: StubBranch[] = [
  base(1, "MAIN", "الفرع الرئيسي", {
    is_default: true,
    governorate: "بغداد",
    city: "الكرادة",
    manager_name: "أحمد الساعدي",
    phone: "07701112233",
  }),
  base(2, "MNS", "فرع المنصور", {
    branch_type: "showroom",
    branch_type_label: "معرض",
    governorate: "بغداد",
    city: "المنصور",
    manager_name: "سارة كاظم",
  }),
  base(3, "BSR", "فرع البصرة", { governorate: "البصرة", city: "العشار", manager_name: "حيدر جاسم" }),
];

const STATS: Record<number, object> = {
  1: {
    sales_total: 18_450_000,
    orders: 142,
    open_orders: 11,
    stock_value: 9_800_000,
    cash: 6_250_000,
    last_activity: "2026-10-15 17:20",
  },
  2: {
    sales_total: 7_320_000,
    orders: 61,
    open_orders: 4,
    stock_value: 3_100_000,
    cash: 1_480_000,
    last_activity: "2026-10-15 15:05",
  },
  3: {
    sales_total: 2_090_000,
    orders: 18,
    open_orders: 1,
    stock_value: 1_250_000,
    cash: null,
    last_activity: "2026-10-14 12:40",
  },
};

let enabled = true;
let scope: { current: number; viewAll: boolean } = { current: 1, viewAll: true };

export function configureBranchesStub(options: { enabled: boolean }) {
  enabled = options.enabled;
}

const CASH_BASE = "/api/v1/desktop/branch-cash";
interface StubCash {
  id: number;
  status: "pending" | "approved" | "completed" | "rejected" | "cancelled";
  amount: number;
  reason: string;
  events: Array<{ action: string; name: string; at: string; reason?: string }>;
}
const CASH: StubCash[] = [
  {
    id: 1,
    status: "approved",
    amount: 750_000,
    reason: "تغذية صندوق فرع المنصور",
    events: [
      { action: "create", name: "سارة", at: "2026-10-16 09:10" },
      { action: "approve", name: "المدير", at: "2026-10-16 09:40" },
    ],
  },
  {
    id: 2,
    status: "completed",
    amount: 250_000,
    reason: "تسوية مبيعات الأسبوع",
    events: [
      { action: "create", name: "حيدر", at: "2026-10-14 11:00" },
      { action: "approve", name: "المدير", at: "2026-10-14 11:30" },
      { action: "receive", name: "سارة", at: "2026-10-14 15:00" },
    ],
  },
];
const LABELS: Record<StubCash["status"], string> = {
  pending: "بانتظار الاعتماد",
  approved: "معتمد — بانتظار تأكيد الاستلام",
  completed: "مكتمل",
  rejected: "مرفوض",
  cancelled: "ملغى",
};
const cashRow = (c: StubCash) => ({
  id: c.id,
  number: `BCT-20261016-000${c.id}`,
  status: c.status,
  status_label: LABELS[c.status],
  amount: c.amount,
  currency: "IQD",
  from_account: "صندوق الفرع الرئيسي",
  to_account: "صندوق فرع المنصور",
  from_branch: "الفرع الرئيسي",
  to_branch: "فرع المنصور",
  from_branch_id: 1,
  to_branch_id: 2,
  transfer_date: "2026-10-16",
  reference: "",
  reason: c.reason,
  notes: "",
  requested_by: "سارة",
  approved_by: c.status === "pending" ? "" : "المدير",
  received_by: c.status === "completed" ? "سارة" : "",
  closed_reason: "",
  created_at: "2026-10-16 09:10",
  completed_at: c.status === "completed" ? "2026-10-16 15:00" : "",
  posted: c.status === "completed",
  events: c.events,
  can_approve: c.status === "pending",
  can_receive: c.status === "approved",
  can_reject: c.status === "pending" || c.status === "approved",
  can_cancel: c.status === "pending" || c.status === "approved",
});

async function handleCash(
  req: IncomingMessage,
  res: ServerResponse,
  path: string,
  url: URL,
  send: Send,
  readJson: (req: IncomingMessage) => Promise<unknown>,
): Promise<boolean> {
  const sub = path.slice(CASH_BASE.length);
  const body = (req.method === "POST" ? await readJson(req) : {}) as Record<string, unknown>;
  const ok = (data: Record<string, unknown>) => {
    send(res, 200, { ok: true, ...data });
    return true;
  };
  const pending = () => {
    const open = CASH.filter((c) => c.status === "pending" || c.status === "approved");
    return { count: open.length, amount: open.reduce((s, c) => s + c.amount, 0) };
  };
  if (sub === "/meta")
    return ok({
      accounts: [
        {
          id: 10,
          name: "صندوق الفرع الرئيسي",
          type: "cash",
          branch_id: 1,
          branch_name: "الفرع الرئيسي",
          can_send_from: true,
          balance: 6_250_000,
        },
        {
          id: 20,
          name: "صندوق فرع المنصور",
          type: "cash",
          branch_id: 2,
          branch_name: "فرع المنصور",
          can_send_from: true,
          balance: 1_480_000,
        },
      ],
      can_execute_now: true,
      pending: pending(),
    });
  if (sub === "" && req.method === "GET") {
    const status = url.searchParams.get("status") ?? "open";
    const rows = CASH.filter((c) =>
      status === "open" ? c.status === "pending" || c.status === "approved" : c.status === status,
    );
    return ok({ rows: rows.map(cashRow).reverse(), pending: pending() });
  }
  if (sub === "" && req.method === "POST") {
    const created: StubCash = {
      id: CASH.length + 1,
      status: "pending",
      amount: Number(body.amount ?? 0),
      reason: String(body.reason ?? ""),
      events: [{ action: "create", name: "المدير", at: "2026-10-16 16:00" }],
    };
    CASH.push(created);
    return ok({ transfer: cashRow(created) });
  }
  const match = /^\/(\d+)\/(approve|receive|reject|cancel)$/.exec(sub);
  const doc = match ? CASH.find((c) => c.id === Number(match[1])) : undefined;
  if (!match || !doc) {
    send(res, 404, { ok: false, error: "التحويل غير موجود" });
    return true;
  }
  const next = {
    approve: "approved",
    receive: "completed",
    reject: "rejected",
    cancel: "cancelled",
  } as const;
  doc.status = next[match[2] as keyof typeof next];
  doc.events.push({ action: match[2] ?? "", name: "المدير", at: "2026-10-16 16:05" });
  return ok({ transfer: cashRow(doc) });
}

export async function handleBranches(
  req: IncomingMessage,
  res: ServerResponse,
  path: string,
  url: URL,
  send: Send,
  readJson: (req: IncomingMessage) => Promise<unknown>,
): Promise<boolean> {
  if (path.startsWith(CASH_BASE)) return handleCash(req, res, path, url, send, readJson);
  if (!path.startsWith(BASE)) return false;
  const sub = path.slice(BASE.length);
  const body = (req.method === "POST" ? await readJson(req) : {}) as Record<string, unknown>;
  const ok = (data: Record<string, unknown>) => {
    send(res, 200, { ok: true, ...data });
    return true;
  };
  const state = () => ({
    enabled,
    explicit: true,
    active_branches: BRANCHES.filter((b) => b.is_active).length,
  });
  const withStats = (b: StubBranch) => ({ ...b, stats: STATS[b.id] ?? null });

  if (sub === "/meta")
    return ok({
      multi_branch: state(),
      primary_branch_id: 1,
      can_manage: true,
      types: TYPES,
      current_branch_id: scope.current,
      scope: {
        can_switch: true,
        view_all: scope.viewAll,
        branches: BRANCHES.filter((b) => b.is_active).map((b) => ({
          id: b.id,
          name: b.name,
          code: b.code,
          is_default: b.is_default,
        })),
      },
    });
  if (sub === "/switch") {
    if (body.view_all) scope = { current: scope.current, viewAll: true };
    else scope = { current: Number(body.branch_id), viewAll: false };
    return ok({});
  }
  if (sub === "/feature") {
    enabled = Boolean(body.enabled);
    return ok({ multi_branch: state() });
  }
  if (sub === "" && req.method === "GET") {
    const archived = url.searchParams.get("archived") === "1";
    return ok({
      rows: BRANCHES.filter((b) => archived || b.is_active).map(withStats),
      multi_branch: state(),
      pending_transfers: {
        stock: 2,
        cash: CASH.filter((c) => c.status === "pending" || c.status === "approved").length,
        cash_amount: 750_000,
      },
    });
  }
  if (sub === "" && req.method === "POST") {
    const created = base(
      BRANCHES.length + 1,
      String(body.code ?? "").toUpperCase(),
      String(body.name ?? ""),
      {
        branch_type: String(body.branch_type ?? "sales"),
        branch_type_label: TYPES.find((t) => t.id === body.branch_type)?.label ?? "فرع مبيعات",
        governorate: String(body.governorate ?? ""),
        city: String(body.city ?? ""),
        manager_name: String(body.manager_name ?? ""),
      },
    );
    BRANCHES.push(created);
    STATS[created.id] = {
      sales_total: 0,
      orders: 0,
      open_orders: 0,
      stock_value: 0,
      cash: 0,
      last_activity: "",
    };
    return ok({ branch: withStats(created) });
  }
  const match = /^\/(\d+)(\/update|\/archive)?$/.exec(sub);
  if (match) {
    const branch = BRANCHES.find((b) => b.id === Number(match[1]));
    if (!branch) {
      send(res, 404, { ok: false, error: "الفرع غير موجود" });
      return true;
    }
    if (match[2] === "/archive") {
      if (body.restore) {
        branch.is_active = true;
      } else {
        branch.is_active = false;
        branch.archived_at = "2026-10-15 18:00";
      }
    } else if (match[2] === "/update") {
      Object.assign(branch, body);
    }
    return ok(match[2] ? { branch: withStats(branch) } : { branch: withStats(branch), blockers: [] });
  }
  send(res, 404, { ok: false, error: "not found" });
  return true;
}
