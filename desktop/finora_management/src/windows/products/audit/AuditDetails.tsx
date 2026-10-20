import { useTimeFormat } from "@/stores/displayTime";
import { auditRequired } from "@shared/inventoryAudit";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { ExternalLink, RefreshCw, SearchCheck } from "lucide-react";
import { useState } from "react";
import { finora, toFinoraError } from "@/api/finora";
import type { AuditCommand, AuditCommandResult, AuditLine, AuditSession } from "@/api/finora/inventoryAudit";
import { FeatureHelp } from "@/components/FeatureHelp";
import { ProductThumb } from "@/components/ProductThumb";
import { auditImageUrl, auditActionLabels, auditMovementLabels } from "./auditUi";
import { formatNumber, formatDateTime } from "@/utils/format";
import { useWindowManager } from "@/stores/windowManager";
import { useOrderNavigation } from "@/stores/orderNavigation";
import { AuditSheet } from "./AuditSheet";
import { hasDesktopBridge } from "@/services/bridge";
import { toast } from "@/stores/toasts";

const labels: Record<string, string> = {
  locations: "المواقع",
  transfers: "التحويلات",
  orders: "الطلبات والفواتير",
  purchases: "المشتريات",
  courier_custody: "عهد المندوبين",
  serials: "الأرقام التسلسلية",
};
const coverage: Record<string, string> = {
  checked: "تم الفحص",
  incomplete: "العد غير مكتمل",
  limited: "نتائج جزئية؛ راجع باقي السجل",
  restricted: "يحتاج صلاحية عرض المستندات",
  checked_recent: "فحص أحدث المستندات؛ لا يثبت التسليم الفعلي",
  no_signed_custody_registry: "المصدر يربط الطلب بالمندوب؛ لا يوفر إثبات عهدة مستقل",
  not_available: "غير مسجل في مصدر المخزون الحالي",
};
export function AuditDetails({
  session,
  scope,
  line,
  serverUrl,
  permissions,
  busy,
  commandError,
  onClose,
  onCommand,
}: {
  session: AuditSession;
  scope: string;
  line: AuditLine | null;
  serverUrl: string | null;
  permissions: string[];
  busy: boolean;
  commandError: string | null;
  onClose(): void;
  onCommand(
    data: Omit<AuditCommand, "idempotency_key">,
    complete?: (result: AuditCommandResult) => void,
  ): void;
}) {
  useTimeFormat();
  const [transferPeer, setTransferPeer] = useState(""),
    [transferQty, setTransferQty] = useState(""),
    [transferAck, setTransferAck] = useState(false),
    [transfer, setTransfer] = useState<AuditCommandResult | null>(null);
  const [tab, setTab] = useState("analysis"),
    [reason, setReason] = useState(""),
    [historyPage, setHistoryPage] = useState(1);
  const detail = useQuery({
    queryKey: ["inventory-audit", "details", scope, session.id, line?.id],
    queryFn: () => finora.inventoryAudit.detail(session.id, auditRequired(line).id),
    enabled: line !== null,
  });
  const moves = useInfiniteQuery({
    queryKey: ["inventory-audit", "movements", scope, session.id, line?.id],
    initialPageParam: null as number | null,
    queryFn: ({ pageParam }) =>
      finora.inventoryAudit.movements(session.id, auditRequired(line).id, pageParam ?? undefined),
    getNextPageParam: (page) => page.next_before_id ?? undefined,
    enabled: line !== null && tab === "movement" && permissions.includes("inventory.audit.investigate"),
  });
  const history = useQuery({
    queryKey: ["inventory-audit", "history", scope, session.id, line?.id, historyPage],
    queryFn: () => finora.inventoryAudit.history(session.id, auditRequired(line).id, historyPage),
    enabled: line !== null && tab === "info",
  });
  const selected = detail.data?.line ?? line;
  const analysis = detail.data?.investigation;
  return (
    <AuditSheet open={line !== null} title="تفاصيل المنتج بالجرد" onClose={onClose}>
      {commandError && (
        <p role="alert" className="mb-3 rounded-control bg-red-50 p-3 text-sm text-danger">
          {commandError}
        </p>
      )}
      {selected && (
        <>
          <div className="flex gap-3 rounded-panel border border-line bg-white/80 p-3">
            <ProductThumb src={auditImageUrl(selected.product.image_url, serverUrl)} size={64} />
            <div className="min-w-0">
              <h3 className="font-semibold">{selected.product.name}</h3>
              <p className="text-sm text-ink-soft">{selected.product.variant_name}</p>
              <p className="mt-1 text-xs text-ink-soft ltr-isolate">
                SKU: {selected.product.sku} · {selected.product.barcode}
              </p>
              <p className="mt-1 text-xs text-ink-soft">
                {session.locations.find((loc) => loc.key === selected.location_key)?.name}
              </p>
              {permissions.includes("can_manage_inventory") && (
                <button
                  type="button"
                  className="mt-2 inline-flex min-h-9 items-center gap-1 text-xs text-violet"
                  onClick={() => {
                    void finora.inventoryAudit
                      .openSource("product", selected.product.id)
                      .catch((problem) => toast.error(toFinoraError(problem).message));
                  }}
                >
                  عرض بطاقة المنتج <ExternalLink size={13} />
                </button>
              )}
            </div>
          </div>
          <div
            role="tablist"
            aria-label="تفاصيل الجرد"
            className="my-3 grid grid-cols-3 gap-1 rounded-control bg-violet-soft/50 p-1"
          >
            {[
              ["analysis", "التحليل الذكي"],
              ["movement", "حركة المخزون"],
              ["info", "المعلومات والسجل"],
            ].map(([value, label]) => (
              <button
                key={value}
                role="tab"
                aria-selected={tab === value}
                type="button"
                onClick={() => setTab(value ?? "analysis")}
                className={`min-h-11 rounded-control px-1 text-xs ${tab === value ? "bg-white font-semibold text-violet shadow-control" : "text-ink-soft"}`}
              >
                {label}
              </button>
            ))}
          </div>
          {detail.error && (
            <p role="alert" className="text-sm text-danger">
              {toFinoraError(detail.error).message}
            </p>
          )}
          {tab === "analysis" && (
            <div className="space-y-3">
              <div className="grid grid-cols-3 gap-2 rounded-panel bg-surface-sunken p-3 text-center">
                {[
                  ["رصيد النظام", selected.expected_quantity],
                  ["العدد الفعلي", selected.counted_quantity],
                  ["الفرق", selected.difference],
                ].map(([name, value]) => (
                  <div key={String(name)}>
                    <p className="text-xs text-ink-soft">{name}</p>
                    <p className="mt-2 text-xl font-semibold ltr-isolate">
                      {value === null ? "—" : formatNumber(Number(value))}
                    </p>
                  </div>
                ))}
              </div>
              <div className="flex items-center gap-2">
                <FeatureHelp
                  label="شرح التحقيق"
                  text="التحقيق يبحث بسجلات فعلية. تطابق زيادة ونقص أو تأخر دفع فاتورة قرينة تحتاج تحقق، ولا يغيّر المخزون تلقائياً."
                />
                {permissions.includes("inventory.audit.investigate") &&
                  permissions.includes("inventory.audit.system") && (
                    <button
                      type="button"
                      disabled={busy || selected.counted_quantity === null || session.status === "posted"}
                      onClick={() => onCommand({ action: "investigate", line_id: selected.id })}
                      className="flex min-h-10 items-center gap-2 rounded-control bg-violet-soft px-3 text-sm text-violet"
                    >
                      <SearchCheck size={16} /> فحص الأدلة
                    </button>
                  )}
              </div>
              {detail.data?.investigation_stale && (
                <p role="status" className="rounded-control bg-amber-50 p-3 text-sm text-amber-700">
                  تغيّرت بيانات المخزون بعد التحقيق؛ أعد الفحص أو العد.
                </p>
              )}
              {analysis ? (
                <>
                  <p className="rounded-panel border border-line p-3 text-sm">{analysis.message}</p>
                  <section className="rounded-panel border border-line p-3">
                    <h4 className="mb-2 text-sm font-semibold">المواقع الأخرى</h4>
                    {analysis.comparisons.map((peer) => (
                      <div
                        key={peer.line_id}
                        className="flex justify-between border-t border-line/60 py-2 text-xs"
                      >
                        <span>
                          {session.locations.find((loc) => loc.key === peer.location_key)?.name ??
                            peer.location_key}
                        </span>
                        <span className="ltr-isolate">
                          {peer.observed
                            ? `${peer.counted_quantity} / ${peer.system_quantity} (${auditRequired(peer.difference) > 0 ? "+" : ""}${peer.difference})`
                            : "غير مكتمل أو يحتاج إعادة عد"}
                        </span>
                      </div>
                    ))}
                    <p className="mt-2 text-xs leading-5 text-ink-soft">{analysis.company_comparison.note}</p>
                  </section>
                  {analysis.evidence.map((evidence, index) => (
                    <section key={index} className="rounded-panel border border-line bg-azure/5 p-3">
                      <p className="text-sm leading-6">{evidence.message}</p>
                      {evidence.references.map((ref, i) => (
                        <div key={i} className="mt-2 rounded-control bg-white p-2 text-xs">
                          <div className="flex justify-between gap-2">
                            <span>
                              {ref.number
                                ? `#${ref.number}`
                                : ref.location_key
                                  ? (session.locations.find((loc) => loc.key === ref.location_key)?.name ??
                                    ref.location_key)
                                  : "مرجع مرتبط"}
                            </span>
                            <span>
                              {ref.quantity !== undefined ? `${formatNumber(ref.quantity)} قطعة` : ""}
                            </span>
                          </div>
                          <p className="mt-1 text-ink-soft">
                            {[ref.status, ref.payment_status, ref.agent_name].filter(Boolean).join(" · ")}
                          </p>
                          {ref.kind === "purchase" && ref.id && (
                            <button
                              type="button"
                              onClick={() => {
                                void finora.inventoryAudit
                                  .openSource("purchase", auditRequired(ref.id))
                                  .catch((problem) => toast.error(toFinoraError(problem).message));
                              }}
                              className="mt-1 inline-flex min-h-8 items-center gap-1 text-violet"
                            >
                              <ExternalLink size={12} />
                              فتح الشراء
                            </button>
                          )}
                          {ref.kind === "stock_transfer" && ref.id && (
                            <button
                              type="button"
                              onClick={() => {
                                void finora.inventoryAudit
                                  .openSource("branch_transfer", auditRequired(ref.id))
                                  .catch((problem) => toast.error(toFinoraError(problem).message));
                              }}
                              className="mt-1 inline-flex min-h-8 items-center gap-1 text-violet"
                            >
                              <ExternalLink size={12} />
                              مراجعة التحويل
                            </button>
                          )}
                          {ref.kind === "invoice" && ref.id && (
                            <button
                              type="button"
                              onClick={() => {
                                if (hasDesktopBridge()) {
                                  onClose();
                                  useOrderNavigation.getState().open(auditRequired(ref.id));
                                  useWindowManager.getState().open("orders");
                                } else
                                  void finora.inventoryAudit
                                    .openSource("invoice", auditRequired(ref.id))
                                    .catch((problem) => toast.error(toFinoraError(problem).message));
                              }}
                              className="mt-1 inline-flex items-center gap-1 text-violet"
                            >
                              <ExternalLink size={12} /> فتح الطلب
                            </button>
                          )}
                        </div>
                      ))}
                    </section>
                  ))}
                  {permissions.includes("inventory.audit.review") &&
                    permissions.includes("can_manage_inventory") &&
                    permissions.includes("edit_current_stock") &&
                    ["counting", "pending_review"].includes(session.status) &&
                    analysis.evidence.some((e) => e.kind === "opposite_count") && (
                      <section className="space-y-2 rounded-panel border border-line p-3">
                        <h4 className="text-sm font-semibold">طلب مراجعة تحويل غير مسجل</h4>
                        <p className="text-xs leading-6 text-ink-soft">
                          أنشئ مسودة بعد مراجعة الدليل. المسودة لا تحرك الرصيد ولا تثبت الانتقال؛ أكمل المستند
                          أو ألغِه وأعد العد قبل ترحيل الجرد.
                        </p>
                        <select
                          aria-label="الموقع المقابل للتحويل"
                          value={transferPeer}
                          onChange={(event) => {
                            setTransferPeer(event.target.value);
                            const peer = analysis.evidence
                              .flatMap((e) => e.references)
                              .find((ref) => String(ref.line_id) === event.target.value);
                            setTransferQty(String(peer?.quantity ?? ""));
                            setTransferAck(false);
                          }}
                          className="h-11 w-full rounded-control border border-line bg-white px-2 text-xs"
                        >
                          <option value="">اختر الموقع المقابل</option>
                          {analysis.evidence
                            .filter((e) => e.kind === "opposite_count")
                            .flatMap((e) => e.references)
                            .map((ref) => (
                              <option key={ref.line_id} value={ref.line_id}>
                                {session.locations.find((loc) => loc.key === ref.location_key)?.name ??
                                  ref.location_key}{" "}
                                · {ref.quantity} قطعة
                              </option>
                            ))}
                        </select>
                        <input
                          aria-label="كمية مسودة التحويل"
                          value={transferQty}
                          onChange={(event) => setTransferQty(event.target.value)}
                          inputMode="numeric"
                          className="h-11 w-full rounded-control border border-line px-3 text-sm"
                        />
                        <textarea
                          aria-label="سبب مسودة التحويل"
                          value={reason}
                          onChange={(event) => setReason(event.target.value)}
                          rows={2}
                          maxLength={2000}
                          className="w-full rounded-control border border-line bg-white p-2 text-sm"
                          placeholder="الدليل الذي يحتاج مراجعة"
                        />
                        <label className="flex items-start gap-2 text-xs leading-6">
                          <input
                            type="checkbox"
                            checked={transferAck}
                            onChange={(event) => setTransferAck(event.target.checked)}
                            className="mt-1"
                          />
                          راجعت القرينة وأطلب مسودة للمراجعة؛ أفهم أن الأعداد المتعاكسة ليست إثبات انتقال.
                        </label>
                        <button
                          type="button"
                          disabled={
                            busy ||
                            selected.conflict ||
                            !transferPeer ||
                            !/^\d+$/.test(transferQty) ||
                            Number(transferQty) < 1 ||
                            !reason.trim() ||
                            !transferAck ||
                            transfer !== null
                          }
                          onClick={() =>
                            onCommand(
                              {
                                action: "transfer_draft",
                                line_id: selected.id,
                                version: selected.version,
                                target_line_id: Number(transferPeer),
                                quantity: Number(transferQty),
                                reason,
                                acknowledge_draft: true,
                              },
                              (result) => {
                                setTransfer(result);
                                toast.success("تم إنشاء مسودة تحويل للمراجعة؛ المخزون لم يتغير");
                              },
                            )
                          }
                          className="min-h-11 w-full rounded-control bg-violet-soft px-3 text-sm text-violet disabled:opacity-50"
                        >
                          إنشاء مسودة التحويل للمراجعة
                        </button>
                        {transfer?.transfer_id && (
                          <button
                            type="button"
                            onClick={() => {
                              void finora.inventoryAudit
                                .openSource(
                                  transfer.transfer_kind === "warehouse"
                                    ? "warehouse_transfer"
                                    : "branch_transfer",
                                  auditRequired(transfer.transfer_id),
                                )
                                .catch((problem) => toast.error(toFinoraError(problem).message));
                            }}
                            className="min-h-10 text-xs text-violet"
                          >
                            فتح مسودة التحويل #{transfer.transfer_id}
                          </button>
                        )}
                      </section>
                    )}
                  <section className="rounded-panel border border-line p-3">
                    <h4 className="text-sm font-semibold">نطاق الفحص</h4>
                    {Object.entries(analysis.coverage).map(([key, value]) => (
                      <p key={key} className="mt-2 text-xs leading-5 text-ink-soft">
                        {labels[key] ?? key}: {coverage[value] ?? value}
                      </p>
                    ))}
                  </section>
                </>
              ) : (
                <p className="text-sm leading-6 text-ink-soft">
                  شغّل فحص الأدلة لعرض المقارنة والحركات والمستندات المتاحة.
                </p>
              )}
              {permissions.includes("inventory.audit.review") &&
                selected.counted_quantity !== null &&
                selected.difference !== 0 &&
                selected.difference !== null &&
                ["counting", "pending_review"].includes(session.status) && (
                  <section className="rounded-panel border border-line p-3">
                    <div className="flex items-center gap-2">
                      <h4 className="text-sm font-semibold">نتيجة مراجعة المسؤول</h4>
                      <FeatureHelp text="تسجيل السبب لا يغيّر الرصيد. الترحيل منفصل بعد اعتماد الجلسة؛ الفرق غير المفسر يمنع الاعتماد حتى التحقق." />
                    </div>
                    <textarea
                      aria-label="سبب فرق الجرد"
                      value={reason}
                      onChange={(event) => setReason(event.target.value)}
                      maxLength={2000}
                      rows={2}
                      className="mt-2 w-full rounded-control border border-line bg-white p-2 text-sm"
                    />
                    <div className="mt-2 flex flex-wrap gap-2">
                      {[
                        [selected.difference < 0 ? "loss" : "surplus", "تثبيت سبب التسوية"],
                        ["unexplained", "غير مفسر؛ يحتاج متابعة"],
                      ].map(([resolution, label]) => (
                        <button
                          key={resolution}
                          type="button"
                          disabled={busy || !reason.trim() || selected.conflict}
                          onClick={() =>
                            onCommand({
                              action: "review_line",
                              line_id: selected.id,
                              version: selected.version,
                              resolution: resolution as "loss" | "surplus" | "unexplained",
                              reason,
                            })
                          }
                          className="min-h-10 rounded-control bg-violet-soft px-3 text-xs text-violet disabled:opacity-50"
                        >
                          {label}
                        </button>
                      ))}
                    </div>
                  </section>
                )}
            </div>
          )}
          {tab === "movement" && (
            <div className="space-y-2">
              {!permissions.includes("inventory.audit.investigate") && (
                <p className="text-sm text-ink-soft">عرض الحركات يحتاج صلاحية التحقيق.</p>
              )}
              {moves.error && (
                <p role="alert" className="text-sm text-danger">
                  {toFinoraError(moves.error).message}
                </p>
              )}
              {moves.isLoading && <p className="text-sm text-ink-soft">جارٍ تحميل الحركات…</p>}
              {moves.data?.pages
                .flatMap((page) => page.items)
                .map((move) => (
                  <div key={move.id} className="rounded-panel border border-line p-3 text-sm">
                    <div className="flex justify-between gap-2">
                      <span>{auditMovementLabels[move.kind] ?? "حركة مخزون"}</span>
                      <strong className="ltr-isolate">
                        {move.quantity > 0 ? "+" : ""}
                        {formatNumber(move.quantity)}
                      </strong>
                    </div>
                    <p className="mt-1 text-xs text-ink-soft">
                      {formatDateTime(move.created_at)} ·{" "}
                      {move.before === null ? "رصيد قبل/بعد غير مثبت" : `${move.before} ← ${move.after}`}
                    </p>
                    <p className="mt-1 text-xs">{move.reason}</p>
                  </div>
                ))}
              {moves.data?.pages[0]?.items.length === 0 && (
                <p className="text-sm text-ink-soft">لا توجد حركات مفصلة في مصدر الصنف.</p>
              )}
              {moves.hasNextPage && (
                <button
                  type="button"
                  disabled={moves.isFetchingNextPage}
                  onClick={() => void moves.fetchNextPage()}
                  className="min-h-10 rounded-control border border-line px-3 text-xs"
                >
                  تحميل الحركات الأقدم
                </button>
              )}
            </div>
          )}
          {tab === "info" && (
            <div className="space-y-3">
              <section className="rounded-panel border border-line p-3 text-sm">
                <p>{selected.product.model}</p>
                <p>الوحدة: {selected.product.unit}</p>
                {selected.product.unit_cost !== undefined && (
                  <p>تكلفة الوحدة: {formatNumber(selected.product.unit_cost)} د.ع</p>
                )}
                <p className="mt-2 text-xs text-ink-soft">
                  آخر عد: {selected.counted_at ? formatDateTime(selected.counted_at) : "لم يثبت العد"}
                </p>
              </section>
              <h4 className="text-sm font-semibold">سجل العد والمراجعة</h4>
              {permissions.includes("inventory.audit.review") && session.status === "counting" && (
                <section className="rounded-panel border border-line p-3">
                  <label className="text-xs text-ink-soft">
                    سبب الاستبعاد أو إغلاق إدخال مفتوح
                    <textarea
                      aria-label="سبب قرار الجرد"
                      value={reason}
                      onChange={(event) => setReason(event.target.value)}
                      maxLength={2000}
                      rows={2}
                      className="mt-1 w-full rounded-control border border-line bg-white p-2 text-sm"
                    />
                  </label>
                  <div className="mt-2 flex flex-wrap gap-2">
                    <button
                      type="button"
                      disabled={busy || !reason.trim()}
                      onClick={() =>
                        onCommand({
                          action: "exclude",
                          line_id: selected.id,
                          version: selected.version,
                          excluded: !selected.excluded,
                          reason,
                        })
                      }
                      className="min-h-10 rounded-control border border-line px-3 text-xs"
                    >
                      {selected.excluded ? "إعادة الصنف للجرد" : "استبعاد الصنف بسبب موثق"}
                    </button>
                    {selected.count_open && (
                      <button
                        type="button"
                        disabled={busy || !reason.trim()}
                        onClick={() =>
                          onCommand({
                            action: "release_ticket",
                            line_id: selected.id,
                            version: selected.version,
                            reason,
                          })
                        }
                        className="min-h-10 rounded-control border border-line px-3 text-xs"
                      >
                        إغلاق الإدخال المفتوح بمراجعة المسؤول
                      </button>
                    )}
                  </div>
                </section>
              )}
              {history.data?.items.map((event) => (
                <div key={event.id} className="rounded-panel border border-line p-3 text-xs">
                  <strong>{event.actor_name}</strong>
                  <span className="ms-2 text-ink-soft">{formatDateTime(event.created_at)}</span>
                  <p className="mt-1">
                    {auditActionLabels[event.action] ?? "إجراء جرد"}
                    {event.detail.before !== undefined
                      ? ` · ${String(event.detail.before ?? "غير مجرود")} ← ${String(event.detail.after)}`
                      : ""}
                  </p>
                  <p className="mt-1 text-ink-soft">
                    {String(event.detail.reason ?? event.detail.notes ?? "")}
                  </p>
                </div>
              ))}
              {history.data && (
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    disabled={historyPage === 1}
                    onClick={() => setHistoryPage(historyPage - 1)}
                    className="rounded-control border border-line px-3 py-2 text-xs"
                  >
                    الأحدث
                  </button>
                  <span className="text-xs">{historyPage}</span>
                  <button
                    type="button"
                    disabled={historyPage * 30 >= history.data.total}
                    onClick={() => setHistoryPage(historyPage + 1)}
                    className="rounded-control border border-line px-3 py-2 text-xs"
                  >
                    الأقدم
                  </button>
                </div>
              )}
            </div>
          )}
        </>
      )}
      {!selected && <RefreshCw className="animate-spin text-violet" size={20} />}
    </AuditSheet>
  );
}
