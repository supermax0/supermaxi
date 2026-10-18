/** Shipping & Logistics Center stub — mirrors modules/desktop_api/shipping_center.py response shapes. */
import type { IncomingMessage, ServerResponse } from "node:http";

const BASE = "/api/v1/desktop/shipping-center";
type Send = (res: ServerResponse, status: number, body: unknown) => void;

const CARRIERS = [
  { id: 1, name: "النقل السريع", phone: "07701112233", price: 5000 },
  { id: 3, name: "شركة البرق", phone: "07809998877", price: 4000 },
  { id: 4, name: "الوسيط للتوصيل", phone: "07501231234", price: 6000 },
];
const NAMES = [
  "علي حسين",
  "زينب كاظم",
  "مصطفى جاسم",
  "نور الهدى",
  "حسن عباس",
  "سارة محمد",
  "أحمد قاسم",
  "مريم علي",
  "حيدر سلمان",
  "رقية فاضل",
  "كرار عادل",
  "هدى جبار",
];
const CITIES = ["بغداد", "البصرة", "أربيل", "النجف", "كربلاء", "الحلة"];

const ORDERS = Array.from({ length: 36 }, (_, i) => {
  const id = 1201 + i;
  const remaining = [45000, 62000, 38000, 120000, 75000, 54000][i % 6] ?? 50000;
  return {
    id,
    customer_name: NAMES[i % NAMES.length] ?? "",
    customer_phone: `0770${String(1000000 + i * 7919).slice(0, 7)}`,
    customer_city: CITIES[i % CITIES.length] ?? "",
    customer_address: "حي الجامعة",
    total: remaining,
    paid_amount: 0,
    remaining,
    status: "جاري الشحن",
    shipping_status: "",
    payment_status: "غير مدفوع",
    shipping_company_id: 1,
    shipping_company: "النقل السريع",
    delivery_agent_id: null,
    delivery_agent: "",
    waybills: [`QX${880100 + i}`],
    fee: 5000,
    fee_due: 5000,
    created_at: "2026-10-12T11:20:00",
  };
});

const stats = (count: number, amount: number) => ({ count, amount });
const DUES = [3_389_000, 1_020_000, 406_000];
const STATS = {
  total: stats(184, 11_240_000),
  transit: stats(36, 2_484_000),
  delivered_unsettled: stats(14, 905_000),
  due: stats(50, 3_389_000),
  returned: stats(9, 0),
};

interface Manifest {
  id: number;
  number: string;
  kind: "settlement" | "handover" | "agent";
  carrier_id: number;
  reference: string;
  date: string;
  rows: number[];
  selections: Record<string, string>;
  executed: boolean;
  received?: number;
}

const manifests: Manifest[] = [
  {
    id: 31,
    number: "KSH-20261012-0007",
    kind: "handover",
    carrier_id: 1,
    reference: "",
    date: "2026-10-12",
    rows: ORDERS.map((o) => o.id),
    selections: {},
    executed: false,
  },
  {
    id: 29,
    number: "STL-20261008-0003",
    kind: "settlement",
    carrier_id: 3,
    reference: "BRQ-551",
    date: "2026-10-08",
    rows: [],
    selections: {},
    executed: true,
    received: 1_310_000,
  },
];
let sequence = 1;

