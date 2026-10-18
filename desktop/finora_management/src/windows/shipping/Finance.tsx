import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Printer, ReceiptText, Save } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { finora, toFinoraError } from "@/api/finora";
import { CYCLES, type CarrierSettings, type ShippingMeta, type ShippingReceipt } from "@/api/finora/shipping";
import { DataTable, type Column } from "@/components/DataTable";
import { Field } from "@/components/FilterPanel";
import { MoneyInput } from "@/components/MoneyInput";
import { SearchBox } from "@/components/SearchBox";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { desktopBridge } from "@/services/bridge";
import { useConnection } from "@/stores/connection";
import { toast } from "@/stores/toasts";
import { cn } from "@/utils/cn";
import { formatNumber } from "@/utils/format";
import { supplierInput, supplierPrimary } from "../suppliers/SupplierDialogs";
import { Metric, Money, money } from "./shared";

export function printReceipt(id: number) {
  desktopBridge()
    .print.open({ kind: "shipping_receipt", id })
    .catch((e: unknown) => toast.error(toFinoraError(e).message));
}

/** Account statement of a carrier / agent: what it owes us (debit) against fees and receipts (credit). */
export function StatementView({ owner, id }: { owner: "carriers" | "agents"; id: number }) {
  const statement = useQuery({
    queryKey: ["shipping", owner, id, "statement"],
    queryFn: () => finora.shipping.statement(owner, id),
  });
  const data = statement.data;
  if (statement.error) return <p className="text-sm text-danger">{toFinoraError(statement.error).message}</p>;
  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-3 gap-2">
        <Metric label="مدين (تحصيلات)" value={money(data?.debit ?? 0)} />
        <Metric label="دائن (أجور + قبض)" value={money(data?.credit ?? 0)} />
        <Metric
          label="الرصيد بذمتهم"
          value={money(data?.balance ?? 0)}
          tone={(data?.balance ?? 0) > 0 ? "text-maroon" : "text-success"}
        />
      </div>
      <table className="w-full text-[12px]" aria-label="كشف الحساب">
        <thead className="text-[11px] text-ink-faint">
          <tr>
            <th className="py-1.5 text-start font-medium">البيان</th>
            <th className="py-1.5 text-start font-medium">مدين</th>
            <th className="py-1.5 text-start font-medium">دائن</th>
            <th className="py-1.5 text-start font-medium">الرصيد</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line/60">
          {statement.isPending && (
            <tr>
              <td colSpan={4} className="py-6 text-center text-ink-faint">
                جارٍ التحميل…
              </td>
            </tr>
          )}
          {data?.lines.length === 0 && (
            <tr>
              <td colSpan={4} className="py-6 text-center text-ink-faint">
                لا توجد تسويات معتمدة بعد
              </td>
            </tr>
          )}
          {data?.lines.map((line, i) => (
            <tr key={i}>
              <td className="py-2">
                <p className="font-medium text-ink">{line.label}</p>
                <p className="ltr-isolate text-right text-[10px] text-ink-faint">
                  {line.manifest_number} · {line.date}
                </p>
              </td>
              <td className="ltr-isolate py-2 text-right">{line.debit ? formatNumber(line.debit) : "—"}</td>
              <td className="ltr-isolate py-2 text-right">{line.credit ? formatNumber(line.credit) : "—"}</td>
              <td className="ltr-isolate py-2 text-right font-semibold">{formatNumber(line.balance)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Receipt vouchers (سندات القبض) issued by approved settlements. */
export function ReceiptsList({
  filter,
  compact = false,
  enabled = true,
}: {
  filter?: { party_type: "carrier" | "agent"; party_id: number };
  compact?: boolean;
  enabled?: boolean;
}) {
  const [searchText, setSearchText] = useState("");
  const search = useDebouncedValue(searchText, 250);
  const receipts = useQuery({
    queryKey: ["shipping", "receipts", filter ?? null, search],
    queryFn: () => finora.shipping.receipts({ ...filter, search }),
    enabled,
  });
  const columns = useMemo<Column<ShippingReceipt>[]>(
    () => [
      {
        id: "number",
        header: "رقم السند",
        width: "24%",
        cell: (r) => (
          <div className="min-w-0">
            <p className="ltr-isolate truncate text-right font-bold">{r.number}</p>
            <p className="truncate text-[11px] text-ink-faint">{r.notes}</p>
          </div>
        ),
      },
      {
        id: "party",
        header: "الجهة",
        width: "20%",
        cell: (r) => (
          <div>
            <p className="truncate font-medium">{r.party_name}</p>
            <p className="text-[11px] text-ink-faint">{r.party_type === "agent" ? "مندوب" : "شركة نقل"}</p>
          </div>
        ),
      },
      {
        id: "amount",
        header: "المبلغ",
        width: "16%",
        cell: (r) => <Money value={r.amount} className="font-bold" />,
      },
      {
        id: "orders",
        header: "الطلبات",
        width: "10%",
        cell: (r) => <span className="ltr-isolate">{formatNumber(r.allocations.length)}</span>,
      },
      {
        id: "method",
        header: "القبض",
        width: "16%",
        minTableWidth: 760,
        cell: (r) => (
          <div className="text-[12px]">
            <p>{r.payment_method === "bank" ? "تحويل مصرفي" : "نقداً"}</p>
            <p className="text-[11px] text-ink-faint">{r.treasury_account}</p>
          </div>
        ),
      },
      {
        id: "date",
        header: "التاريخ",
        width: "14%",
        cell: (r) => <span className="ltr-isolate text-[12px]">{r.date}</span>,
      },
    ],
    [],
  );
  const actions = (r: ShippingReceipt) => (
    <button
      type="button"
      aria-label={`طباعة ${r.number}`}
      className="grid h-8 w-8 place-items-center rounded-[10px] border border-line/70 bg-white/75 text-ink-soft hover:bg-violet-soft"
      onClick={(e) => {
        e.stopPropagation();
        printReceipt(r.id);
      }}
    >
      <Printer size={15} />
    </button>
  );
  if (compact) {
    const rows = receipts.data?.rows ?? [];
    return (
      <ul className="divide-y divide-line/60 text-[13px]">
        {rows.length === 0 && (
          <li className="py-8 text-center text-ink-faint">
            {receipts.isPending ? "جارٍ التحميل…" : "لا توجد سندات"}
          </li>
        )}
        {rows.map((r) => (
          <li key={r.id} className="flex items-center gap-3 py-2.5">
            <ReceiptText size={16} className="shrink-0 text-maroon" />
            <div className="min-w-0 flex-1">
              <p className="ltr-isolate truncate text-right font-bold">{r.number}</p>
              <p className="text-[11px] text-ink-faint">
                {r.date} · {formatNumber(r.allocations.length)} طلب
              </p>
            </div>
            <Money value={r.amount} className="font-semibold" />
            {actions(r)}
          </li>
        ))}
      </ul>
    );
  }
  return (
    <div className="flex h-full min-h-0 flex-col">
      <SearchBox
        value={searchText}
        onChange={setSearchText}
        busy={receipts.isFetching}
        placeholder="رقم السند أو الجهة أو مرجع الشركة…"
        className="mb-3 shrink-0"
      />
      <DataTable
        label="سندات القبض"
        columns={columns}
        rows={receipts.data?.rows}
        loading={receipts.isPending}
        fetching={receipts.isFetching}
        error={receipts.error ? toFinoraError(receipts.error).message : null}
        onRetry={() => void receipts.refetch()}
        emptyTitle="لا توجد سندات قبض"
        emptyHint="يصدر سند القبض تلقائياً عند اعتماد كشف تسوية."
        rowActions={actions}
      />
    </div>
  );
}

/** Per-carrier delivery-fee and settlement settings. */
export function CarrierSettingsForm({
  carrierId,
  canManage,
  treasuryAccounts,
}: {
  carrierId: number;
  canManage: boolean;
  treasuryAccounts: ShippingMeta["treasury_accounts"];
}) {
  const client = useQueryClient();
  const online = useConnection((s) => s.status === "online");
  const settings = useQuery({
    queryKey: ["shipping", "settings", carrierId],
    queryFn: () => finora.shipping.settings(carrierId),
  });
  const [form, setForm] = useState<CarrierSettings | null>(null);
  useEffect(() => {
    if (settings.data) setForm(settings.data.settings);
  }, [settings.data]);
  const save = useMutation({
    mutationFn: (f: CarrierSettings) =>
      finora.shipping.saveSettings(carrierId, {
        price: f.price,
        return_fee: f.return_fee,
        settlement_cycle: f.settlement_cycle,
        payment_method: f.payment_method,
        treasury_account_id: f.treasury_account_id,
        notes: f.notes,
      }),
    onSuccess: async () => {
      toast.success("حُفظت إعدادات الشركة");
      await client.invalidateQueries({ queryKey: ["shipping"] });
    },
    onError: (e: unknown) => toast.error(toFinoraError(e).message),
  });
  if (!form) return <p className="py-6 text-center text-[13px] text-ink-faint">جارٍ التحميل…</p>;
  const set = (patch: Partial<CarrierSettings>) => setForm((f) => (f ? { ...f, ...patch } : f));
  return (
    <form
      className="grid grid-cols-2 gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate(form);
      }}
    >
      <Field label="أجرة التوصيل الثابتة">
        <MoneyInput
          label="أجرة التوصيل الثابتة"
          value={form.price}
          onChange={(v) => set({ price: v })}
          className={supplierInput}
        />
      </Field>
      <Field label="أجرة المرتجع (0 = مجانية)">
        <MoneyInput
          label="أجرة المرتجع"
          value={form.return_fee}
          onChange={(v) => set({ return_fee: v })}
          className={supplierInput}
        />
      </Field>
      <Field label="دورة التسديد">
        <select
          className={supplierInput}
          value={form.settlement_cycle}
          onChange={(e) => set({ settlement_cycle: e.target.value as CarrierSettings["settlement_cycle"] })}
        >
          {Object.entries(CYCLES).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </Field>
      <Field label="طريقة الاستلام">
        <select
          className={supplierInput}
          value={form.payment_method}
          onChange={(e) => set({ payment_method: e.target.value === "bank" ? "bank" : "cash" })}
        >
          <option value="cash">نقداً</option>
          <option value="bank">تحويل مصرفي</option>
        </select>
      </Field>
      <Field label="الحساب الافتراضي للإيداع" wide>
        <select
          className={supplierInput}
          value={form.treasury_account_id ?? ""}
          onChange={(e) => set({ treasury_account_id: e.target.value ? Number(e.target.value) : null })}
        >
          <option value="">الافتراضي</option>
          {treasuryAccounts.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>
      </Field>
      <Field label="ملاحظات العقد" wide>
        <textarea
          className={cn(supplierInput, "h-16 py-2")}
          value={form.notes}
          onChange={(e) => set({ notes: e.target.value })}
        />
      </Field>
      <p className="col-span-2 text-[11px] leading-5 text-ink-faint">
        أجرة التوصيل تُخصم من التحصيل مرة واحدة لكل طلب. أجرة المرتجع تُخصم من صافي الكشف وتُسجَّل مصروف توصيل
        عند الاعتماد.
        {form.updated_by && ` آخر تعديل: ${form.updated_by} ${form.updated_at}`}
      </p>
      {canManage && (
        <div className="col-span-2 flex justify-end">
          <button type="submit" className={supplierPrimary} disabled={!online || save.isPending}>
            <Save size={16} /> حفظ الإعدادات
          </button>
        </div>
      )}
    </form>
  );
}
