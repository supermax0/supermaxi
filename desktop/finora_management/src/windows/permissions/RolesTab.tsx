import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { finora, toFinoraError } from "@/api/finora";
import type { PermissionRole } from "@/api/finora/permissions";
import { ConfirmDialog } from "@/components/Dialog";
import { useConnection } from "@/stores/connection";
import { toast } from "@/stores/toasts";
import { cn } from "@/utils/cn";
import { Panel } from "../shipping/shared";
import { supplierInput, supplierPrimary, supplierSecondary } from "../suppliers/SupplierDialogs";

/** Role templates: a named set of permissions that can be assigned to many employees. */
export function RolesTab({ enabled }: { enabled: boolean }) {
  const online = useConnection((s) => s.status === "online");
  const client = useQueryClient();
  const [editing, setEditing] = useState<PermissionRole | "new" | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [confirmDelete, setConfirmDelete] = useState<PermissionRole | null>(null);
  const [showTemplates, setShowTemplates] = useState(false);
  const [picked, setPicked] = useState<Set<string>>(new Set());

  const roles = useQuery({
    queryKey: ["permissions", "roles"],
    queryFn: () => finora.permissions.roles(),
    enabled,
  });
  const catalog = useQuery({
    queryKey: ["permissions", "catalog"],
    queryFn: () => finora.permissions.catalog(),
    enabled,
    staleTime: 60_000,
  });

  useEffect(() => {
    if (editing === null) return;
    if (editing === "new") {
      setName("");
      setDescription("");
      setChosen(new Set());
    } else {
      setName(editing.name);
      setDescription(editing.description);
      setChosen(new Set(editing.permissions));
    }
  }, [editing]);

  const save = useMutation({
    mutationFn: () =>
      finora.permissions.saveRole(editing === "new" || editing === null ? null : editing.id, {
        name,
        description,
        permissions: [...chosen],
      }),
    onSuccess: async () => {
      toast.success("حُفظ الدور");
      setEditing(null);
      await client.invalidateQueries({ queryKey: ["permissions"] });
    },
    onError: (e: unknown) => toast.error(toFinoraError(e).message),
  });
  const templates = useQuery({
    queryKey: ["permissions", "templates"],
    queryFn: () => finora.permissions.roleTemplates(),
    enabled: enabled && showTemplates,
  });
  const install = useMutation({
    mutationFn: () => finora.permissions.installTemplates([...picked]),
    onSuccess: async (res) => {
      toast.success(
        `أُضيف ${res.created.length} دور${res.skipped.length ? ` — تجاوزت ${res.skipped.length} موجود مسبقاً` : ""}`,
      );
      setPicked(new Set());
      await client.invalidateQueries({ queryKey: ["permissions"] });
    },
    onError: (e: unknown) => toast.error(toFinoraError(e).message),
  });
  const remove = useMutation({
    mutationFn: (role: PermissionRole) => finora.permissions.deleteRole(role.id),
    onSuccess: async () => {
      toast.success("حُذف الدور");
      setConfirmDelete(null);
      await client.invalidateQueries({ queryKey: ["permissions"] });
    },
    onError: (e: unknown) => {
      setConfirmDelete(null);
      toast.error(toFinoraError(e).message);
    },
  });

  const toggle = (permission: string, on: boolean) =>
    setChosen((cur) => {
      const next = new Set(cur);
      if (on) next.add(permission);
      else next.delete(permission);
      return next;
    });

  return (
    <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
      <div>
        <button
          type="button"
          className={cn(supplierPrimary, "mb-3")}
          disabled={!online}
          onClick={() => setEditing("new")}
        >
          <Plus size={16} /> دور جديد
        </button>
        <button
          type="button"
          className={cn(supplierSecondary, "mb-3 ms-2")}
          disabled={!online}
          onClick={() => setShowTemplates((v) => !v)}
        >
          الأدوار الجاهزة
        </button>
        {showTemplates && (
          <div className="mb-3 space-y-2 rounded-panel bg-white/85 p-3 ring-1 ring-line/60">
            <p className="text-[12.5px] text-ink-soft">
              تُضاف كأدوار عادية تقدر تعدّلها بعد ذلك. لا يُستبدل دور موجود بنفس الاسم.
            </p>
            {(templates.data?.rows ?? []).map((t) => (
              <label key={t.key} className="flex items-start gap-2 text-[13px]">
                <input
                  type="checkbox"
                  disabled={t.installed}
                  checked={t.installed || picked.has(t.key)}
                  onChange={(e) =>
                    setPicked((cur) => {
                      const next = new Set(cur);
                      if (e.target.checked) next.add(t.key);
                      else next.delete(t.key);
                      return next;
                    })
                  }
                />
                <span>
                  <strong>{t.name}</strong>
                  {t.installed && <span className="ms-1 text-[11px] text-emerald-700">مضاف</span>}
                  <span className="block text-[12px] text-ink-faint">
                    {t.description} · {t.permissions.length} صلاحية
                  </span>
                </span>
              </label>
            ))}
            <button
              type="button"
              className={supplierPrimary}
              disabled={!online || picked.size === 0 || install.isPending}
              onClick={() => install.mutate()}
            >
              إضافة المحدد ({picked.size})
            </button>
          </div>
        )}
        <ul className="space-y-1.5">
          {(roles.data?.rows ?? []).map((r) => (
            <li key={r.id} className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setEditing(r)}
                className="flex-1 rounded-panel bg-white/85 p-3 text-start ring-1 ring-line/60"
              >
                <strong className="block text-[14px]">{r.name}</strong>
                <span className="text-[12px] text-ink-faint">
                  {r.permissions.length} صلاحية · {r.employees} موظف
                </span>
              </button>
              <button
                type="button"
                aria-label={`حذف الدور ${r.name}`}
                disabled={!online}
                onClick={() => setConfirmDelete(r)}
              >
                <Trash2 size={15} />
              </button>
            </li>
          ))}
          {roles.data?.rows.length === 0 && <li className="text-sm text-ink-faint">لا أدوار بعد</li>}
        </ul>
      </div>
      <div>
        {editing === null ? (
          <p className="py-10 text-center text-sm text-ink-faint">اختر دوراً أو أنشئ دوراً جديداً</p>
        ) : (
          <div className="space-y-3">
            <input
              aria-label="اسم الدور"
              className={supplierInput}
              placeholder="اسم الدور"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <input
              aria-label="وصف الدور"
              className={supplierInput}
              placeholder="وصف (اختياري)"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
            {(catalog.data?.groups ?? []).map((g) => (
              <Panel key={g.key} title={g.title}>
                <div className="grid gap-1.5 md:grid-cols-2">
                  {g.permissions.map((p) => (
                    <label key={p.name} className="inline-flex items-start gap-2 text-[13px]">
                      <input
                        type="checkbox"
                        checked={chosen.has(p.name)}
                        onChange={(e) => toggle(p.name, e.target.checked)}
                      />
                      <span>
                        {p.label}
                        {p.sensitive && <span className="ms-1 text-[11px] text-amber-700">حساسة</span>}
                      </span>
                    </label>
                  ))}
                </div>
              </Panel>
            ))}
            <div className="flex gap-2">
              <button
                type="button"
                className={supplierPrimary}
                disabled={!online || save.isPending || name.trim().length < 2}
                onClick={() => save.mutate()}
              >
                حفظ الدور
              </button>
              <button type="button" className={supplierSecondary} onClick={() => setEditing(null)}>
                إلغاء
              </button>
            </div>
          </div>
        )}
      </div>
      <ConfirmDialog
        open={confirmDelete !== null}
        title="حذف دور"
        busy={remove.isPending}
        message={`سيُحذف الدور «${confirmDelete?.name ?? ""}». لا يُحذف دور معيّن لموظفين.`}
        confirmLabel="حذف"
        tone="danger"
        onClose={() => setConfirmDelete(null)}
        onConfirm={() => confirmDelete && remove.mutate(confirmDelete)}
      />
    </div>
  );
}
