import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { finora, toFinoraError } from "@/api/finora";
import type { DistributionItem, DistributionSession } from "@/api/finora/branches";
import { ConfirmDialog } from "@/components/Dialog";
import { useConnection } from "@/stores/connection";
import { toast } from "@/stores/toasts";
import { formatNumber } from "@/utils/format";
import { Metric, Money, Panel } from "../shipping/shared";
import { supplierInput, supplierPrimary, supplierSecondary } from "../suppliers/SupplierDialogs";

const STATUS: Record<DistributionSession["status"], string> = {
  draft: "مسودة",
  ready: "جاهزة للتنفيذ",
  executing: "قيد التنفيذ",
  completed: "مكتملة",
  failed: "فشل — يمكن الاستئناف",
  cancelled: "ملغاة",
};

/** Initial distribution wizard (old companies only): choose → preview → approve → execute. */
export function Distribution({ enabled }: { enabled: boolean }) {
  const online = useConnection((s) => s.status === "online");
  const client = useQueryClient();
  const [openId, setOpenId] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);
  const [confirm, setConfirm] = useState<"execute" | "cancel" | null>(null);

  const list = useQuery({
    queryKey: ["branches", "distribution"],
    queryFn: () => finora.branches.distributionList(),
    enabled,
  });
  const detail = useQuery({
    queryKey: ["branches", "distribution", openId],
    queryFn: () => finora.branches.distributionDetail(openId as number),
    enabled: enabled && openId !== null,
  });
  const refresh = () => client.invalidateQueries({ queryKey: ["branches"] });
  const act = useMutation({
    mutationFn: (action: "approve" | "execute" | "cancel") =>
      finora.branches.distributionAct(openId as number, action),
    onSuccess: async (res, action) => {
      setConfirm(null);
      const s = res.session;
      if (action === "execute") {
        if (s.status === "completed") toast.success("اكتمل التوزيع");
        else toast.error(`لم يكتمل: ${s.failed} عنصر فشل — راجع الأسباب ثم أعد التنفيذ`);
      } else toast.success(action === "approve" ? "اعتُمدت الجلسة" : "أُلغيت الجلسة");
      await refresh();
    },
    onError: (e: unknown) => {
      setConfirm(null);
      toast.error(toFinoraError(e).message);
    },
  });

  const eligibility = list.data?.eligibility;
  const session = detail.data?.session;
  const preview = detail.data?.preview;

  if (creating)
    return (
      <Builder
        onDone={() => setCreating(false)}
        onCreated={(id) => {
          setCreating(false);
          setOpenId(id);
          void refresh();
        }}
      />
    );

  return (
    <div className="space-y-4">
      {eligibility && !eligibility.eligible && (
        <Panel title="غير متاح حالياً">
          <ul className="list-disc ps-5 text-[13.5px] text-ink-soft">
            {eligibility.reasons.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </Panel>
      )}
      {eligibility?.eligible && (
        <button
          type="button"
          className={supplierPrimary}
          disabled={!online}
          onClick={() => setCreating(true)}
        >
          <Plus size={16} /> جلسة توزيع جديدة
        </button>
      )}
      <ul className="space-y-2">
        {(list.data?.rows ?? []).map((r) => (
          <li key={r.id}>
            <button
              type="button"
              onClick={() => setOpenId(r.id)}
              className="flex w-full items-center justify-between rounded-panel bg-white/85 p-3 text-start ring-1 ring-line/60"
            >
              <span>
                <strong>{r.title}</strong>{" "}
                <span className="ltr-isolate text-xs text-ink-faint">{r.number}</span>
              </span>
              <span className="text-[12.5px] text-ink-soft">
                {STATUS[r.status]} · {r.done}/{r.total}
              </span>
            </button>
          </li>
        ))}
        {list.data && list.data.rows.length === 0 && <li className="text-sm text-ink-faint">لا جلسات بعد</li>}
      </ul>

      {session && preview && (
        <Panel title={`${session.title} — ${STATUS[session.status]}`}>
          <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
            <Metric label="وحدات مخزون" value={formatNumber(preview.summary.stock_units)} />
            <Metric label="قيمة المخزون (FIFO)" value={<Money value={preview.summary.stock_value} />} />
            <Metric label="نقد" value={<Money value={preview.summary.cash} />} />
            <Metric label="موظفون" value={formatNumber(preview.summary.staff)} />
          </div>
          <ul className="mt-3 space-y-1.5 text-[13px]">
            {preview.items.map((it) => (
              <li key={it.index} className="flex flex-wrap items-center justify-between gap-2">
                <span>{itemLabel(it as unknown as DistributionItem)}</span>
                <span
                  className={
                    it.verdict === "blocked" || it.state === "failed" ? "text-danger" : "text-ink-soft"
                  }
                >
                  {it.state === "done"
                    ? "تم"
                    : it.state === "failed"
                      ? `فشل: ${String(it.error ?? "")}`
                      : it.verdict === "blocked"
                        ? `محجوب: ${it.reason}`
                        : "جاهز"}
                </span>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-[12px] text-ink-faint">
            {session.backup_path === "unavailable"
              ? "تنبيه: لا يمكن أخذ نسخة استعادة من هنا لهذا النوع من قواعد البيانات — خذ نسخة من الخادم قبل التنفيذ."
              : session.backup_path
                ? `نسخة الاستعادة: ${session.backup_path}`
                : "تُؤخذ نسخة استعادة تلقائياً قبل أول عنصر عند التنفيذ."}
          </p>
          <div className="mt-4 flex flex-wrap gap-2">
            {session.status === "draft" && (
              <button
                type="button"
                className={supplierPrimary}
                disabled={!online || !preview.can_execute || act.isPending}
                onClick={() => act.mutate("approve")}
              >
                اعتماد
              </button>
            )}
            {(session.status === "ready" || session.status === "failed") && (
              <button
                type="button"
                className={supplierPrimary}
                disabled={!online || act.isPending}
                onClick={() => setConfirm("execute")}
              >
                {session.status === "failed" ? "استئناف التنفيذ" : "تنفيذ"}
              </button>
            )}
            {(session.status === "draft" || session.status === "ready") && (
              <button
                type="button"
                className={supplierSecondary}
                disabled={!online || act.isPending}
                onClick={() => setConfirm("cancel")}
              >
                إلغاء الجلسة
              </button>
            )}
          </div>
        </Panel>
      )}

      <ConfirmDialog
        open={confirm !== null}
        title={confirm === "execute" ? "تنفيذ التوزيع" : "إلغاء الجلسة"}
        busy={act.isPending}
        message={
          confirm === "execute"
            ? "ستُنفَّذ العناصر المعتمدة فعلياً (تحويلات مخزون ونقد وتعيينات). كل عنصر يُنفَّذ مرة واحدة فقط."
            : "ستُلغى الجلسة ولا يمكن تنفيذها بعد ذلك."
        }
        confirmLabel={confirm === "execute" ? "تنفيذ" : "إلغاء الجلسة"}
        tone={confirm === "execute" ? undefined : "danger"}
        onClose={() => setConfirm(null)}
        onConfirm={() => confirm && act.mutate(confirm === "execute" ? "execute" : "cancel")}
      />
    </div>
  );
}

function itemLabel(it: DistributionItem & { product_name?: string }): string {
  if (it.type === "stock")
    return `مخزون: منتج #${it.product_id} × ${it.quantity} (فرع ${it.from_branch_id} ← ${it.to_branch_id})`;
  if (it.type === "cash")
    return `نقد: ${formatNumber(it.amount)} (صندوق ${it.from_account_id} ← ${it.to_account_id})`;
  return `موظف #${it.employee_id} ← فرع ${it.branch_id} (${it.mode === "move" ? "نقل" : "إضافي"})`;
}

function Builder({ onDone, onCreated }: { onDone: () => void; onCreated: (id: number) => void }) {
  const online = useConnection((s) => s.status === "online");
  const [title, setTitle] = useState("");
  const [items, setItems] = useState<DistributionItem[]>([]);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [q, setQ] = useState("");
  const [qty, setQty] = useState<Record<number, string>>({});
  const [cashFrom, setCashFrom] = useState("");
  const [cashTo, setCashTo] = useState("");
  const [amount, setAmount] = useState("");
  const [person, setPerson] = useState("");
  const [personBranch, setPersonBranch] = useState("");
  const [mode, setMode] = useState<"extra" | "move">("extra");

  const meta = useQuery({ queryKey: ["branches", "meta"], queryFn: () => finora.branches.meta() });
  const accounts = useQuery({ queryKey: ["branch-cash", "meta"], queryFn: () => finora.branchCash.meta() });
  const people = useQuery({ queryKey: ["branches", "people"], queryFn: () => finora.branches.people() });
  const stock = useQuery({
    queryKey: ["distribution", "stock", from, q],
    queryFn: () => finora.stockOperations.stocks("branch", `branch:${from}`, q, 1, 12),
    enabled: from !== "",
  });
  const create = useMutation({
    mutationFn: () => finora.branches.distributionCreate(title.trim(), items),
    onSuccess: (res) => onCreated(res.session.id),
    onError: (e: unknown) => toast.error(toFinoraError(e).message),
  });

  const branchList = meta.data?.scope.branches ?? [];
  const add = (item: DistributionItem) => setItems((cur) => [...cur, item]);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <input
          aria-label="عنوان الجلسة"
          className={supplierInput}
          placeholder="عنوان الجلسة"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
      </div>

      <Panel title="مخزون">
        <div className="grid gap-2 md:grid-cols-3">
          <select
            aria-label="الفرع المصدر"
            className={supplierInput}
            value={from}
            onChange={(e) => setFrom(e.target.value)}
          >
            <option value="">من فرع…</option>
            {branchList.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))}
          </select>
          <select
            aria-label="الفرع المستلم"
            className={supplierInput}
            value={to}
            onChange={(e) => setTo(e.target.value)}
          >
            <option value="">إلى فرع…</option>
            {branchList
              .filter((b) => String(b.id) !== from)
              .map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                </option>
              ))}
          </select>
          <input
            aria-label="بحث منتج"
            className={supplierInput}
            placeholder="بحث منتج"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
        <ul className="mt-2 space-y-1.5 text-[13px]">
          {(stock.data?.items ?? []).map((row) => (
            <li key={row.id} className="flex items-center justify-between gap-2">
              <span>
                {row.name} <span className="text-ink-faint">(متاح {row.available})</span>
              </span>
              <span className="flex items-center gap-1">
                <input
                  aria-label={`كمية ${row.name}`}
                  className="h-9 w-20 rounded-control border border-line px-2"
                  inputMode="numeric"
                  value={qty[row.product_id] ?? ""}
                  onChange={(e) => setQty({ ...qty, [row.product_id]: e.target.value })}
                />
                <button
                  type="button"
                  className={supplierSecondary}
                  disabled={!to || !Number(qty[row.product_id])}
                  onClick={() =>
                    add({
                      type: "stock",
                      product_id: row.product_id,
                      variant_color: row.variant_name || null,
                      quantity: Number(qty[row.product_id]),
                      from_branch_id: Number(from),
                      to_branch_id: Number(to),
                    })
                  }
                >
                  إضافة
                </button>
              </span>
            </li>
          ))}
        </ul>
      </Panel>

      <Panel title="أموال">
        <div className="grid gap-2 md:grid-cols-4">
          <select
            aria-label="الصندوق المصدر"
            className={supplierInput}
            value={cashFrom}
            onChange={(e) => setCashFrom(e.target.value)}
          >
            <option value="">من صندوق…</option>
            {(accounts.data?.accounts ?? [])
              .filter((a) => a.can_send_from)
              .map((a) => (
                <option key={a.id} value={a.id}>
                  {a.branch_name} — {a.name}
                </option>
              ))}
          </select>
          <select
            aria-label="الصندوق المستلم"
            className={supplierInput}
            value={cashTo}
            onChange={(e) => setCashTo(e.target.value)}
          >
            <option value="">إلى صندوق…</option>
            {(accounts.data?.accounts ?? [])
              .filter((a) => String(a.id) !== cashFrom)
              .map((a) => (
                <option key={a.id} value={a.id}>
                  {a.branch_name} — {a.name}
                </option>
              ))}
          </select>
          <input
            aria-label="المبلغ"
            className={supplierInput}
            inputMode="numeric"
            placeholder="المبلغ"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
          />
          <button
            type="button"
            className={supplierSecondary}
            disabled={!cashFrom || !cashTo || !Number(amount)}
            onClick={() =>
              add({
                type: "cash",
                from_account_id: Number(cashFrom),
                to_account_id: Number(cashTo),
                amount: Number(amount),
              })
            }
          >
            إضافة
          </button>
        </div>
      </Panel>

      <Panel title="موظفون">
        <div className="grid gap-2 md:grid-cols-4">
          <select
            aria-label="الموظف"
            className={supplierInput}
            value={person}
            onChange={(e) => setPerson(e.target.value)}
          >
            <option value="">الموظف…</option>
            {(people.data?.rows ?? []).map((p) => (
              <option key={p.id} value={p.id}>
                {p.name} — {p.home_branch}
              </option>
            ))}
          </select>
          <select
            aria-label="فرع الموظف"
            className={supplierInput}
            value={personBranch}
            onChange={(e) => setPersonBranch(e.target.value)}
          >
            <option value="">الفرع…</option>
            {branchList.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))}
          </select>
          <select
            aria-label="نوع التعيين"
            className={supplierInput}
            value={mode}
            onChange={(e) => setMode(e.target.value as "extra" | "move")}
          >
            <option value="extra">يعمل أيضاً هناك</option>
            <option value="move">نقل (فرع أساسي)</option>
          </select>
          <button
            type="button"
            className={supplierSecondary}
            disabled={!person || !personBranch}
            onClick={() =>
              add({ type: "staff", employee_id: Number(person), branch_id: Number(personBranch), mode })
            }
          >
            إضافة
          </button>
        </div>
      </Panel>

      <Panel title={`العناصر المختارة (${items.length})`}>
        <ul className="space-y-1.5 text-[13px]">
          {items.length === 0 && (
            <li className="text-ink-faint">لم تختر شيئاً بعد — لا شيء يُنفَّذ افتراضياً</li>
          )}
          {items.map((it, i) => (
            <li key={i} className="flex items-center justify-between gap-2">
              <span>{itemLabel(it)}</span>
              <button
                type="button"
                aria-label="حذف العنصر"
                onClick={() => setItems(items.filter((_, j) => j !== i))}
              >
                <Trash2 size={14} />
              </button>
            </li>
          ))}
        </ul>
      </Panel>

      <div className="flex gap-2">
        <button
          type="button"
          className={supplierPrimary}
          disabled={!online || create.isPending || items.length === 0 || title.trim().length < 3}
          onClick={() => create.mutate()}
        >
          حفظ ومعاينة
        </button>
        <button type="button" className={supplierSecondary} onClick={onDone}>
          إلغاء
        </button>
      </div>
    </div>
  );
}
