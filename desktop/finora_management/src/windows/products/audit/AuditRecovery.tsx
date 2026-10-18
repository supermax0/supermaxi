import { useState } from "react";
import { finora, toFinoraError } from "@/api/finora";
import type { AuditCommandResult } from "@/api/finora/inventoryAudit";
import { FeatureHelp } from "@/components/FeatureHelp";
import type { z } from "zod";
import type { auditLocalSchema } from "@shared/inventoryAudit";
import { auditButton } from "./auditUi";

export function AuditRecovery({
  status,
  busy,
  onWorking,
  onRecovered,
  onRefresh,
}: {
  status: z.infer<typeof auditLocalSchema> | undefined;
  busy: boolean;
  onWorking(value: boolean): void;
  onRecovered(result: AuditCommandResult, key: string, action: string): void;
  onRefresh(): Promise<void>;
}) {
  const [reason, setReason] = useState(""),
    [error, setError] = useState<string | null>(null);
  const act = async (key: string, action: string, discard = false) => {
    if (busy) return;
    setError(null);
    onWorking(true);
    try {
      if (discard) await finora.inventoryAudit.discardLocal(key, reason);
      else {
        const result = await finora.inventoryAudit.retryLocal(key);
        onRecovered(result, key, action);
      }
      await onRefresh();
    } catch (problem) {
      setError(toFinoraError(problem).message);
    } finally {
      onWorking(false);
    }
  };
  if (!status?.available || (!status.offline && !status.items.length)) return null;
  return (
    <section
      className="max-h-52 shrink-0 overflow-y-auto rounded-panel border border-amber-200 bg-amber-50/80 p-3"
      aria-label="مزامنة الجرد"
    >
      <div className="flex items-center gap-2">
        <p className="text-sm font-semibold text-amber-800">
          {status.offline ? "لقطة الجرد المحلية · بدون اتصال" : "عمليات الجرد المحفوظة"}
        </p>
        <FeatureHelp text="العد المحلي محفوظ ومؤرخ ومشفر على هذا الجهاز. المزامنة تعيد نفس معرف العملية وتتحقق من حركات الخادم. تعارض الحركة يحتاج إسقاط العد القديم بسبب موثق ثم إعادة العد؛ الاعتماد والترحيل يتطلبان اتصالاً حياً." />
      </div>
      {status.offline && (
        <p className="mt-1 text-xs leading-5 text-amber-800">
          {status.prepared_records} صنف مُنزّل. الأرقام تخص اللقطة؛ لا تتحدث تلقائياً أثناء انقطاع الاتصال.
        </p>
      )}
      {!!status.items.length && (
        <div className="mt-2 max-h-36 space-y-2 overflow-auto">
          {status.items.map((item) => (
            <div
              key={item.key}
              className="flex flex-wrap items-center justify-between gap-2 rounded-control border border-amber-200/60 bg-white/80 p-2 text-xs"
            >
              <p className="min-w-0 flex-1 leading-5">
                {item.action === "save_offline_count"
                  ? "عد محلي"
                  : item.action === "create"
                    ? "إنشاء جلسة"
                    : item.action === "prepare_offline"
                      ? "تنزيل لقطة"
                      : "طلب جرد"}{" "}
                · {item.session_id ? `جلسة #${item.session_id}` : "جلسة جديدة"}
                {item.line_id ? ` · صنف #${item.line_id}` : ""}
                <span className="ms-1 font-semibold">
                  {
                    {
                      pending: "بانتظار المزامنة",
                      uncertain: "نتيجة غير مؤكدة",
                      confirmed: "مؤكد؛ يحتاج إغلاقاً محلياً",
                      conflict: "تعارض؛ أعد العد",
                    }[item.state]
                  }
                </span>
                {item.error && <span className="block text-red-700">{item.error}</span>}
              </p>
              <button
                type="button"
                disabled={busy}
                onClick={() => void act(item.key, item.action)}
                className={`${auditButton} min-h-10 text-xs`}
              >
                {item.state === "pending" ? "مزامنة العد" : "تأكيد نفس الطلب"}
              </button>
              {["pending", "conflict"].includes(item.state) && (
                <button
                  type="button"
                  disabled={busy || !reason.trim()}
                  onClick={() => void act(item.key, item.action, true)}
                  className={`${auditButton} min-h-10 text-xs`}
                >
                  إسقاط العد القديم
                </button>
              )}
            </div>
          ))}
        </div>
      )}
      {status.items.some((item) => ["pending", "conflict"].includes(item.state)) && (
        <input
          aria-label="سبب إسقاط العد المحلي"
          value={reason}
          maxLength={2000}
          onChange={(event) => setReason(event.target.value)}
          disabled={busy}
          placeholder="سبب الإسقاط؛ العدد السابق يبقى في السجل المحلي"
          className="mt-2 h-10 w-full rounded-control border border-amber-200 bg-white px-3 text-xs outline-none"
        />
      )}
      {error && (
        <p role="alert" className="mt-2 text-sm text-red-700">
          {error}
        </p>
      )}
    </section>
  );
}