const RECEIPTS = [
  {
    id: 88,
    number: "RCV-SHP-20261008-0001",
    party_type: "carrier" as const,
    party_id: 3,
    party_name: "شركة البرق",
    amount: 1_010_000,
    payment_method: "cash",
    treasury_account: "الصندوق الرئيسي",
    date: "2026-10-08",
    reference: "BRQ-551",
    notes: "تسوية كشف STL-20261008-0003",
    status: "معتمد",
    balance_before: 1_310_000,
    balance_after: 300_000,
    created_by: "admin",
    allocations: [
      { order_id: 1102, label: "#1102", amount: 62_000 },
      { order_id: 1105, label: "#1105", amount: 120_000 },
    ],
  },
];
const SETTINGS = {
  price: 5000,
  return_fee: 3000,
  settlement_cycle: "weekly",
  payment_method: "cash",
  treasury_account_id: null as number | null,
  notes: "التسديد كل خميس",
  updated_by: "admin",
  updated_at: "2026-10-10 10:00",
};
const BRANCHES = [{ id: 1, name: "الفرع الرئيسي" }];
const RETURN_ITEMS = [
  { item_id: 501, product_id: 11, name: "سماعة لاسلكية", variant: "أسود", quantity: 2 },
  { item_id: 502, product_id: 12, name: "شاحن سريع", variant: "", quantity: 1 },
];
const RETURNS = [1219, 1224, 1230].map((orderId, i) => ({
  id: 70 + i,
  order_id: orderId,
  state: (i === 2 ? "received" : "awaiting") as "awaiting" | "received" | "closed",
  manifest_id: 29,
  manifest_number: "STL-20261008-0003",
  party_type: "carrier",
  party_id: 1,
  party_name: "النقل السريع",
  order_amount: [62_000, 45_000, 120_000][i] ?? 0,
  customer_name: ["علي حسين", "سارة محمد", "حيدر سلمان"][i] ?? "",
  customer_city: "بغداد",
  order_status: "جاري الشحن",
  waybills: [`QX88011${i}`],
  reported_at: "2026-10-08 14:10",
  received_at: i === 2 ? "2026-10-14 09:30" : "",
  received_by: i === 2 ? "المحاسب" : "",
  closed_at: "",
  closed_by: "",
  branch_id: null,
  packaging_ok: null,
  inspection: [],
  writeoffs: [] as string[],
  note: "",
}));

function build(m: Manifest) {
  const rows = m.rows.flatMap((id) => {
    const o = ORDERS.find((x) => x.id === id);
    return o ? [{ ...o, selection: m.selections[String(id)] ?? "" }] : [];
  });
  const by = (s: string) => rows.filter((r) => r.selection === s);
  const delivered = by("واصل");
  const amount = delivered.reduce((s, r) => s + r.remaining, 0);
  const fee = delivered.reduce((s, r) => s + r.fee, 0);
  const unclassified = rows.filter((r) => !r.selection);
  const issues = [
    ...(rows.some((r) => r.id === 1203)
      ? [
          {
            severity: "warning",
            code: "status_mismatch",
            order_id: 1203,
            message: "الطلب 1203 حالته «جاري الشحن» لكن شركة النقل أبلغت عنه قبل يومين فقط",
          },
        ]
      : []),
    ...by("مشكلة").map((r) => ({
      severity: "error",
      code: "problem",
      order_id: r.id,
      message: `الطلب ${r.id} معلّم كمشكلة — عالجه قبل الاعتماد`,
    })),
  ];
  const blocking = [
    ...unclassified.map((r) => ({
      severity: "error",
      code: "unclassified",
      order_id: r.id,
      message: `الطلب ${r.id} غير مصنف`,
    })),
    ...issues.filter((i) => i.severity === "error"),
    ...(rows.length === 0
      ? [{ severity: "error", code: "empty", order_id: null, message: "الكشف فارغ" }]
      : []),
  ];
  const carrier = CARRIERS.find((c) => c.id === m.carrier_id);
  return {
    id: m.id,
    number: m.number,
    kind: m.kind,
    carrier_id: m.carrier_id,
    carrier: carrier?.name ?? "",
    agent: "",
    orders_count: m.kind === "settlement" && m.executed && rows.length === 0 ? 21 : rows.length,
    total_amount: m.executed && m.received ? m.received : rows.reduce((s, r) => s + r.remaining, 0),
    executed: m.executed,
    created_at: `${m.date}T10:15:00`,
    created_by: "المحاسب",
    reference: m.reference,
    breakdown: {},
    meta: {
      reference: m.reference,
      date: m.date,
      ...(m.received ? { received_amount: m.received, approved_by: "admin", approved_at: m.date } : {}),
    },
    selections: { ...m.selections },
    rows,
    issues,
    blocking,
    totals: {
      delivered: { count: delivered.length, amount, fee },
      returned: stats(by("راجع").length, 0),
      postponed: stats(by("مؤجل").length, 0),
      problem: stats(by("مشكلة").length, 0),
      unclassified: stats(unclassified.length, 0),
    },
    expected_net: amount - fee,
    ready: rows.length > 0 && blocking.length === 0,
  };
}

const summary = (m: Manifest) => {
  const full: Record<string, unknown> = build(m);
  return Object.fromEntries(
    Object.entries(full).filter(
      ([k]) =>
        !["meta", "selections", "rows", "issues", "blocking", "totals", "expected_net", "ready"].includes(k),
    ),
  );
};

