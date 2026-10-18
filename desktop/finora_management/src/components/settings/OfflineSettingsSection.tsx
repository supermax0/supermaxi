import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Cloud, RefreshCw, Download, PackageCheck } from "lucide-react";
import { desktopBridge } from "@/services/bridge";
import { useOffline } from "@/stores/offline";
import { toast } from "@/stores/toasts";
import { useConnection } from "@/stores/connection";
import { formatIqd } from "@/utils/money";
import { SectionCard } from "./primitives";

const labels = {
  pending: "بانتظار المزامنة",
  syncing: "جارٍ الإرسال",
  conflict: "تحتاج مراجعة",
  done: "تم التسجيل",
  cancelled: "طلب محلي ملغى",
};
export function OfflineSettingsSection() {
  const status = useOffline((s) => s.status);
  const online = useConnection((s) => s.status === "online");
  const client = useQueryClient();
  const download = useMutation({
    mutationFn: (restart?: boolean) => {
      const bridge = desktopBridge().offline;
      if (!bridge?.downloadSnapshot) throw new Error("حدّث التطبيق لتفعيل تنزيل النسخة المحلية.");
      return bridge.downloadSnapshot(restart);
    },
    onSuccess: (next) => {
      useOffline.getState().set(next);
      void client.invalidateQueries();
    },
  });
  const snapshot = status.snapshot;
  const quota = useMutation({
    mutationFn: async (resume: boolean) => {
      const bridge = desktopBridge().offline;
      if (!bridge?.returnStock) throw new Error("حدّث التطبيق لتفعيل حصة المخزون.");
      return resume ? bridge.resumeStockRequest() : bridge.returnStock();
    },
    onSuccess: (next) => useOffline.getState().set(next),
  });
  const sync = useMutation({
    mutationFn: async (id?: string) => {
      const bridge = desktopBridge().offline;
      if (!bridge) throw new Error("حدّث برنامج FINORA لتفعيل التخزين المحلي.");
      return id ? bridge.retry(id) : bridge.synchronize();
    },
    onSuccess: (next) => {
      useOffline.getState().set(next);
      void client.invalidateQueries();
    },
  });
  const discard = useMutation({
    mutationFn: (id: string) => {
      const bridge = desktopBridge().offline;
      if (!bridge?.discardHR) throw new Error("حدّث التطبيق لمراجعة الطلب المحلي");
      return bridge.discardHR(id);
    },
    onSuccess: (next) => {
      useOffline.getState().set(next);
      void client.invalidateQueries();
    },
  });
  const stamp = status.lastCachedAt
    ? new Date(status.lastCachedAt).toLocaleString("ar-IQ")
    : "لم تُحمّل بيانات بعد";
  return (
    <>
      <SectionCard icon={Download} title="نسخة البيانات للأوفلاين">
        <div className="space-y-3 p-4 text-sm text-ink-soft">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p>{snapshot?.capturedAt ? "النسخة المحلية مكتملة" : "نزّل البيانات قبل العمل بدون نت"}</p>
              <p className="mt-1 text-xs text-ink-faint">
                {snapshot?.capturedAt
                  ? new Date(snapshot.capturedAt).toLocaleString("ar-IQ")
                  : "تشمل السجلات والتفاصيل المتاحة لصلاحياتك في هذا الفرع."}
              </p>
            </div>
            <button
              type="button"
              disabled={
                !online || !status.available || download.isPending || snapshot?.downloading || status.syncing
              }
              onClick={() => download.mutate(false)}
              className="inline-flex items-center gap-2 rounded-control bg-maroon px-4 py-2 text-xs font-semibold text-white disabled:opacity-45"
            >
              <Download size={14} />
              {download.isPending || snapshot?.downloading
                ? "جارٍ التنزيل…"
                : snapshot?.resumable
                  ? "استئناف التنزيل"
                  : snapshot?.capturedAt
                    ? "تحديث النسخة"
                    : "تنزيل البيانات"}
            </button>
          </div>
          {(snapshot?.downloading || snapshot?.resumable) && (
            <div className="space-y-2">
              <p className="text-xs">
                {snapshot.downloaded} من {snapshot.total || "…"} سجل · النسخة السابقة محفوظة حتى اكتمال
                التنزيل.
              </p>
              <progress
                aria-label="تقدّم تنزيل بيانات الأوفلاين"
                className="h-2 w-full accent-violet"
                value={snapshot.downloaded}
                max={Math.max(snapshot.total, 1)}
              />
            </div>
          )}
          {snapshot?.resumable && !snapshot.downloading && (
            <button
              type="button"
              disabled={!online || download.isPending}
              onClick={() => download.mutate(true)}
              className="text-xs font-semibold text-violet disabled:opacity-45"
            >
              بدء تنزيل جديد مع إبقاء النسخة السابقة
            </button>
          )}
          {!!snapshot?.datasets.length && (
            <p className="text-xs">
              {snapshot.datasets.reduce((n, d) => n + d.total, 0)} سجل في {snapshot.datasets.length} مجموعة
              بيانات.
            </p>
          )}
          {status.hr?.ready && (
            <p className="text-xs text-ink-soft">
              بيانات HR: {status.hr.people} ملف موظف، مع الدوام وآخر ٣ أشهر رواتب والسلف والإجازات.{" "}
              {status.hr.stale ? "تحتاج تحديثاً بعد العمليات الأخيرة." : "جاهزة للعمل دون اتصال."}
            </p>
          )}
          {snapshot?.stale && (
            <p className="text-xs text-warning">
              حدثت عمليات بعد تنزيل النسخة؛ حدّثها للحصول على أحدث الأرصدة والمخزون.
            </p>
          )}
          {(download.isError || snapshot?.error) && (
            <p role="alert" className="text-xs text-danger">
              {download.isError
                ? String(download.error instanceof Error ? download.error.message : download.error)
                : snapshot?.error}
            </p>
          )}
          <p className="text-xs leading-6">
            التنزيل قابل للاستئناف بعد انقطاع الاتصال أو إعادة التشغيل. تظهر النسخة الجديدة بعد اكتمال جميع
            الصفحات، وتشمل البحث والفلترة محلياً. الصور والتقارير المطبوعة تحتاج اتصالاً حالياً.
          </p>
        </div>
      </SectionCard>
      <SectionCard icon={PackageCheck} title="حصة مخزون هذا الجهاز">
        <div className="space-y-3 p-4 text-sm text-ink-soft">
          <p className="text-xs leading-6">
            احجز الكمية من نافذة بيع للمورد وأنت متصل، ثم اختر «اعتماد البيع من حصة هذا الجهاز». الكمية
            المحجوزة محمية من البيع على الأجهزة الأخرى، ولا تُلغى تلقائياً عند الانقطاع.
          </p>
          {!status.stock?.rows.length && (
            <p className="text-xs text-ink-faint">لا توجد حصة محجوزة لهذا المستخدم والفرع.</p>
          )}
          <div className="max-h-48 space-y-2 overflow-auto">
            {status.stock?.rows
              .filter((row) => row.available || row.used || row.frozen)
              .map((row) => (
                <div
                  key={row.id}
                  className="flex justify-between gap-3 rounded-control border border-line/60 bg-white/70 p-3 text-xs"
                >
                  <span>
                    {row.name}
                    {row.color ? ` · ${row.color}` : ""}
                  </span>
                  <span className="text-violet">
                    {row.frozen ? "مجمّدة لحين تأكيد الإعادة" : `متبقي ${row.available} · مستخدم ${row.used}`}
                  </span>
                </div>
              ))}
          </div>
          <button
            type="button"
            onClick={() => quota.mutate(!!status.stock?.pendingRequest)}
            disabled={
              !online ||
              quota.isPending ||
              status.stock?.busy ||
              (!status.stock?.pendingRequest && !status.stock?.rows.some((row) => row.available > 0))
            }
            className="rounded-control border border-line bg-white px-4 py-2 text-xs font-semibold text-violet disabled:opacity-45"
          >
            {quota.isPending
              ? "جارٍ التأكيد…"
              : status.stock?.pendingRequest
                ? "استئناف طلب الحصة المحفوظ"
                : "إعادة الحصة غير المستخدمة"}
          </button>
          <p className="text-xs leading-5">
            عند الإعادة تتوقف الكمية محلياً قبل إرسال الطلب، وتبقى متوقفة إذا انقطع الاتصال حتى تأكيد السيرفر.
            الكميات المستخدمة في بيع محفوظ لا تُعاد.
          </p>
          {(quota.isError || status.stock?.error) && (
            <p role="alert" className="text-xs text-danger">
              {quota.isError
                ? String(quota.error instanceof Error ? quota.error.message : quota.error)
                : status.stock?.error}
            </p>
          )}
        </div>
      </SectionCard>
      <SectionCard icon={Cloud} title="الأوفلاين والمزامنة">
        <div className="space-y-3 p-4 text-sm text-ink-soft">
          <p>
            {status.available
              ? "التخزين المحلي المشفّر جاهز لهذا المستخدم والفرع."
              : "يلزم تسجيل دخول أونلاين لتجهيز الوصول المحلي."}
          </p>
          <p className="text-xs">آخر بيانات محفوظة: {stamp}</p>
          <div className="flex items-center justify-between gap-3 rounded-control bg-violet-soft/60 p-3">
            <span>
              {status.pending} بانتظار المزامنة · {status.conflicts} تحتاج مراجعة
            </span>
            <button
              type="button"
              onClick={() => sync.mutate(undefined)}
              disabled={!online || sync.isPending || status.syncing}
              className="inline-flex items-center gap-2 rounded-control bg-maroon px-4 py-2 text-xs font-semibold text-white disabled:opacity-45"
            >
              <RefreshCw
                size={14}
                className={sync.isPending || status.syncing ? "animate-spin" : undefined}
              />
              مزامنة الآن
            </button>
          </div>
          <p className="text-xs leading-6">
            تتوفر النسخة المحلية والبيع للمورد ونقطة البيع من حصة الجهاز. البيع المعتمد يُحفظ برقم محلي
            ويستهلك الحصة فوراً، مع الدفع النقدي أو التحويل أو الآجل في نقطة البيع، ثم يتزامن بنفس المعرّف.
            المسودة العادية تنتظر تحقق السيرفر ولا تُعد إيصالاً. الأرصدة المعروضة تتحدث بعد المزامنة؛
            التعديلات والإلغاءات والتحصيلات المنفصلة تحتاج اتصالاً.
          </p>
          <p className="text-xs leading-6">
            الوصول المحلي صالح حتى 24 ساعة من آخر تحقق أونلاين. عملياتك المحفوظة تبقى بعد انتهاء الوصول، وتظهر
            عند دخول نفس المستخدم والفرع.
          </p>
          {(status.error || sync.isError) && (
            <p role="alert" className="text-danger">
              {sync.isError
                ? String(sync.error instanceof Error ? sync.error.message : sync.error)
                : status.error}
            </p>
          )}
        </div>
      </SectionCard>
      <SectionCard icon={Cloud} title="سجل المزامنة">
        <div className="max-h-[360px] space-y-2 overflow-y-auto p-4">
          {!status.operations.length && (
            <p className="py-5 text-center text-sm text-ink-faint">لا توجد عمليات محلية لهذا الحساب.</p>
          )}
          {status.operations.map((operation) => (
            <article
              key={operation.id}
              className="rounded-control border border-line bg-white/80 p-3 text-sm"
            >
              <div className="flex justify-between gap-3">
                <p className="font-semibold text-ink">
                  {operation.kind === "finance"
                    ? "مسودة مالية — بدون أثر على الأرصدة"
                    : operation.kind === "hr"
                      ? "الموارد البشرية"
                      : operation.reserved
                        ? "بيع من حصة الجهاز"
                        : "بيع للمورد"}{" "}
                  — {operation.label}
                </p>
                <span className="text-xs text-violet">{labels[operation.status]}</span>
              </div>
              <p className="mt-2 text-xs text-ink-soft">
                {operation.kind === "hr"
                  ? operation.status === "done"
                    ? "تم التأكيد المركزي"
                    : operation.status === "cancelled"
                      ? "أُلغي الطلب المحلي المرفوض"
                      : "بانتظار التأكيد المركزي"
                  : formatIqd(operation.total)}{" "}
                · {new Date(operation.createdAt).toLocaleString("ar-IQ")}
              </p>
              <p dir="ltr" className="mt-1 truncate text-left text-[10px] text-ink-faint">
                {operation.invoiceNo ?? operation.id}
              </p>
              {operation.localInvoiceNo && (
                <p dir="ltr" className="mt-1 truncate text-left text-[10px] text-violet">
                  {operation.localInvoiceNo}
                </p>
              )}
              {operation.error && <p className="mt-2 text-xs text-danger">{operation.error}</p>}
              {operation.kind === "pos" && (
                <button
                  type="button"
                  className="mt-2 me-4 text-xs font-semibold text-violet"
                  onClick={() =>
                    void window.finoraDesktop?.offline
                      ?.printPosSale(operation.id)
                      .catch((error: unknown) =>
                        toast.error(String(error instanceof Error ? error.message : error)),
                      )
                  }
                >
                  طباعة الإيصال المحلي
                </button>
              )}
              {operation.status === "conflict" && (
                <button
                  type="button"
                  disabled={!online || sync.isPending || status.syncing}
                  onClick={() => sync.mutate(operation.id)}
                  className="mt-2 text-xs font-semibold text-violet disabled:opacity-45"
                >
                  إعادة التحقق بنفس المعرّف
                </button>
              )}
              {operation.canDiscard && (
                <button
                  type="button"
                  disabled={discard.isPending || status.syncing}
                  onClick={() => discard.mutate(operation.id)}
                  className="ms-4 mt-2 text-xs font-semibold text-ink-soft disabled:opacity-45"
                >
                  إلغاء الطلب المرفوض
                </button>
              )}
            </article>
          ))}
        </div>
      </SectionCard>
      {discard.error && (
        <p className="text-xs text-danger" role="alert">
          {String(discard.error instanceof Error ? discard.error.message : discard.error)}
        </p>
      )}
    </>
  );
}
