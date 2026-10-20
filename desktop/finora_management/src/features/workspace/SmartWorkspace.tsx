import {
  ArrowLeft,
  Activity,
  Banknote,
  Bell,
  Boxes,
  Building2,
  CalendarDays,
  CheckCheck,
  ChevronLeft,
  Clock3,
  FileText,
  History,
  LayoutGrid,
  PackagePlus,
  RefreshCw,
  ScanBarcode,
  Search,
  Settings2,
  ShieldAlert,
  ShoppingCart,
  TrendingUp,
  UserPlus,
  Wallet,
  Wifi,
  WifiOff,
  Zap,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useState } from "react";
import { DialogShell, ConfirmDialog } from "@/components/Dialog";
import { useConnection } from "@/stores/connection";
import { useOffline } from "@/stores/offline";
import { useSession } from "@/stores/session";
import { useWindowManager } from "@/stores/windowManager";
import { toast } from "@/stores/toasts";
import { WINDOWS } from "@/windows/registry";
import { formatNumber } from "@/utils/format";
import { useWorkspaceData } from "./useWorkspaceData";
import { WorkspaceCustomization, ACTION_LABELS } from "./WorkspaceCustomization";
import { actionAllowed, openWorkspaceTarget, runWorkspaceAction, ACTION_TARGETS } from "./navigation";
import { allowedWindow, useWorkspace, type ActionId, type WidgetId, type WorkspaceTarget } from "./state";
import { Panel, Empty, Retry, Skeleton, Metric, relative } from "./WorkspacePrimitives";
import { getTasks, TaskList } from "./AttentionCenter";
import { Assistant } from "./WorkspaceAssistant";
import { ActivityHistory } from "./ActivityHistory";
import "./workspace.css";
const ACTION_ICONS: Record<ActionId, LucideIcon> = {
  order: Boxes,
  sale: ShoppingCart,
  expense: FileText,
  receipt: Banknote,
  audit: ScanBarcode,
  search: Search,
  product: PackagePlus,
  customer: UserPlus,
};
export function SmartWorkspace() {
  const session = useSession((s) => s.session);
  const active = useWindowManager((s) => s.active === null);
  const prefs = useWorkspace((s) => s.prefs);
  const recent = useWorkspace((s) => s.recent);
  const saved = useWorkspace((s) => s.saved);
  const visits = useWorkspace((s) => s.visits);
  const dismissed = useWorkspace((s) => s.dismissed);
  const ready = useWorkspace((s) => s.ready);
  const offline = useOffline((s) => s.status);
  const connection = useConnection((s) => s.status);
  const [customize, setCustomize] = useState(false);
  const [allTasks, setAllTasks] = useState(false);
  const [allActivity, setAllActivity] = useState(false);
  const [restore, setRestore] = useState(false);
  const [deferred, setDeferred] = useState<string[]>([]);
  const [clock, setClock] = useState(() => new Date());
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => setClock(new Date()), 60_000);
    return () => window.clearInterval(timer);
  }, [active]);
  const data = useWorkspaceData();
  const tasks = getTasks(data);
  const visible = (id: WidgetId) => prefs.visible.includes(id);
  const order = (id: WidgetId) => ({ order: prefs.order.indexOf(id) < 0 ? 99 : prefs.order.indexOf(id) });
  const resume = recent.filter((row) => allowedWindow(row.target.window, session)).slice(0, 4);
  const recoverable = saved.filter((target) => allowedWindow(target.window, session));
  const suggestion = prefs.suggestions
    ? Object.entries(visits)
        .filter(
          ([id, count]) =>
            count >= 5 &&
            !deferred.includes(`${data.identity}:${id}`) &&
            !dismissed.includes(id as WorkspaceTarget["window"]) &&
            allowedWindow(id as WorkspaceTarget["window"], session) &&
            ACTIONS_FOR_WINDOW(id).some((action) => actionAllowed(action) && !prefs.actions.includes(action)),
        )
        .sort((a, b) => b[1] - a[1])[0]
    : undefined;
  const sales = data.sales.data?.value;
  const receivables = data.receivables.data?.value;
  const status =
    connection !== "online"
      ? connection === "offline"
        ? "بدون إنترنت"
        : "الخادم غير متاح"
      : offline.syncing
        ? "جارٍ المزامنة"
        : offline.conflicts || offline.error
          ? "تحتاج المزامنة مراجعة"
          : "الخادم متاح";
  const branch =
    session?.branch_scope === "shared"
      ? "كل الفروع (مشتركة)"
      : session?.branch_scope === "all"
        ? "كل الفروع المسموحة"
        : (session?.branch?.name ?? "الفرع الحالي");
  return (
    <main
      aria-label="الرئيسية"
      dir="rtl"
      hidden={!active}
      className={`smart-workspace ${prefs.compact ? "workspace-compact" : ""}`}
      data-testid="smart-workspace"
    >
      <div className="workspace-welcome">
        <div>
          <p className="workspace-eyebrow">مساحة العمل · FINORA</p>
          <h1>
            <span aria-hidden>👋</span> {clock.getHours() < 12 ? "صباح الخير" : "أهلاً بك"} في{" "}
            {session?.tenant.name || session?.tenant.slug || "FINORA"}
          </h1>
          <p>كل شيء جاهز، من وين تحب تبدأ اليوم؟</p>
        </div>
        <div className="workspace-status">
          <span>
            <CalendarDays size={18} />
            {clock.toLocaleDateString("ar-IQ", {
              weekday: "long",
              day: "numeric",
              month: "long",
              year: "numeric",
            })}
          </span>
          <span>
            <Building2 size={18} />
            {branch}
          </span>
          <span className={connection === "online" ? "workspace-online" : "workspace-offline"}>
            {connection === "online" ? <Wifi size={17} /> : <WifiOff size={17} />}
            <span>
              {status}
              <small>
                {offline.pending > 0
                  ? `${offline.pending} عملية تنتظر المزامنة`
                  : offline.lastCachedAt
                    ? `آخر حفظ محلي: ${relative(offline.lastCachedAt)}`
                    : !offline.available
                      ? "التخزين المحلي غير متاح"
                      : "لا توجد عمليات مزامنة معلقة"}
              </small>
            </span>
          </span>
        </div>
        <button
          className="workspace-button workspace-restore"
          onClick={() => setRestore(true)}
          disabled={!recoverable.length}
        >
          <History size={17} />
          استعادة الجلسة
        </button>
      </div>
      <div className="workspace-toolbar">
        <span>
          {connection !== "online"
            ? "آخر بيانات محفوظة · قد تختلف عن الخادم"
            : "المؤشرات ضمن صلاحيات حسابك ونطاق العمل الحالي"}
        </span>
        <button className="workspace-button" onClick={() => setCustomize(true)}>
          <Settings2 size={15} />
          تخصيص مساحة العمل
        </button>
      </div>
      <div className="workspace-kpis">
        {visible("sales") && data.can("view_reports") && (
          <div style={order("sales")}>
            <Metric
              title="مبيعات اليوم"
              icon={TrendingUp}
              value={sales?.value}
              detail={
                sales
                  ? `أمس: ${formatNumber(sales.previous)} د.ع${data.sales.data?.cachedAt ? " · محفوظة" : ""}`
                  : "المبيعات المعتمدة في التقارير"
              }
              tone="green"
              change={sales?.change}
              error={data.sales.isError}
              retry={data.sales.refetch}
              onOpen={() => openWorkspaceTarget({ window: "reports", tab: "sales", period: "today" })}
            />
          </div>
        )}
        {visible("orders") && data.can("can_see_orders") && (
          <div style={order("orders")}>
            <Metric
              title="الطلبات"
              icon={Boxes}
              value={data.activeOrders}
              detail={
                data.orders.data
                  ? [
                      [data.orders.data.ordered, "جديدة"],
                      [data.orders.data.packed, "معبأة"],
                      [data.orders.data.shipping, "قيد الشحن"],
                    ]
                      .filter(([v]) => v !== undefined)
                      .map(([v, label]) => `${v} ${label}`)
                      .join(" · ") || "كل الطلبات الظاهرة لحسابك"
                  : "الطلبات النشطة المسموح بعرضها"
              }
              tone="blue"
              error={data.orders.isError}
              retry={data.orders.refetch}
              onOpen={() => openWorkspaceTarget({ window: "orders", tab: "all" })}
            />
          </div>
        )}
        {visible("attention") && (
          <div style={order("attention")}>
            <Metric
              title="المتابعة"
              icon={ShieldAlert}
              value={data.attention}
              detail="طلبات التجهيز والمخزون والمزامنة"
              tone="violet"
              error={data.attentionError}
              retry={data.refreshAttention}
              onOpen={() => setAllTasks(true)}
            />
          </div>
        )}
        {visible("receivables") && data.can("manage_customers") && (
          <div style={order("receivables")}>
            <Metric
              title="المستحقات"
              icon={Wallet}
              value={receivables?.value}
              detail={
                receivables ? `${formatNumber(receivables.debtors)} عميل بذمم قائمة` : "أرصدة العملاء الفعلية"
              }
              tone="orange"
              error={data.receivables.isError}
              retry={data.receivables.refetch}
              onOpen={() => openWorkspaceTarget({ window: "customers", tab: "debt" })}
            />
          </div>
        )}
      </div>
      <div className="workspace-panels">
        {visible("quick") && (
          <div style={order("quick")}>
            <Panel
              title="ابدأ العمل"
              icon={Zap}
              footer={
                <button onClick={() => setCustomize(true)}>
                  <Settings2 size={16} />
                  تخصيص الإجراءات
                </button>
              }
            >
              <div className="workspace-actions">
                {prefs.actions.filter(actionAllowed).map((action) => {
                  const Icon = ACTION_ICONS[action];
                  return (
                    <button
                      key={action}
                      className={`workspace-action action-${action}`}
                      disabled={
                        connection !== "online" && !["search", "sale", "order", "audit"].includes(action)
                      }
                      title={
                        connection !== "online" && !["search", "sale", "order", "audit"].includes(action)
                          ? "هذا الإجراء يحتاج اتصالاً بالخادم"
                          : undefined
                      }
                      onClick={() => runWorkspaceAction(action)}
                    >
                      <span>{ACTION_LABELS[action]}</span>
                      <Icon size={24} strokeWidth={1.7} />
                    </button>
                  );
                })}
              </div>
              {!prefs.actions.filter(actionAllowed).length && (
                <Empty>اختر الإجراءات المناسبة من التخصيص.</Empty>
              )}
              {suggestion && (
                <div className="workspace-adaptive">
                  <p>
                    تستخدم {WINDOWS[suggestion[0] as WorkspaceTarget["window"]].navLabel} كثيراً؛ تثبيت
                    اختصار؟
                  </p>
                  <button
                    onClick={() => {
                      const action = ACTIONS_FOR_WINDOW(suggestion[0]).find(
                        (a) => actionAllowed(a) && !prefs.actions.includes(a),
                      );
                      if (
                        action &&
                        !useWorkspace.getState().configure({ ...prefs, actions: [...prefs.actions, action] })
                      )
                        toast.error("تعذر حفظ الاختصار");
                    }}
                  >
                    تثبيت
                  </button>
                  <button
                    onClick={() => setDeferred((items) => [...items, `${data.identity}:${suggestion[0]}`])}
                  >
                    لاحقاً
                  </button>
                  <button
                    onClick={() =>
                      useWorkspace.getState().dismiss(suggestion[0] as WorkspaceTarget["window"])
                    }
                  >
                    عدم الاقتراح مجدداً
                  </button>
                </div>
              )}
            </Panel>
          </div>
        )}
        {visible("tasks") && (
          <div style={order("tasks")}>
            <Panel
              title="يحتاج اهتمامك"
              className="workspace-tasks-preview"
              icon={Bell}
              count={data.attention}
              footer={
                <button onClick={() => setAllTasks(true)}>
                  <LayoutGrid size={16} />
                  عرض كل المهام
                </button>
              }
            >
              {tasks.length ? (
                <TaskList tasks={tasks.slice(0, 5)} />
              ) : data.attention === undefined ? (
                data.attentionError ? (
                  <Retry retry={data.refreshAttention} />
                ) : (
                  <Skeleton />
                )
              ) : (
                <Empty>
                  <CheckCheck size={26} />
                  لا توجد مهام ضمن المصادر المتاحة حالياً.
                </Empty>
              )}
            </Panel>
          </div>
        )}
        {visible("resume") && (
          <div style={order("resume")}>
            <Panel
              title="أكمل من حيث توقفت"
              icon={Clock3}
              footer={
                <button disabled={!recoverable.length} onClick={() => setRestore(true)}>
                  <RefreshCw size={16} />
                  استعادة جلسة العمل
                </button>
              }
            >
              {resume.length ? (
                <div className="workspace-list">
                  {resume.map((row) => {
                    const definition = WINDOWS[row.target.window],
                      Icon = definition.icon;
                    return (
                      <button
                        key={row.target.window}
                        onClick={() => openWorkspaceTarget(row.target)}
                        className="workspace-list-row tone-blue"
                      >
                        <span className="workspace-row-icon">
                          <Icon size={22} />
                        </span>
                        <span className="workspace-row-text">
                          <strong>
                            {definition.title}
                            {row.target.entityId ? ` #${row.target.entityId}` : ""}
                          </strong>
                          <small>آخر مشاهدة · {relative(row.at)}</small>
                        </span>
                        <ChevronLeft size={17} />
                      </button>
                    );
                  })}
                </div>
              ) : (
                <Empty>
                  <History size={26} />
                  ابدأ العمل وستظهر هنا آخر الأقسام التي استخدمتها.
                </Empty>
              )}
            </Panel>
          </div>
        )}
      </div>
      <div className="workspace-bottom">
        {visible("activity") && (
          <div style={order("activity")} className="workspace-activity-wrap">
            <Panel
              title="النشاط الأخير"
              icon={Activity}
              footer={
                <button onClick={() => setAllActivity(true)}>
                  <ArrowLeft size={15} />
                  عرض السجل الكامل
                </button>
              }
            >
              {data.activity.isError ? (
                <Retry retry={data.activity.refetch} />
              ) : data.activity.data ? (
                data.activity.data.value.rows.length ? (
                  <div className="workspace-activity">
                    {data.activity.data.value.rows.slice(0, 4).map((row) => (
                      <button
                        key={row.id}
                        onClick={() =>
                          row.deleted
                            ? toast.info("حُذف هذا السجل؛ يبقى الحدث محفوظاً للمراجعة")
                            : openWorkspaceTarget(row.target)
                        }
                      >
                        <span className="workspace-row-icon">
                          <Activity size={20} />
                        </span>
                        <span>
                          <strong>
                            {row.title}
                            {row.target.entityId ? ` #${row.target.entityId}` : ""}
                          </strong>
                          <small>
                            {row.actor ? `من قبل ${row.actor} · ` : ""}
                            {relative(Date.parse(row.at))}
                          </small>
                        </span>
                      </button>
                    ))}
                  </div>
                ) : (
                  <Empty>لا يوجد نشاط حديث لعرضه.</Empty>
                )
              ) : (
                <Skeleton />
              )}
            </Panel>
          </div>
        )}
        {visible("assistant") && ready && active && (
          <Assistant key={data.identity} scope={data.identity} order={prefs.order.indexOf("assistant")} />
        )}
      </div>
      {customize && <WorkspaceCustomization onClose={() => setCustomize(false)} />}
      <ConfirmDialog
        open={restore}
        title="استعادة جلسة العمل"
        message={`يمكن استعادة ${recoverable.length} قسم ضمن حسابك وفرعك الحالي. تُستعاد الفلاتر والسجلات المدعومة فقط؛ المسودات المالية تعتمد على نظام الاسترداد الخاص بكل قسم.`}
        confirmLabel="استعادة الجلسة"
        onClose={() => setRestore(false)}
        onConfirm={() => {
          setRestore(false);
          const [first, ...rest] = recoverable;
          for (const target of rest.slice().reverse()) {
            openWorkspaceTarget(target);
            useWindowManager.getState().minimize();
          }
          if (first) openWorkspaceTarget(first);
        }}
      />
      {allTasks && (
        <DialogShell
          open
          title="مركز المتابعة"
          onClose={() => setAllTasks(false)}
          footer={
            <button className="workspace-button" onClick={() => setAllTasks(false)}>
              إغلاق
            </button>
          }
        >
          <div className="workspace-activity-history">
            <TaskList
              tasks={tasks.map((task) => ({
                ...task,
                open: () => {
                  setAllTasks(false);
                  task.open();
                },
              }))}
            />
          </div>
          {data.attentionError ? (
            <Retry retry={data.refreshAttention}>تعذر تحميل بعض مصادر المتابعة</Retry>
          ) : (
            !tasks.length &&
            (data.attention === undefined ? <Skeleton /> : <Empty>لا توجد مهام متاحة حالياً.</Empty>)
          )}
          <p className="workspace-caption">
            المصادر: الطلبات الجديدة، المخزون المنخفض والنافد، مسودات كشوف الشحن، تنبيهات الموظفين المسموحة،
            وأخطاء المزامنة. لا يتكرر العنصر داخل هذه المصادر.
          </p>
        </DialogShell>
      )}
      {allActivity && <ActivityHistory identity={data.identity} onClose={() => setAllActivity(false)} />}
    </main>
  );
}
function ACTIONS_FOR_WINDOW(id: string): ActionId[] {
  return (Object.keys(ACTION_TARGETS) as ActionId[]).filter((key) => ACTION_TARGETS[key] === id);
}
