import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ShieldAlert, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { finora, toFinoraError } from "@/api/finora";
import type { OverrideChange, PermissionEmployee, PermissionGroup } from "@/api/finora/permissions";
import { useConnection } from "@/stores/connection";
import { toast } from "@/stores/toasts";
import { useWindowManager } from "@/stores/windowManager";
import { cn } from "@/utils/cn";
import { Panel } from "../shipping/shared";
import { supplierInput, supplierPrimary, supplierSecondary } from "../suppliers/SupplierDialogs";
import { RolesTab } from "./RolesTab";

type Tab = "employees" | "roles" | "audit";
type Choice = "inherit" | "grant" | "deny";

const SOURCE: Record<string, string> = {
  admin: "مدير عام",
  deny: "ممنوع بشكل فردي",
  grant: "مسموح بشكل فردي",
  role: "من الدور",
  none: "غير ممنوح",
};

/** Permissions: roles + per-employee exceptions (deny beats grant beats role). General admin only. */
export function PermissionsWindow() {
  const active = useWindowManager((s) => s.active === "permissions");
  const [tab, setTab] = useState<Tab>("employees");
  return (
    <div className="flex h-full min-h-0 flex-col p-5" dir="rtl">
      <div
        role="tablist"
        aria-label="أقسام الصلاحيات"
        className="mb-4 flex gap-1 rounded-control bg-white/70 p-1 shadow-control"
      >
        {(
          [
            ["employees", "صلاحيات الموظفين"],
            ["roles", "الأدوار"],
            ["audit", "سجل التغييرات"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={tab === id}
            onClick={() => setTab(id)}
            className={cn(
              "h-9 rounded-[11px] px-4 text-[13.5px] font-medium",
              tab === id ? "bg-violet-soft text-violet-deep" : "text-ink-soft hover:text-ink",
            )}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {tab === "employees" && <EmployeesTab enabled={active} />}
        {tab === "roles" && <RolesTab enabled={active} />}
        {tab === "audit" && <AuditTab enabled={active} />}
      </div>
    </div>
  );
}

function EmployeesTab({ enabled }: { enabled: boolean }) {
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<number | null>(null);
  const list = useQuery({
    queryKey: ["permissions", "employees"],
    queryFn: () => finora.permissions.employees(),
    enabled,
  });
  const rows = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return (list.data?.rows ?? []).filter(
      (e) => !needle || `${e.name} ${e.username ?? ""} ${e.roles.join(" ")}`.toLowerCase().includes(needle),
    );
  }, [list.data, search]);
  return (
    <div className="grid min-h-0 gap-4 lg:grid-cols-[320px_1fr]">
      <div>
        <input
          aria-label="بحث عن موظف"
          className={cn(supplierInput, "mb-3")}
          placeholder="ابحث عن موظف…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        {list.error && <p className="text-sm text-danger">{toFinoraError(list.error).message}</p>}
        <ul className="space-y-1.5">
          {rows.map((e) => (
            <EmployeeItem
              key={e.id}
              employee={e}
              current={selected === e.id}
              onPick={() => setSelected(e.id)}
            />
          ))}
        </ul>
      </div>
      <div>
        {selected === null ? (
          <p className="py-10 text-center text-sm text-ink-faint">اختر موظفاً لعرض صلاحياته وتعديلها</p>
        ) : (
          <EmployeeEditor id={selected} enabled={enabled} />
        )}
      </div>
    </div>
  );
}

function EmployeeItem({
  employee,
  current,
  onPick,
}: {
  employee: PermissionEmployee;
  current: boolean;
  onPick(): void;
}) {
  return (
    <li>
      <button
        type="button"
        onClick={onPick}
        aria-pressed={current}
        className={cn(
          "flex w-full items-center justify-between rounded-panel p-3 text-start ring-1",
          current ? "bg-violet-soft ring-violet/40" : "bg-white/85 ring-line/60",
          !employee.active && "opacity-60",
        )}
      >
        <span>
          <strong className="block text-[14px]">{employee.name}</strong>
          <span className="text-[12px] text-ink-faint">
            {employee.is_admin ? "مدير عام" : employee.roles.join("، ") || "بلا دور"}
            {!employee.active && " · غير فعّال"}
          </span>
        </span>
        {employee.overrides > 0 && (
          <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-800">
            {employee.overrides} استثناء
          </span>
        )}
      </button>
    </li>
  );
}

function EmployeeEditor({ id, enabled }: { id: number; enabled: boolean }) {
  const online = useConnection((s) => s.status === "online");
  const client = useQueryClient();
  const detail = useQuery({
    queryKey: ["permissions", "employee", id],
    queryFn: () => finora.permissions.employee(id),
    enabled,
  });
  const catalog = useQuery({
    queryKey: ["permissions", "catalog"],
    queryFn: () => finora.permissions.catalog(),
    enabled,
    staleTime: 60_000,
  });
  const roles = useQuery({
    queryKey: ["permissions", "roles"],
    queryFn: () => finora.permissions.roles(),
    enabled,
  });
  const [draft, setDraft] = useState<Record<string, Choice>>({});
  const [roleIds, setRoleIds] = useState<number[] | null>(null);
  useEffect(() => {
    setDraft({});
    setRoleIds(null);
  }, [id]);

  const refresh = async () => {
    await client.invalidateQueries({ queryKey: ["permissions"] });
  };
  const saveOverrides = useMutation({
    mutationFn: () => {
      const changes: Record<string, OverrideChange> = {};
      for (const [name, choice] of Object.entries(draft))
        changes[name] = choice === "inherit" ? null : choice;
      return finora.permissions.setOverrides(id, changes);
    },
    onSuccess: async () => {
      toast.success("حُفظت صلاحيات الموظف");
      setDraft({});
      await refresh();
    },
    onError: (e: unknown) => toast.error(toFinoraError(e).message),
  });
  const saveRoles = useMutation({
    mutationFn: () => finora.permissions.setRoles(id, roleIds ?? []),
    onSuccess: async () => {
      toast.success("حُفظت أدوار الموظف");
      setRoleIds(null);
      await refresh();
    },
    onError: (e: unknown) => toast.error(toFinoraError(e).message),
  });

  const data = detail.data;
  if (detail.error) return <p className="text-sm text-danger">{toFinoraError(detail.error).message}</p>;
  if (!data || !catalog.data) return <p className="text-sm text-ink-faint">جارٍ التحميل…</p>;
  const byName = new Map(data.permissions.map((p) => [p.name, p]));
  const currentRoles = roleIds ?? data.role_ids;
  const pending = Object.keys(draft).length;

  return (
    <div className="space-y-4">
      <Panel title={data.employee.name}>
        {data.employee.is_admin ? (
          <p className="flex items-center gap-2 text-[13px] text-ink-soft">
            <ShieldCheck size={16} aria-hidden /> المدير العام يملك كل الصلاحيات ولا تُقيَّد بأي استثناء.
          </p>
        ) : (
          <>
            <p className="mb-2 text-[12.5px] text-ink-soft">الأدوار</p>
            <div className="flex flex-wrap gap-3">
              {(roles.data?.rows ?? []).map((r) => (
                <label key={r.id} className="inline-flex items-center gap-1.5 text-[13px]">
                  <input
                    type="checkbox"
                    checked={currentRoles.includes(r.id)}
                    onChange={(e) =>
                      setRoleIds(
                        e.target.checked ? [...currentRoles, r.id] : currentRoles.filter((x) => x !== r.id),
                      )
                    }
                  />
                  {r.name}
                </label>
              ))}
              {roles.data?.rows.length === 0 && (
                <span className="text-[13px] text-ink-faint">لا أدوار بعد</span>
              )}
            </div>
            {roleIds !== null && (
              <button
                type="button"
                className={cn(supplierPrimary, "mt-3")}
                disabled={!online || saveRoles.isPending}
                onClick={() => saveRoles.mutate()}
              >
                حفظ الأدوار
              </button>
            )}
          </>
        )}
      </Panel>

      {!data.employee.is_admin && (
        <>
          <p className="text-[12.5px] text-ink-soft">
            «حسب الدور» يتبع أدوار الموظف. «سماح» أو «منع» استثناء فردي: المنع يغلب الدور والسماح يفتح
            الصلاحية حتى بلا دور.
          </p>
          {catalog.data.groups.map((group) => (
            <GroupPanel
              key={group.key}
              group={group}
              byName={byName}
              draft={draft}
              onChoose={(name, choice, original) =>
                setDraft((cur) => {
                  const rest = Object.fromEntries(Object.entries(cur).filter(([key]) => key !== name));
                  return choice === original ? rest : { ...rest, [name]: choice };
                })
              }
            />
          ))}
          <div className="sticky bottom-0 flex items-center gap-3 rounded-panel bg-white/95 p-3 shadow-control">
            <button
              type="button"
              className={supplierPrimary}
              disabled={!online || pending === 0 || saveOverrides.isPending}
              onClick={() => saveOverrides.mutate()}
            >
              حفظ التغييرات {pending > 0 ? `(${pending})` : ""}
            </button>
            {pending > 0 && (
              <button type="button" className={supplierSecondary} onClick={() => setDraft({})}>
                تراجع
              </button>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function GroupPanel({
  group,
  byName,
  draft,
  onChoose,
}: {
  group: PermissionGroup;
  byName: Map<string, import("@/api/finora/permissions").EffectivePermission>;
  draft: Record<string, Choice>;
  onChoose(name: string, choice: Choice, original: Choice): void;
}) {
  const allowedCount = group.permissions.filter((p) => byName.get(p.name)?.allowed).length;
  return (
    <details className="rounded-panel bg-white/85 ring-1 ring-line/60">
      <summary className="cursor-pointer p-3 text-[14px] font-semibold">
        {group.title}{" "}
        <span className="text-[12px] font-normal text-ink-faint">
          ({allowedCount}/{group.permissions.length} ممنوحة)
        </span>
      </summary>
      <ul className="divide-y divide-line/50 px-3 pb-2">
        {group.permissions.map((p) => {
          const eff = byName.get(p.name);
          const original: Choice = eff?.override ?? "inherit";
          const choice = draft[p.name] ?? original;
          return (
            <li key={p.name} className="flex flex-wrap items-center justify-between gap-2 py-2 text-[13px]">
              <span className="min-w-0 flex-1">
                {p.sensitive && (
                  <ShieldAlert size={13} className="me-1 inline text-amber-600" aria-label="حساسة" />
                )}
                {p.label}
                <span
                  className={cn("ms-2 text-[11.5px]", eff?.allowed ? "text-emerald-700" : "text-ink-faint")}
                >
                  {eff?.allowed ? "✓" : "✗"} {SOURCE[eff?.source ?? "none"]}
                  {eff?.source === "role" && eff.roles.length > 0 ? ` (${eff.roles.join("، ")})` : ""}
                </span>
              </span>
              <span
                role="radiogroup"
                aria-label={p.label}
                className="inline-flex overflow-hidden rounded-control ring-1 ring-line"
              >
                {(
                  [
                    ["inherit", "حسب الدور"],
                    ["grant", "سماح"],
                    ["deny", "منع"],
                  ] as const
                ).map(([value, label]) => (
                  <button
                    key={value}
                    type="button"
                    role="radio"
                    aria-checked={choice === value}
                    aria-label={`${p.label}: ${label}`}
                    onClick={() => onChoose(p.name, value, original)}
                    className={cn(
                      "px-2.5 py-1 text-[12px]",
                      choice === value
                        ? value === "deny"
                          ? "bg-danger text-white"
                          : value === "grant"
                            ? "bg-emerald-600 text-white"
                            : "bg-violet-soft text-violet-deep"
                        : "bg-white text-ink-soft",
                    )}
                  >
                    {label}
                  </button>
                ))}
              </span>
            </li>
          );
        })}
      </ul>
    </details>
  );
}

function AuditTab({ enabled }: { enabled: boolean }) {
  const audit = useQuery({
    queryKey: ["permissions", "audit"],
    queryFn: () => finora.permissions.audit(),
    enabled,
  });
  return (
    <Panel title="آخر التغييرات على الصلاحيات">
      <ul className="space-y-1.5 text-[13px]">
        {(audit.data?.rows ?? []).length === 0 && <li className="text-ink-faint">لا تغييرات مسجلة</li>}
        {(audit.data?.rows ?? []).map((r) => (
          <li key={r.id} className="flex justify-between gap-3">
            <span>
              {r.summary} <span className="text-ink-faint">— {r.by}</span>
            </span>
            <span className="ltr-isolate text-[12px] text-ink-faint">{r.at}</span>
          </li>
        ))}
      </ul>
    </Panel>
  );
}
