import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { finora, toFinoraError } from "@/api/finora";
import type { StoreDashboard } from "@/api/finora/storeAnalytics";
import { useSession } from "@/stores/session";
import { toast } from "@/stores/toasts";
import { useWindowManager } from "@/stores/windowManager";
import { cn } from "@/utils/cn";
import { formatNumber } from "@/utils/format";
import { Metric, Panel } from "../shipping/shared";
import { supplierInput, supplierSecondary } from "../suppliers/SupplierDialogs";

const SECTION: Record<string, string> = {
  accessories: "ملحقات متوافقة",
  bought_together: "يُشترى عادة معه",
  upgrades: "خيار أفضل",
  similar: "منتجات مشابهة",
  bundles: "الباقات",
  cart: "قد تحتاج أيضاً (السلة)",
  for_you: "مقترح لك",
  after_purchase: "مكمّلات لمشترياتك",
  budget: "ضمن ميزانيتك",
};
const PAGE: Record<string, string> = {
  all: "كل الصفحات",
  home: "الرئيسية",
  category: "الأقسام",
  search: "البحث",
  product: "صفحة المنتج",
  cart: "السلة",
  checkout: "إتمام الطلب",
  compare: "المقارنة",
  other: "أخرى",
};
const pct = (v: number | null) => (v === null ? "—" : `${v}%`);
const money = (v: number) => `${formatNumber(v)} د.ع`;

/** The online store's numbers: shopping funnel, real sales, recommendation effect, unmet demand, speed. */
export function StoreAnalyticsWindow() {
  const active = useWindowManager((s) => s.active === "storeAnalytics");
  const [days, setDays] = useState(30);
  const q = useQuery({
    queryKey: ["storeAnalytics", days],
    queryFn: () => finora.storeAnalytics.dashboard(days),
    enabled: active,
  });
  const d = q.data;
  return (
    <div className="flex h-full min-h-0 flex-col p-5" dir="rtl">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <p className="flex-1 text-[12.5px] text-ink-soft">
          سلوك التسوق من زيارات المتجر (عدا من أوقف التخصيص)، والمبيعات من فواتير المتجر الفعلية. الهامش
          تقديري (السعر − الكلفة المسجلة) وليس الربح المحاسبي.
        </p>
        <label className="flex items-center gap-2 text-[13px]">
          الفترة
          <select
            aria-label="الفترة"
            className={cn(supplierInput, "w-32")}
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
          >
            <option value={7}>آخر 7 أيام</option>
            <option value={30}>آخر 30 يوماً</option>
            <option value={90}>آخر 90 يوماً</option>
          </select>
        </label>
      </div>
      {q.error && <p className="text-sm text-danger">{toFinoraError(q.error).message}</p>}
      {q.isLoading && <p className="text-sm text-ink-soft">جارٍ التحميل…</p>}
      {d && (
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto">
          <StoreSettingsPanel />
          <Overview d={d} />
          <div className="grid gap-4 lg:grid-cols-2">
            <Funnel d={d} />
            <Searches d={d} />
          </div>
          <Recommendations d={d} />
          <div className="grid gap-4 lg:grid-cols-2">
            <TopProducts d={d} />
            <Unmet d={d} />
          </div>
          <Speed d={d} />
        </div>
      )}
    </div>
  );
}

function Overview({ d }: { d: StoreDashboard }) {
  const s = d.sales;
  return (
    <Panel title="المبيعات الفعلية من المتجر">
      <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
        <Metric label="طلبات قائمة" value={formatNumber(s.orders)} />
        <Metric label="قيمة الطلبات (مع التوصيل)" value={money(s.revenue)} />
        <Metric label="متوسط قيمة الطلب" value={money(s.average_order_value)} />
        <Metric label="قطع لكل طلب" value={s.units_per_order} />
        <Metric
          label="هامش إجمالي تقديري"
          value={`${money(s.estimated_margin)} (${pct(s.estimated_margin_pct)})`}
        />
        <Metric label="معدل التحويل" value={pct(d.behaviour.conversion_rate)} />
        <Metric label="الإلغاء" value={pct(s.cancel_rate)} />
        <Metric label="الإرجاع" value={pct(s.return_rate)} />
      </div>
    </Panel>
  );
}

