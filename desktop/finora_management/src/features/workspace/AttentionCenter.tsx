import { Bell, ChevronLeft } from "lucide-react";
import { useUi } from "@/stores/ui";
import { useHRNavigation } from "@/stores/hrNavigation";
import { useWindowManager } from "@/stores/windowManager";
import { useSession } from "@/stores/session";
import { allowedWindow } from "./state";
import { formatNumber } from "@/utils/format";
import { openWorkspaceTarget } from "./navigation";
import type { useWorkspaceData } from "./useWorkspaceData";
type Data = ReturnType<typeof useWorkspaceData>;
export interface Task {
  id: string;
  title: string;
  hint: string;
  count: number;
  tone: string;
  open(): void;
}
export function getTasks(data: Data): Task[] {
  const items: Task[] = [];
  if (data.syncIssues > 0)
    items.push({
      id: "sync",
      title: "المزامنة تحتاج مراجعة",
      hint: "راجع العمليات المحفوظة قبل إعادة المحاولة",
      count: data.syncIssues,
      tone: "rose",
      open: () => useUi.getState().openOfflineSettings(),
    });
  if ((data.ordered ?? 0) > 0)
    items.push({
      id: "ordered",
      title: "طلبات بانتظار التجهيز",
      hint: "افتح الطلبات الجديدة لمتابعتها",
      count: data.ordered ?? 0,
      tone: "rose",
      open: () => openWorkspaceTarget({ window: "orders", tab: "ordered" }),
    });
  const stats = data.stock.data?.stats;
  if (data.can("hr.view")) {
    const seen = new Set<string>();
    for (const item of data.hr.data?.items ?? []) {
      if (seen.has(item.key)) continue;
      seen.add(item.key);
      items.push({
        id: `hr:${item.key}`,
        title: item.title,
        hint: item.body,
        count: 1,
        tone: item.tone === "warning" ? "orange" : "violet",
        open: () => {
          if (!allowedWindow("employees", useSession.getState().session)) return;
          useHRNavigation
            .getState()
            .set({ tab: item.tab, person_id: item.person_id, date: item.date, month: item.month });
          useWindowManager.getState().open("employees");
        },
      });
    }
  }
  if (data.shipping.data?.value.open_manifests)
    items.push({
      id: "shipping",
      title: "كشوف شحن غير معتمدة",
      hint: "راجع مسودات الكشوف قبل الاعتماد",
      count: data.shipping.data.value.open_manifests,
      tone: "orange",
      open: () => openWorkspaceTarget({ window: "shipping", tab: "open-manifests" }),
    });
  if (stats?.out)
    items.push({
      id: "out",
      title: "منتجات نفد مخزونها",
      hint: "ضمن نطاق الفرع والصلاحيات الحالية",
      count: stats.out,
      tone: "orange",
      open: () => openWorkspaceTarget({ window: "products", tab: "out" }),
    });
  if (stats?.low)
    items.push({
      id: "low",
      title: "منتجات وصلت للحد الأدنى",
      hint: "راجع الكميات وحدود التنبيه",
      count: stats.low,
      tone: "violet",
      open: () => openWorkspaceTarget({ window: "products", tab: "low" }),
    });
  return items;
}
export function TaskList({ tasks }: { tasks: Task[] }) {
  return (
    <div className="workspace-list">
      {tasks.map((task) => (
        <button key={task.id} onClick={task.open} className={`workspace-list-row tone-${task.tone}`}>
          <span className="workspace-row-icon">
            <Bell size={17} />
          </span>
          <span className="workspace-row-text">
            <strong>{task.title}</strong>
            <small>{task.hint}</small>
          </span>
          <span className="workspace-count">{formatNumber(task.count)}</span>
          <ChevronLeft size={16} />
        </button>
      ))}
    </div>
  );
}
