import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Eye, EyeOff, RefreshCw, ArrowUpLeft, BarChart3 } from "lucide-react";
import { finora } from "@/api/finora";
import { useSession } from "@/stores/session";
import { useConnection } from "@/stores/connection";
import { useWindowManager } from "@/stores/windowManager";
import { useAvailableWindows } from "@/hooks/useAvailableWindows";
import { WINDOWS } from "@/windows/registry";
import { useNavigation, openNavItem } from "@/navigation/useNavigation";
import { desktopBridge, hasDesktopBridge } from "@/services/bridge";
import { formatNumber } from "@/utils/format";

export function HomeDashboard() {
  const active = useWindowManager((s) => s.active);
  const session = useSession((s) => s.session);
  const online = useConnection((s) => s.status === "online");
  const windows = useAvailableWindows();
  const navigation = useNavigation();
  const [visible, setVisible] = useState(false);
  const [period, setPeriod] = useState<"today" | "this_week" | "this_month">("today");
  const identity = JSON.stringify(session);
  const canReports = session?.permissions.includes("view_reports") ?? false;
  const summary = useQuery({
    queryKey: ["desktop", "home", identity, period],
    queryFn: () =>
      finora.reports.dashboard({ period, dateFrom: "", dateTo: "", branchId: null, employeeId: null }, "day"),
    enabled: active === null && canReports && online && hasDesktopBridge() && !!desktopBridge().lifecycle,
    staleTime: 60_000,
    refetchInterval: 60_000,
  });
  useEffect(() => {
    setVisible(false);
  }, [identity]);
  useEffect(() => {
    if (!visible) return;
    const timer = setTimeout(() => setVisible(false), 30_000);
    const hide = () => {
      if (document.hidden) setVisible(false);
    };
    document.addEventListener("visibilitychange", hide);
    const blur = () => setVisible(false);
    window.addEventListener("blur", blur);
    return () => {
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", hide);
      window.removeEventListener("blur", blur);
    };
  }, [visible]);
  if (active !== null) return null;
  return (
    <main dir="rtl" aria-label="الرئيسية" className="absolute inset-0 overflow-auto p-4 sm:p-6 lg:p-8">
      <div className="mx-auto max-w-[1450px] space-y-6">
        <section className="flex flex-wrap items-center justify-between gap-4 rounded-panel border border-violet/10 bg-gradient-to-l from-violet-soft to-white p-5">
          <div>
            <p className="text-xs text-ink-soft">
              {session?.tenant.name ?? session?.tenant.slug} · {session?.branch?.name ?? "حسب صلاحيات الحساب"}
            </p>
            <h1 className="mt-2 text-2xl font-bold text-ink">
              {session?.user.name ? `أهلاً ${session.user.name}` : "أهلاً بك"}
            </h1>
            <p className="mt-2 text-sm text-ink-soft">
              اختر نافذة من الشريط العلوي أو اضغط <kbd dir="ltr">Ctrl+K</kbd>
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {canReports && (
              <>
                <select
                  aria-label="فترة ملخص الرئيسية"
                  value={period}
                  onChange={(e) => setPeriod(e.target.value as typeof period)}
                  className="rounded-control border border-line bg-white px-3 py-2"
                >
                  <option value="today">اليوم</option>
                  <option value="this_week">هذا الأسبوع</option>
                  <option value="this_month">هذا الشهر</option>
                </select>
                <button
                  type="button"
                  onClick={() => setVisible((value) => !value)}
                  className="flex items-center gap-2 rounded-control border border-line bg-white px-3 py-2 text-sm"
                >
                  {visible ? <EyeOff size={17} /> : <Eye size={17} />}
                  {visible ? "إخفاء الأرقام" : "إظهار الأرقام"}
                </button>
                <button
                  type="button"
                  aria-label="تحديث ملخص الرئيسية"
                  disabled={!online || summary.isFetching}
                  onClick={() => void summary.refetch()}
                  className="rounded-control border border-line bg-white p-2 disabled:opacity-40"
                >
                  <RefreshCw size={18} />
                </button>
              </>
            )}
          </div>
        </section>
        {canReports && (
          <section aria-label="ملخص الأعمال" className="space-y-3">
            {summary.isError && (
              <p role="alert" className="rounded-control bg-warning-soft p-3 text-sm">
                تعذّر تحديث الملخص. تحقق من الاتصال أو افتح التقارير؛ لا توجد أرقام تقديرية.
              </p>
            )}
            {!online && (
              <p className="text-sm text-ink-soft">الملخص غير متصل. قد تكون آخر قراءة معروضة قديمة.</p>
            )}
            <div className="grid grid-cols-1 gap-3 min-[600px]:grid-cols-2 min-[1100px]:grid-cols-3">
              {(summary.data?.kpis ?? [])
                .filter((kpi) => kpi.value !== null)
                .map((kpi) => (
                  <article
                    key={kpi.key}
                    className="min-w-0 rounded-panel border border-line/80 bg-white/85 p-5 shadow-control"
                  >
                    <p className="text-sm text-ink-soft">{kpi.label}</p>
                    <p
                      dir="ltr"
                      className="mt-3 truncate text-start text-2xl font-bold tabular-nums text-ink"
                    >
                      {visible ? `${formatNumber(kpi.value ?? 0)} د.ع` : "••••••"}
                    </p>
                    {kpi.change_pct !== null && (
                      <p className="mt-2 text-xs text-ink-soft">
                        {visible ? `${formatNumber(kpi.change_pct)}%` : "•••"} مقارنة بالفترة السابقة
                      </p>
                    )}
                  </article>
                ))}
            </div>
            {summary.isPending && online && (
              <p role="status" className="text-sm text-ink-soft">
                جارٍ تحميل ملخص الأعمال…
              </p>
            )}
            {summary.data && (
              <p className="text-xs text-ink-faint">
                آخر قراءة: {new Date(summary.dataUpdatedAt).toLocaleTimeString("ar-IQ")} · الأرقام بالدينار
                العراقي وتخضع لصلاحيات التقارير.
              </p>
            )}
          </section>
        )}
        <section className="rounded-panel border border-line/80 bg-white/75 p-5">
          <h2 className="mb-4 flex items-center gap-2 font-bold text-ink">
            <BarChart3 size={19} className="text-violet" />
            الوصول السريع
          </h2>
          <div className="grid grid-cols-2 gap-3 min-[850px]:grid-cols-3 min-[1200px]:grid-cols-4">
            {windows
              .filter((id) => !WINDOWS[id].moreOnly)
              .map((id) => {
                const item = WINDOWS[id],
                  Icon = item.icon;
                return (
                  <button
                    type="button"
                    key={id}
                    aria-label={`فتح ${item.title}`}
                    onClick={() => useWindowManager.getState().open(id)}
                    className="flex min-h-20 items-center gap-3 rounded-control border border-line bg-white p-4 text-start text-sm font-semibold text-ink transition hover:border-violet/40 hover:bg-violet-soft"
                  >
                    <Icon size={21} className="shrink-0 text-violet" />
                    {item.title}
                  </button>
                );
              })}
            {navigation.items
              .filter((item) => item.id.startsWith("workspace-"))
              .map((item) => (
                <button
                  type="button"
                  key={item.id}
                  onClick={() => openNavItem(item)}
                  className="flex min-h-20 items-center justify-between gap-2 rounded-control border border-line bg-white p-4 text-start text-sm text-ink"
                >
                  {item.label}
                  <ArrowUpLeft size={17} className="shrink-0 text-violet" />
                </button>
              ))}
          </div>
        </section>
      </div>
    </main>
  );
}
