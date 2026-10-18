import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { toFinoraError } from "@/api/finora";
import { storageLocations, type StoragePlace, type StorageStock } from "@/api/finora/storageLocations";
import type { StockPayload } from "@/api/finora/stockOperations";
import { ConfirmDialog } from "@/components/Dialog";
import { FeatureHelp } from "@/components/FeatureHelp";
import { SidePanel } from "@/components/SidePanel";
import { toast } from "@/stores/toasts";
import { desktopBridge } from "@/services/bridge";
import { formatNumber } from "@/utils/format";
import { fieldClass, stockButton, stockPrimary } from "./StockForms";

export const storageKinds = {
  main: "أساسي",
  storage: "تخزين",
  sales: "بيع",
  damaged: "تالف",
  returns: "رواجع للمراجعة",
};
export type StorageFormMode =
  | { kind: "location"; place: StoragePlace; editing?: StoragePlace }
  | { kind: "transfer"; place: StoragePlace; row: StorageStock };
export function StorageForm({
  mode,
  places,
  active,
  onClose,
  onSaved,
}: {
  mode: StorageFormMode;
  places: StoragePlace[];
  active: boolean;
  onClose(): void;
  onSaved(documentId?: number): void;
}) {
  const client = useQueryClient();
  const editing = mode.kind === "location" ? mode.editing : undefined;
  const [name, setName] = useState(editing?.name ?? "");
  const [code, setCode] = useState(editing?.code ?? "");
  const [kind, setKind] = useState<Exclude<StoragePlace["kind"], "main">>(
    editing?.kind && editing.kind !== "main" ? editing.kind : "storage",
  );
  const [enabled, setEnabled] = useState(editing?.is_active ?? true);
  const [destination, setDestination] = useState(
    places.find(
      (row) => row.branch_id === mode.place.branch_id && row.is_active && row.key !== mode.place.key,
    )?.key ?? "",
  );
  const [quantity, setQuantity] = useState("1");
  const [reason, setReason] = useState("");
  const [attempt, setAttempt] = useState<StockPayload | null>(null);
  const currentAttempt = useRef<StockPayload | null>(null);
  const [discard, setDiscard] = useState(false);
  const [journalError, setJournalError] = useState(false);
  const dirty =
    mode.kind === "location"
      ? name !== (editing?.name ?? "") ||
        code !== (editing?.code ?? "") ||
        kind !== (editing?.kind ?? "storage") ||
        enabled !== (editing?.is_active ?? true)
      : reason !== "" || quantity !== "1";
  const target = places.find(
    (row) =>
      row.key === destination &&
      row.is_active &&
      row.branch_id === mode.place.branch_id &&
      row.key !== mode.place.key,
  );
  const amount = Number(quantity);
  const valid =
    mode.kind === "location"
      ? !!name.trim() && !!code.trim()
      : !!target &&
        !!reason.trim() &&
        Number.isSafeInteger(amount) &&
        amount > 0 &&
        amount <= mode.row.movable;
  const save = useMutation({
    mutationFn: () => {
      let payload = attempt;
      if (!payload) {
        if (!valid) throw Error("أكمل البيانات المطلوبة");
        payload = { operation_id: crypto.randomUUID(), branch_id: mode.place.branch_id };
        if (mode.kind === "location")
          Object.assign(payload, {
            code: code.trim(),
            name: name.trim(),
            kind,
            is_active: enabled,
            ...(editing ? { revision: editing.revision } : {}),
          });
        else
          Object.assign(payload, {
            product_id: mode.row.product_id,
            variant_name: mode.row.variant_name,
            quantity: amount,
            from_location_id: mode.place.id,
            to_location_id: target?.id ?? null,
            reason: reason.trim(),
          });
        setAttempt(payload);
        currentAttempt.current = payload;
      }
      return mode.kind === "transfer"
        ? storageLocations.createTransfer(payload)
        : editing?.id
          ? storageLocations.updateLocation(editing.id, payload)
          : storageLocations.createLocation(payload);
    },
    onSuccess: (result) => {
      toast.success(
        mode.kind === "transfer"
          ? "حُفظت مسودة التحويل؛ أرسل القطع من السند بعد مغادرتها المصدر"
          : "تم حفظ المخزن",
      );
      onSaved(result.type === "storage_transfer" ? result.id : undefined);
    },
    onError: async (error) => {
      toast.error(toFinoraError(error).message);
      void client.invalidateQueries({ queryKey: ["storage-locations"] });
      void client.invalidateQueries({ queryKey: ["stock-recovery"] });
      const original = currentAttempt.current;
      try {
        setJournalError(false);
        const journal = await desktopBridge().stockRecovery?.list();
        if (journal?.available && !journal.items.some((row) => row.key === original?.operation_id)) {
          setAttempt(null);
          currentAttempt.current = null;
        }
      } catch {
        // Keep the fixed request if the journal cannot prove it was rejected before commit.
        setJournalError(true);
      }
    },
  });
  const close = () => {
    if (save.isPending) return;
    if (dirty || attempt) setDiscard(true);
    else onClose();
  };
  return (
    <>
      <SidePanel
        open={active}
        title={mode.kind === "transfer" ? "تحويل داخلي جديد" : editing ? "تعديل المخزن" : "إضافة مخزن"}
        subtitle={mode.place.branch_name}
        onClose={close}
        layer={45}
        footer={
          <div className="flex flex-wrap gap-2">
            <button
              type="submit"
              form="storage-form"
              className={stockPrimary}
              disabled={save.isPending || (!attempt && !valid)}
            >
              {save.isPending
                ? "جارٍ الحفظ…"
                : attempt
                  ? "إعادة نفس الطلب"
                  : mode.kind === "transfer"
                    ? "حفظ المسودة"
                    : "حفظ المخزن"}
            </button>
            <button type="button" className={stockButton} disabled={save.isPending} onClick={close}>
              إغلاق النموذج
            </button>
          </div>
        }
      >
        <form
          id="storage-form"
          onSubmit={(event) => {
            event.preventDefault();
            if (!save.isPending && (valid || attempt)) save.mutate();
          }}
          className="space-y-4"
        >
          {journalError && (
            <p role="alert" className="rounded-control bg-warning-soft p-3 text-sm">
              تعذر قراءة سجل الطلبات المحلي؛ احتفظنا ببيانات المحاولة حتى تراجع نتيجتها.
            </p>
          )}
          {save.error && (
            <p role="alert" className="rounded-control bg-danger-soft p-3 text-sm text-danger">
              {toFinoraError(save.error).message}
            </p>
          )}
          {attempt && (
            <p className="rounded-control bg-warning-soft p-3 text-xs leading-6 text-ink-soft">
              ثُبتت بيانات الطلب عند أول محاولة. أعد نفس الطلب لمراجعة نتيجته؛ إذا أغلقت النموذج يبقى الطلب
              المحفوظ في سجل المراجعة.
            </p>
          )}
          <fieldset disabled={save.isPending || attempt !== null} className="space-y-4">
            {mode.kind === "location" ? (
              <>
                <label className="block text-sm">
                  اسم المخزن
                  <input
                    autoFocus
                    required
                    maxLength={150}
                    className={fieldClass}
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                  />
                </label>
                <label className="block text-sm">
                  رمز المخزن
                  <input
                    required
                    maxLength={60}
                    className={`${fieldClass} ltr-isolate`}
                    value={code}
                    onChange={(event) => setCode(event.target.value)}
                  />
                </label>
                <label className="block text-sm">
                  نوع الموقع{" "}
                  <FeatureHelp
                    label="شرح أنواع المخازن"
                    text="التخزين والبيع يحتفظان بقطع متاحة حسب الحجوزات. التالف والرواجع للمراجعة لا يتاحان للبيع. يجب نقل الرصيد وإكمال التحويلات قبل تغيير النوع أو إيقاف المخزن."
                  />
                  <select
                    aria-label="نوع الموقع"
                    className={fieldClass}
                    value={kind}
                    onChange={(event) => setKind(event.target.value as typeof kind)}
                  >
                    {(["storage", "sales", "damaged", "returns"] as const).map((value) => (
                      <option key={value} value={value}>
                        {storageKinds[value]}
                      </option>
                    ))}
                  </select>
                </label>
                {editing && (
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={enabled}
                      onChange={(event) => setEnabled(event.target.checked)}
                    />
                    المخزن فعّال
                  </label>
                )}
              </>
            ) : (
              <>
                <div className="rounded-control border border-line bg-white/80 p-3">
                  <strong>{mode.row.name}</strong>
                  <p className="mt-1 text-xs text-ink-faint">
                    {mode.row.sku} · {mode.row.variant_name || "بدون خيارات"}
                  </p>
                </div>
                <p className="text-sm">
                  المصدر: <strong>{mode.place.name}</strong> · قابل للنقل {formatNumber(mode.row.movable)}
                </p>
                <label className="block text-sm">
                  المخزن المقصود
                  <select
                    aria-label="المخزن المقصود"
                    className={fieldClass}
                    value={destination}
                    required
                    onChange={(event) => setDestination(event.target.value)}
                  >
                    <option value="">اختر الموقع</option>
                    {places
                      .filter(
                        (row) =>
                          row.is_active &&
                          row.branch_id === mode.place.branch_id &&
                          row.key !== mode.place.key,
                      )
                      .map((row) => (
                        <option key={row.key} value={row.key}>
                          {row.name}
                        </option>
                      ))}
                  </select>
                </label>
                <label className="block text-sm">
                  كمية القطع
                  <input
                    autoFocus
                    required
                    type="number"
                    min={1}
                    max={mode.row.movable}
                    step={1}
                    className={`${fieldClass} ltr-isolate`}
                    value={quantity}
                    onChange={(event) => setQuantity(event.target.value)}
                  />
                </label>
                <label className="block text-sm">
                  سبب النقل
                  <textarea
                    required
                    maxLength={1000}
                    rows={3}
                    className={fieldClass}
                    value={reason}
                    onChange={(event) => setReason(event.target.value)}
                  />
                </label>
                <p className="rounded-control bg-violet-soft p-3 text-xs leading-6 text-ink-soft">
                  الحفظ ينشئ مسودة دون تغيير الرصيد. بعد مغادرة القطع المصدر افتح السند وأرسلها؛ عند وصولها
                  أكد الاستلام. النقل إلى فرع آخر يتم من تحويلات الفروع.
                </p>
              </>
            )}
          </fieldset>
        </form>
      </SidePanel>
      <ConfirmDialog
        open={active && discard}
        title="إغلاق نموذج المخزن"
        message={
          attempt
            ? "يبقى الطلب الذي حاولت حفظه في سجل المراجعة حتى تتأكد نتيجته. راجع نفس الطلب قبل تسجيل عملية جديدة."
            : "تغلق البيانات غير المحفوظة في هذا النموذج."
        }
        confirmLabel="إغلاق النموذج"
        onClose={() => setDiscard(false)}
        onConfirm={onClose}
      />
    </>
  );
}