function Funnel({ d }: { d: StoreDashboard }) {
  const top = Math.max(1, ...d.behaviour.funnel.map((f) => f.count));
  return (
    <Panel title="مسار الشراء">
      <ol className="space-y-2" aria-label="مسار الشراء">
        {d.behaviour.funnel.map((f) => (
          <li key={f.step}>
            <div className="flex justify-between text-[13px]">
              <span>{f.step}</span>
              <b>{formatNumber(f.count)}</b>
            </div>
            <div className="mt-1 h-2 rounded-full bg-surface-sunken">
              <div className="h-2 rounded-full bg-maroon" style={{ width: `${(100 * f.count) / top}%` }} />
            </div>
          </li>
        ))}
      </ol>
      <p className="mt-3 text-[12px] text-ink-faint">
        أُزيل من السلة: {formatNumber(d.behaviour.removed_from_cart)} — كل حدث يُحسب مرة واحدة حتى مع التحديث
        أو إعادة المحاولة.
      </p>
    </Panel>
  );
}

function Searches({ d }: { d: StoreDashboard }) {
  const b = d.behaviour;
  return (
    <Panel title={`البحث — ${formatNumber(b.searches)} عملية، بلا نتائج ${pct(b.no_result_rate)}`}>
      <h4 className="mb-1 text-[12.5px] font-bold text-danger">بحثوا عنه ولم يجدوه</h4>
      {b.top_no_results.length ? (
        <ul className="mb-3 space-y-1 text-[13px]">
          {b.top_no_results.map((r) => (
            <li key={r.query} className="flex justify-between">
              <span>{r.query}</span>
              <b>{r.count}</b>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mb-3 text-[12.5px] text-ink-faint">لا يوجد.</p>
      )}
      <h4 className="mb-1 text-[12.5px] font-bold">الأكثر بحثاً</h4>
      <ul className="space-y-1 text-[13px]">
        {b.top_searches.map((r) => (
          <li key={r.query} className="flex justify-between">
            <span>{r.query}</span>
            <b>{r.count}</b>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

function Recommendations({ d }: { d: StoreDashboard }) {
  const r = d.recommendations;
  const isAdmin = useSession((s) => s.session?.user.role === "admin");
  return (
    <Panel title={`أثر التوصيات — مبيعات منسوبة ${money(r.attributed_value)}`}>
      <p className="mb-2 text-[12px] text-ink-faint">
        النقرة ليست بيعاً: تُنسب القطعة لقسم التوصيات فقط إذا نقرها الزائر نفسه هناك ثم طلبها خلال 7 أيام،
        والطلب ما زال قائماً.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-[13px]">
          <thead>
            <tr className="text-ink-faint">
              <th className="p-1.5 text-start">القسم</th>
              <th className="p-1.5 text-start">ظهور</th>
              <th className="p-1.5 text-start">نقرات</th>
              <th className="p-1.5 text-start">نسبة النقر</th>
              <th className="p-1.5 text-start">قطع مبيعة</th>
              <th className="p-1.5 text-start">قيمتها</th>
            </tr>
          </thead>
          <tbody>
            {r.sections.map((s) => (
              <tr key={s.section} className="border-t border-line/60">
                <td className="p-1.5">{SECTION[s.section] ?? s.section}</td>
                <td className="p-1.5">{formatNumber(s.views)}</td>
                <td className="p-1.5">{formatNumber(s.clicks)}</td>
                <td className="p-1.5">{pct(s.ctr)}</td>
                <td className="p-1.5">{formatNumber(s.attributed_sales)}</td>
                <td className="p-1.5">{money(s.attributed_value)}</td>
              </tr>
            ))}
            {!r.sections.length && (
              <tr>
                <td className="p-1.5 text-ink-faint" colSpan={6}>
                  لا بيانات بعد.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <Experiment d={d} canEdit={isAdmin} />
    </Panel>
  );
}

function Experiment({ d, canEdit }: { d: StoreDashboard; canEdit: boolean }) {
  const e = d.recommendations.experiment;
  const client = useQueryClient();
  const [value, setValue] = useState(String(e?.holdout_pct ?? 0));
  const save = useMutation({
    mutationFn: () => finora.storeAnalytics.setExperiment(Number(value)),
    onSuccess: async (res) => {
      toast.success(res.holdout_pct ? `تجربة التوصيات: ${res.holdout_pct}% بلا توصيات` : "أُوقفت التجربة");
      await client.invalidateQueries({ queryKey: ["storeAnalytics"] });
    },
    onError: (err) => toast.error(toFinoraError(err).message),
  });
  return (
    <div className="mt-4 rounded-control bg-surface-sunken/60 p-3 text-[13px]">
      <h4 className="mb-1 font-bold">تجربة المقارنة</h4>
      {e ? (
        <p>
          {e.holdout_pct}% من الزوار لا يرون التوصيات. تحويلهم {pct(e.holdout.conversion_rate)} (
          {formatNumber(e.holdout.sessions)} جلسة) مقابل {pct(e.exposed.conversion_rate)} لمن يراها (
          {formatNumber(e.exposed.sessions)} جلسة).{" "}
          {!e.enough_data && (
            <span className="text-ink-faint">
              البيانات غير كافية للحكم بعد (نحتاج {e.min_sessions_per_group} جلسة على الأقل في كل مجموعة).
            </span>
          )}
        </p>
      ) : (
        <p className="text-ink-faint">متوقفة: كل الزوار يرون التوصيات.</p>
      )}
      {canEdit && (
        <div className="mt-2 flex items-center gap-2">
          <label className="flex items-center gap-2">
            نسبة من لا يرى التوصيات
            <input
              aria-label="نسبة من لا يرى التوصيات"
              className={cn(supplierInput, "w-20")}
              type="number"
              min={0}
              max={50}
              value={value}
              onChange={(ev) => setValue(ev.target.value)}
            />
            %
          </label>
          <button
            type="button"
            className={supplierSecondary}
            disabled={save.isPending}
            onClick={() => save.mutate()}
          >
            حفظ
          </button>
        </div>
      )}
    </div>
  );
}

function TopProducts({ d }: { d: StoreDashboard }) {
  return (
    <Panel title="الأكثر طلباً">
      <ul className="space-y-1 text-[13px]">
        {d.sales.top_products.map((p) => (
          <li key={p.product_id} className="flex justify-between gap-2">
            <span className="truncate">{p.name}</span>
            <b>{formatNumber(p.units)} قطعة</b>
          </li>
        ))}
        {!d.sales.top_products.length && <li className="text-ink-faint">لا طلبات في هذه الفترة.</li>}
      </ul>
    </Panel>
  );
}

function Unmet({ d }: { d: StoreDashboard }) {
  const u = d.unmet_demand;
  return (
    <Panel title="طلب غير مُلبّى">
      <h4 className="mb-1 text-[12.5px] font-bold">شاهدوه وهو بلا رصيد</h4>
      <ul className="mb-3 space-y-1 text-[13px]">
        {u.viewed_out_of_stock.map((p) => (
          <li key={p.product_id} className="flex justify-between gap-2">
            <span className="truncate">{p.name}</span>
            <b>{formatNumber(p.views)} مشاهدة</b>
          </li>
        ))}
        {!u.viewed_out_of_stock.length && <li className="text-ink-faint">لا يوجد.</li>}
      </ul>
      <h4 className="mb-1 text-[12.5px] font-bold">طلبات «اطلب توفيره»</h4>
      <ul className="space-y-1 text-[13px]">
        {u.availability_requests.map((r) => (
          <li key={r.catalog_id} className="flex justify-between gap-2">
            <span className="truncate">{r.title}</span>
            <b>{formatNumber(r.requests)}</b>
          </li>
        ))}
        {!u.availability_requests.length && <li className="text-ink-faint">لا يوجد.</li>}
      </ul>
    </Panel>
  );
}

function Pass({ ok }: { ok: boolean | null }) {
  if (ok === null) return <span className="text-ink-faint">—</span>;
  return <span className={ok ? "text-success" : "text-danger"}>{ok ? "ضمن الهدف" : "خارج الهدف"}</span>;
}

function Speed({ d }: { d: StoreDashboard }) {
  return (
    <Panel title="سرعة المتجر">
      <p className="mb-2 text-[12px] text-ink-faint">
        من متصفحات الزوار الحقيقيين (الشريحة 75%). الأهداف: LCP ≤ 2.5 ث، INP ≤ 200 ms، CLS ≤ 0.1.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-[13px]">
          <thead>
            <tr className="text-ink-faint">
              <th className="p-1.5 text-start">الصفحة</th>
              <th className="p-1.5 text-start">عينات</th>
              <th className="p-1.5 text-start">LCP</th>
              <th className="p-1.5 text-start">INP</th>
              <th className="p-1.5 text-start">CLS</th>
            </tr>
          </thead>
          <tbody>
            {d.vitals.map((v) => (
              <tr key={v.page} className="border-t border-line/60">
                <td className="p-1.5">{PAGE[v.page] ?? v.page}</td>
                <td className="p-1.5">{formatNumber(v.samples)}</td>
                <td className="p-1.5">
                  {v.lcp_p75_ms === null ? "—" : `${formatNumber(v.lcp_p75_ms)} ms`}{" "}
                  <Pass ok={v.passes.lcp} />
                </td>
                <td className="p-1.5">
                  {v.inp_p75_ms === null ? "—" : `${formatNumber(v.inp_p75_ms)} ms`}{" "}
                  <Pass ok={v.passes.inp} />
                </td>
                <td className="p-1.5">
                  {v.cls_p75 ?? "—"} <Pass ok={v.passes.cls} />
                </td>
              </tr>
            ))}
            {!d.vitals.length && (
              <tr>
                <td className="p-1.5 text-ink-faint" colSpan={5}>
                  لا قياسات بعد — تُجمع من زيارات المتجر الجديد.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <h4 className="mb-1 mt-4 text-[12.5px] font-bold">زمن استجابة الخادم (منذ آخر تشغيل)</h4>
      <ul className="space-y-1 text-[13px]">
        {d.server.rows.slice(0, 8).map((r) => (
          <li key={r.endpoint} className="flex justify-between gap-2">
            <span className="truncate" dir="ltr">
              {r.endpoint}
            </span>
            <span>
              P50 {r.p50_ms} ms · P95 {r.p95_ms} ms ({formatNumber(r.count)})
            </span>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

/** Admin only: the online store's design switch and the owner's own texts. */
function StoreSettingsPanel() {
  const isAdmin = useSession((s) => s.session?.user.role === "admin");
  const client = useQueryClient();
  const q = useQuery({
    queryKey: ["storeSettings"],
    queryFn: () => finora.storeAnalytics.settings(),
    enabled: isAdmin,
  });
  const [draft, setDraft] = useState<{ about_text: string; returns_policy: string } | null>(null);
  const save = useMutation({
    mutationFn: (input: Parameters<typeof finora.storeAnalytics.saveSettings>[0]) =>
      finora.storeAnalytics.saveSettings(input),
    onSuccess: async () => {
      toast.success("حُفظت إعدادات المتجر");
      setDraft(null);
      await client.invalidateQueries({ queryKey: ["storeSettings"] });
    },
    onError: (err) => toast.error(toFinoraError(err).message),
  });
  if (!isAdmin || !q.data) return null;
  const s = q.data;
  const texts = draft ?? { about_text: s.about_text, returns_policy: s.returns_policy };
  return (
    <Panel title="إعدادات المتجر الإلكتروني">
      <label className="flex items-center gap-3 text-[13.5px]">
        <input
          type="checkbox"
          role="switch"
          aria-label="التصميم الجديد للمتجر"
          checked={s.design_v2}
          disabled={save.isPending}
          onChange={(e) => save.mutate({ design_v2: e.target.checked })}
        />
        <span>
          <b>التصميم الجديد للمتجر</b> —{" "}
          {s.design_v2 ? "مفعّل: يراه كل الزبائن" : "متوقف: الزبائن يرون التصميم القديم"}
        </span>
      </label>
      <div className="mt-4 grid gap-3 md:grid-cols-2">
        <label className="grid gap-1 text-[12.5px]">
          نص «عن المتجر» (اختياري — يظهر أعلى الصفحة)
          <textarea
            aria-label="نص عن المتجر"
            className={cn(supplierInput, "min-h-24 py-2")}
            maxLength={1500}
            value={texts.about_text}
            onChange={(e) => setDraft({ ...texts, about_text: e.target.value })}
          />
        </label>
        <label className="grid gap-1 text-[12.5px]">
          سياسة الإرجاع والاستبدال (اختياري — تحل محل النص العام في صفحة الشروط)
          <textarea
            aria-label="سياسة الإرجاع"
            className={cn(supplierInput, "min-h-24 py-2")}
            maxLength={2000}
            placeholder="مثلاً: يمكن إرجاع الجهاز خلال 3 أيام بكارتونه الأصلي إذا لم يُستعمل."
            value={texts.returns_policy}
            onChange={(e) => setDraft({ ...texts, returns_policy: e.target.value })}
          />
        </label>
      </div>
      {draft && (
        <button
          type="button"
          className={`${supplierSecondary} mt-3`}
          disabled={save.isPending}
          onClick={() => save.mutate(draft)}
        >
          حفظ النصوص
        </button>
      )}
    </Panel>
  );
}