/** Returns true when the request was a shipping-center call and has been answered. */
export async function handleShipping(
  req: IncomingMessage,
  res: ServerResponse,
  path: string,
  url: URL,
  send: Send,
  readJson: (req: IncomingMessage) => Promise<unknown>,
): Promise<boolean> {
  if (!path.startsWith(BASE)) return false;
  const sub = path.slice(BASE.length);
  const body = (req.method === "POST" ? await readJson(req) : {}) as Record<string, unknown>;
  const ok = (data: Record<string, unknown>) => {
    send(res, 200, { ok: true, ...data });
    return true;
  };
  if (sub === "/meta")
    return ok({
      carriers: CARRIERS,
      agents: [{ id: 2, name: "مندوب علي", phone: "07712345678", carrier_id: 1 }],
      treasury_accounts: [
        { id: 4, name: "الصندوق الرئيسي", is_default: true },
        { id: 5, name: "مصرف الرافدين", is_default: false },
      ],
      can_approve: true,
      can_manage: true,
    });
  if (sub === "/overview")
    return ok({
      cards: {
        in_transit: { count: 87 },
        delivered_unsettled: stats(23, 1_642_000),
        carriers_due: stats(64, 4_815_000),
        agents_due: stats(11, 690_000),
        returns: { count: 17 },
        open_manifests: { count: manifests.filter((m) => !m.executed).length, flagged: 2 },
      },
    });
  if (sub === "/carriers")
    return ok({
      rows: CARRIERS.map((c, i) => ({
        ...c,
        notes: "",
        opening_balance: 0,
        stats: { ...STATS, due: stats(50 - i * 14, DUES[i] ?? 0) },
        due: DUES[i] ?? 0,
        open_manifests: manifests.filter((m) => m.carrier_id === c.id && !m.executed).length,
      })),
    });
  const carrierMatch = /^\/carriers\/(\d+)$/.exec(sub);
  if (carrierMatch) {
    const c = CARRIERS.find((x) => x.id === Number(carrierMatch[1]));
    if (!c) {
      send(res, 404, { ok: false, error: "not found" });
      return true;
    }
    return ok({
      carrier: { ...c, notes: "" },
      stats: STATS,
      received_total: 7_850_000,
      manifests: manifests.filter((m) => m.carrier_id === c.id).map(summary),
      statement: [
        {
          id: 1,
          date: "2026-10-08",
          invoice_id: null,
          action: "settlement",
          amount: 1_310_000,
          note: "تسوية STL-20261008-0003",
        },
        { id: 2, date: "2026-10-01", invoice_id: 1102, action: "payment", amount: 62_000, note: "تحصيل طلب" },
      ],
    });
  }
  if (/^\/(carriers|agents)\/\d+\/orders$/.test(sub)) {
    const rows =
      url.searchParams.get("bucket") === "returned"
        ? ORDERS.slice(0, 3).map((o) => ({ ...o, status: "راجع" }))
        : ORDERS.slice(0, 12);
    return ok({ rows, page: 1, page_size: 25, total: rows.length, total_pages: 1 });
  }
  if (sub === "/agents")
    return ok({
      rows: [
        {
          id: 2,
          name: "مندوب علي",
          phone: "07712345678",
          active: true,
          carrier: "النقل السريع",
          has_portal: true,
          stats: STATS,
        },
      ],
    });
  if (sub === "/manifests" && req.method === "POST") {
    const m: Manifest = {
      id: 40 + sequence,
      number: `STL-20261015-${String(sequence++).padStart(4, "0")}`,
      kind: "settlement",
      carrier_id: Number(body.carrier_id),
      reference: String(body.reference ?? ""),
      date: String(body.date ?? "2026-10-15"),
      rows: [],
      selections: {},
      executed: false,
    };
    manifests.unshift(m);
    return ok({ manifest: build(m) });
  }
  if (sub === "/manifests") {
    const state = url.searchParams.get("state");
    const kind = url.searchParams.get("kind");
    return ok({
      rows: manifests
        .filter((m) => (state === "open" ? !m.executed : state === "executed" ? m.executed : true))
        .filter((m) => !kind || m.kind === kind)
        .map(summary),
    });
  }
  const missingMatch = /^\/manifests\/(\d+)\/missing$/.exec(sub);
  if (missingMatch) {
    const m = manifests.find((x) => x.id === Number(missingMatch[1]));
    const rows = ORDERS.filter((o) => !m?.rows.includes(o.id))
      .slice(0, 9)
      .map((o, i) => ({ ...o, days_out: 18 - i * 2, in_manifest: i === 4 ? "STL-20261014-0002" : "" }));
    return ok({ rows, total: rows.length, amount: rows.reduce((sum, r) => sum + r.remaining, 0) });
  }
  const manifestMatch = /^\/manifests\/(\d+)(\/.*)?$/.exec(sub);
  if (manifestMatch) {
    const m = manifests.find((x) => x.id === Number(manifestMatch[1]));
    if (!m) {
      send(res, 404, { ok: false, error: "الكشف غير موجود" });
      return true;
    }
    const action = manifestMatch[2] ?? "";
    if (action === "/rows") {
      const codes = (body.codes as string[]) ?? [];
      const added: number[] = [];
      const duplicates: string[] = [];
      const missing: string[] = [];
      for (const code of codes) {
        const o = ORDERS.find((x) => String(x.id) === code || x.waybills.includes(code));
        if (!o) missing.push(code);
        else if (m.rows.includes(o.id)) duplicates.push(code);
        else {
          m.rows.push(o.id);
          added.push(o.id);
        }
      }
      return ok({ manifest: build(m), added, duplicates, missing });
    }
    const remove = /^\/rows\/(\d+)\/remove$/.exec(action);
    if (remove) {
      m.rows = m.rows.filter((id) => id !== Number(remove[1]));
      return ok({ manifest: build(m) });
    }
    if (action === "/selections") {
      for (const [id, value] of Object.entries((body.selections as Record<string, string>) ?? {})) {
        m.selections[id] = value;
      }
      return ok({ manifest: build(m) });
    }
    if (action === "/approve") {
      const built = build(m);
      const allocations = body.allocations as Record<string, number> | undefined;
      const expected = allocations
        ? Object.values(allocations).reduce((sum, a) => sum + a, 0) -
          Object.values(allocations).filter((a) => a > 0).length * 5000
        : built.expected_net;
      if (Number(body.received_amount) !== expected) {
        send(res, 409, { ok: false, error: "المبلغ المستلم لا يطابق الصافي المتوقع" });
        return true;
      }
      m.executed = true;
      m.received = Number(body.received_amount);
      RECEIPTS.unshift({
        ...RECEIPTS[0],
        id: 90 + RECEIPTS.length,
        number: `RCV-SHP-20261015-000${RECEIPTS.length + 1}`,
        amount: m.received,
        notes: `تسوية كشف ${m.number}`,
        reference: m.reference,
      } as (typeof RECEIPTS)[number]);
      return ok({ manifest: build(m), result: {} });
    }
    return ok({ manifest: build(m) });
  }
  if (/^\/(carriers|agents)\/\d+\/statement$/.test(sub)) {
    const lines = [
      {
        date: "2026-10-08 14:10",
        manifest_id: 29,
        manifest_number: "STL-20261008-0003",
        label: "تحصيل 21 طلب واصل",
        debit: 1_415_000,
        credit: 0,
        balance: 1_415_000,
      },
      {
        date: "2026-10-08 14:10",
        manifest_id: 29,
        manifest_number: "STL-20261008-0003",
        label: "أجور النقل",
        debit: 0,
        credit: 105_000,
        balance: 1_310_000,
      },
      {
        date: "2026-10-08 14:10",
        manifest_id: 29,
        manifest_number: "STL-20261008-0003",
        label: "سند قبض RCV-SHP-20261008-0001",
        debit: 0,
        credit: 1_010_000,
        balance: 300_000,
      },
    ];
    return ok({ lines, debit: 1_415_000, credit: 1_115_000, balance: 300_000 });
  }
  if (sub === "/receipts") return ok({ rows: RECEIPTS });
  const settingsMatch = /^\/carriers\/(\d+)\/settings$/.exec(sub);
  if (settingsMatch) {
    if (req.method === "POST") Object.assign(SETTINGS, body);
    return ok({ settings: { ...SETTINGS, carrier_id: Number(settingsMatch[1]) } });
  }
  const agentMatch = /^\/agents\/(\d+)$/.exec(sub);
  if (agentMatch)
    return ok({
      agent: {
        id: 2,
        name: "مندوب علي",
        phone: "07712345678",
        active: true,
        carrier: "النقل السريع",
        has_portal: true,
      },
      stats: STATS,
      custody: {
        claimed_count: 6,
        claimed_amount: 412_000,
        settled_outstanding: 75_000,
        received_total: 1_240_000,
        in_custody: 487_000,
      },
      manifests: [],
    });
  if (/^\/agents\/\d+\/portal$/.test(sub))
    return ok({ count: 7, counts: { واصل: 6, راجع: 1 }, amount: 455_000, can_approve: true });
  if (sub === "/returns") {
    const state = url.searchParams.get("state") ?? "awaiting";
    return ok({
      rows: RETURNS.filter((r) => r.state === state),
      counts: {
        awaiting: RETURNS.filter((r) => r.state === "awaiting").length,
        received: RETURNS.filter((r) => r.state === "received").length,
        closed: RETURNS.filter((r) => r.state === "closed").length,
      },
    });
  }
  if (sub === "/returns/receive") {
    const r = RETURNS.find(
      (x) => String(x.order_id) === String(body.code) || x.id === Number(body.return_id),
    );
    if (!r) {
      send(res, 404, { ok: false, error: "لا يوجد مرتجع مفتوح بهذا الرقم" });
      return true;
    }
    r.state = "received";
    r.received_at = "2026-10-15 12:40";
    return ok({ item: { ...r, items: RETURN_ITEMS, branches: BRANCHES } });
  }
  const returnMatch = /^\/returns\/(\d+)(\/close)?$/.exec(sub);
  if (returnMatch) {
    const r = RETURNS.find((x) => x.id === Number(returnMatch[1]));
    if (!r) {
      send(res, 404, { ok: false, error: "not found" });
      return true;
    }
    if (returnMatch[2]) {
      r.state = "closed";
      r.closed_at = "2026-10-15 12:45";
      return ok({ item: { ...r, writeoffs: ["WO-7F3A21C09B12"] } });
    }
    return ok({ item: { ...r, items: RETURN_ITEMS, branches: BRANCHES }, can_writeoff: true });
  }
  if (sub === "/overdue") {
    const parcels = ORDERS.slice(20, 27).map((o, i) => ({ ...o, days_out: 21 - i * 2, in_manifest: "" }));
    return ok({
      days: Number(url.searchParams.get("days") ?? 7),
      parcels,
      returns: RETURNS.filter((r) => r.state !== "closed").map((r) => ({
        id: r.id,
        order_id: r.order_id,
        state: r.state,
        party_name: r.party_name,
        manifest_number: r.manifest_number,
        order_amount: r.order_amount,
        days: 7,
      })),
      manifests: [],
      counts: {
        parcels: parcels.length,
        returns: RETURNS.filter((r) => r.state !== "closed").length,
        manifests: 0,
      },
      amount: parcels.reduce((sum, p) => sum + p.remaining, 0),
    });
  }
  if (sub === "/lookup") {
    const codes = (body.codes as string[]) ?? [];
    const found = codes.flatMap((code) => {
      const o = ORDERS.find((x) => String(x.id) === code || x.waybills.includes(code));
      if (o) return [{ ...o, code }];
      // orders shown on the orders page (stubbed elsewhere) resolve too
      const base = ORDERS[0];
      return /^\d{5}$/.test(code) && base
        ? [
            {
              ...base,
              id: Number(code),
              code,
              status: "معباة",
              shipping_company: "",
            },
          ]
        : [];
    });
    return ok({ found, missing: codes.filter((c) => !found.some((f) => f.code === c)) });
  }
  if (sub === "/agent-report")
    return ok({
      report_id: 55,
      report_number: "AGT-2-20261015-0001",
      already_exists: false,
      message: `تم إنشاء الكشف AGT-2-20261015-0001 (${(body.order_ids as number[]).length} طلب)`,
    });
  if (sub === "/handover")
    return ok({ report_id: 32, report_number: "KSH-20261015-0001", message: "تم إنشاء كشف التسليم" });
  send(res, 404, { ok: false, error: "not found" });
  return true;
}
