import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Building2, Check, ChevronDown, Layers } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { finora, toFinoraError } from "@/api/finora";
import { useSession } from "@/stores/session";
import { toast } from "@/stores/toasts";
import { cn } from "@/utils/cn";
import { Popover } from "./Popover";

/**
 * Top-bar work-scope selector. Shown only when the company has turned multi-branch on and the user can
 * actually see more than one branch. It changes the VIEW scope on the server session; every cached query is
 * dropped afterwards so every window reloads for the new scope.
 */
export function BranchScopeSwitcher() {
  const client = useQueryClient();
  const signedIn = useSession((s) => s.status === "signed_in");
  const anchor = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const meta = useQuery({
    queryKey: ["branches", "meta"],
    queryFn: () => finora.branches.meta(),
    enabled: signedIn,
    staleTime: 30_000,
  });
  const change = useMutation({
    mutationFn: (target: { branch_id: number } | { view_all: true }) => finora.branches.switchScope(target),
    onSuccess: async () => {
      setOpen(false);
      await client.invalidateQueries();
    },
    onError: (e: unknown) => toast.error(toFinoraError(e).message),
  });

  const data = meta.data;
  const branches = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    const all = data?.scope.branches ?? [];
    return needle ? all.filter((b) => `${b.name} ${b.code}`.toLowerCase().includes(needle)) : all;
  }, [data, filter]);
  if (!data || !data.multi_branch.enabled || data.scope.branches.length < 2) return null;

  if (data.scope.shared) {
    // Shared mode: nothing is filtered by branch, so naming one branch here would be misleading.
    return (
      <div
        dir="rtl"
        title="الفروع مشتركة: البيانات غير مقسّمة بين الفروع، وكل الشاشات تعرض كل الفروع"
        aria-label="نطاق العمل: كل الفروع (مشتركة)"
        className="flex h-10 items-center gap-2 rounded-control border border-line/70 bg-white/80 px-3 text-[13px] font-medium text-ink shadow-control"
      >
        <Layers size={16} className="shrink-0 text-maroon" />
        <span className="truncate">كل الفروع (مشتركة)</span>
      </div>
    );
  }

  const current = data.scope.branches.find((b) => b.id === data.current_branch_id);
  const label = data.scope.view_all ? "جميع الفروع" : (current?.name ?? "الفرع");

  return (
    <div dir="rtl" className="relative">
      <button
        ref={anchor}
        type="button"
        aria-label={`نطاق العمل: ${label}`}
        aria-haspopup="listbox"
        aria-expanded={open}
        disabled={!data.scope.can_switch}
        title={data.scope.can_switch ? "تبديل نطاق العمل" : "أنت مرتبط بفرع واحد"}
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "flex h-10 max-w-[200px] items-center gap-2 rounded-control border border-line/70 bg-white/80 px-3 text-[13px] font-medium text-ink shadow-control",
          "hover:bg-violet-soft disabled:cursor-default disabled:hover:bg-white/80",
        )}
      >
        {data.scope.view_all ? (
          <Layers size={16} className="shrink-0 text-maroon" />
        ) : (
          <Building2 size={16} className="shrink-0 text-maroon" />
        )}
        <span className="truncate">{label}</span>
        {data.scope.can_switch && <ChevronDown size={14} className="shrink-0 text-ink-faint" />}
      </button>
      <Popover
        open={open}
        onClose={() => setOpen(false)}
        anchor={anchor}
        label="نطاق العمل"
        align="start"
        width={280}
      >
        <div dir="rtl" className="p-2">
          {data.scope.branches.length > 6 && (
            <input
              autoFocus
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="ابحث عن فرع…"
              aria-label="بحث عن فرع"
              className="mb-2 h-9 w-full rounded-control border border-line bg-white px-3 text-sm outline-none focus:border-violet/45"
            />
          )}
          <ul role="listbox" aria-label="الفروع" className="max-h-[320px] space-y-0.5 overflow-y-auto">
            <li>
              <Option
                active={data.scope.view_all}
                icon={<Layers size={15} />}
                title="جميع الفروع"
                hint="عرض مجمّع — الإنشاء يتطلب فرعاً محدداً"
                busy={change.isPending}
                onSelect={() => change.mutate({ view_all: true })}
              />
            </li>
            {branches.map((b) => (
              <li key={b.id}>
                <Option
                  active={!data.scope.view_all && b.id === data.current_branch_id}
                  icon={<Building2 size={15} />}
                  title={b.name}
                  hint={b.is_default ? `${b.code} · الفرع الأساسي` : b.code}
                  busy={change.isPending}
                  onSelect={() => change.mutate({ branch_id: b.id })}
                />
              </li>
            ))}
            {branches.length === 0 && (
              <li className="px-3 py-6 text-center text-xs text-ink-faint">لا توجد نتائج</li>
            )}
          </ul>
        </div>
      </Popover>
    </div>
  );
}

function Option({
  active,
  icon,
  title,
  hint,
  busy,
  onSelect,
}: {
  active: boolean;
  icon: React.ReactNode;
  title: string;
  hint: string;
  busy: boolean;
  onSelect(): void;
}) {
  return (
    <button
      type="button"
      role="option"
      aria-selected={active}
      disabled={busy}
      onClick={onSelect}
      className={cn(
        "flex w-full items-center gap-3 rounded-control px-3 py-2.5 text-start transition-colors",
        active ? "bg-violet-soft text-violet-deep" : "hover:bg-surface-sunken",
      )}
    >
      <span className="text-maroon">{icon}</span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[13px] font-semibold">{title}</span>
        <span className="block truncate text-[11px] text-ink-faint">{hint}</span>
      </span>
      {active && <Check size={15} className="shrink-0" />}
    </button>
  );
}
