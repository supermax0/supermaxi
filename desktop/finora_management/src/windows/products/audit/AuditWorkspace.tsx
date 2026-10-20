import { useTimeFormat } from "@/stores/displayTime";
import { auditRequired } from "@shared/inventoryAudit";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowUp,
  Check,
  ClipboardCheck,
  History,
  Minus,
  Plus,
  RefreshCw,
  Search,
  X,
  Link,
  ExternalLink,
  Pause,
  Play,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { finora, toFinoraError } from "@/api/finora";
import type { AuditCommand, AuditCommandResult, AuditLine, AuditSession } from "@/api/finora/inventoryAudit";
import { FeatureHelp } from "@/components/FeatureHelp";
import { ProductThumb } from "@/components/ProductThumb";
import { TablePagination } from "@/components/TablePagination";
import { useBarcodeScanner } from "@/hooks/useBarcodeScanner";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { toast } from "@/stores/toasts";
import { formatNumber, formatDateTime } from "@/utils/format";
import { AuditDetails } from "./AuditDetails";
import { AuditSheet } from "./AuditSheet";
import { AuditRecovery } from "./AuditRecovery";
import { AuditCamera } from "./AuditCamera";
import { ScanLine } from "lucide-react";
import { hasDesktopBridge } from "@/services/bridge";
import { useSession } from "@/stores/session";

import { auditButton, auditPrimary, auditImageUrl } from "./auditUi";

const input =
  "h-11 min-w-0 rounded-control border border-line bg-white px-3 text-sm text-ink outline-none focus:ring-2 focus:ring-violet/30";
const states: Record<string, string> = {
  counting: "قيد الجرد",
  paused: "متوقف مؤقتاً",
  pending_review: "بانتظار المراجعة",
  approved: "معتمد",
  posted: "مرحّل",
  matched: "مطابق",
  shortage: "نقص",
  surplus: "زيادة",
  uncounted: "غير مجرود",
  counted: "تم العد",
  conflict: "أعد العد",
  excluded: "مستبعد",
};
const stateTone = (status: string) =>
  status === "shortage" || status === "conflict"
    ? "bg-red-50 text-red-600"
    : status === "matched" || status === "posted"
      ? "bg-emerald-50 text-emerald-700"
      : status === "surplus"
        ? "bg-blue-50 text-blue-600"
        : "bg-violet-soft text-violet";
const number = (value: number | null | undefined) => (value == null ? "—" : formatNumber(value));
interface Entry {
  line: AuditLine;
  ticket: AuditCommandResult | null;
  quantity: string;
  notes: string;
  origin: "search" | "row";
  saved: boolean;
}
interface Attempt {
  id: number;
  data: AuditCommand;
  complete?: (result: AuditCommandResult) => void;
}

function Quantity({
  value,
  onChange,
  disabled,
  label = "العدد الفعلي",
}: {
  value: string;
  onChange(value: string): void;
  disabled: boolean;
  label?: string;
}) {
  useTimeFormat();
  return (
    <div
      className="flex min-h-11 items-center overflow-hidden rounded-control border border-line bg-white"
      dir="ltr"
    >
      <button
        type="button"
        aria-label="تقليل العدد"
        disabled={disabled || !/^\d+$/.test(value) || Number(value) === 0}
        onClick={() => onChange(String(Math.max(0, Number(value) - 1)))}
        className="grid h-11 w-11 shrink-0 place-items-center text-violet disabled:opacity-40"
      >
        <Minus size={17} />
      </button>
      <input
        type="text"
        inputMode="numeric"
        aria-label={label}
        value={value}
        disabled={disabled}
        onChange={(event) =>
          onChange(
            event.target.value.replace(/[٠-٩۰-۹]/g, (char) =>
              String(char.charCodeAt(0) - (char.charCodeAt(0) >= 0x6f0 ? 0x6f0 : 0x660)),
            ),
          )
        }
        className="h-11 min-w-0 flex-1 border-x border-line bg-transparent text-center text-base font-semibold outline-none"
      />
      <button
        type="button"
        aria-label="زيادة العدد"
        disabled={disabled || !/^\d+$/.test(value) || Number(value) >= 1_000_000_000}
        onClick={() => onChange(String(Number(value) + 1))}
        className="grid h-11 w-11 shrink-0 place-items-center text-violet disabled:opacity-40"
      >
        <Plus size={17} />
      </button>
    </div>
  );
}

export function AuditWorkspace({
  serverUrl,
  scope,
  initialView = "count",
  initialSessionId = null,
  active = true,
  onBusyChange,
}: {
  serverUrl: string | null;
  scope: string;
  initialView?: "count" | "history";
  initialSessionId?: number | null;
  active?: boolean;
  onBusyChange?(value: boolean): void;
}) {
  useTimeFormat();
  const queryClient = useQueryClient();
  const [cameraOpen, setCameraOpen] = useState(false),
    [scanMode, setScanMode] = useState<"select" | "count">("select");
  const scanning = useRef(false),
    lastScan = useRef({ code: "", time: 0 });
  const [view, setView] = useState(initialView),
    [sessionId, setSessionId] = useState<number | null>(initialSessionId),
    [historyPage, setHistoryPage] = useState(1);
  const [createOpen, setCreateOpen] = useState(false),
    [kind, setKind] = useState<"branch" | "warehouse">("branch"),
    [locationKeys, setLocationKeys] = useState<string[]>([]),
    [title, setTitle] = useState("");
  const [pageSize, setPageSize] = useState(25),
    [historySize, setHistorySize] = useState(25);
  const [location, setLocation] = useState(""),
    [search, setSearch] = useState(""),
    [filter, setFilter] = useState("all"),
    [page, setPage] = useState(1);
  const [entry, setEntry] = useState<Entry | null>(null),
    [details, setDetails] = useState<AuditLine | null>(null),
    [reviewOpen, setReviewOpen] = useState(false);
  const [partial, setPartial] = useState(false),
    [reason, setReason] = useState("");
  const [checkValuation, setCheckValuation] = useState(false),
    [reconcileValuation, setReconcileValuation] = useState(false);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState<string | null>(null),
    [uncertain, setUncertain] = useState(false);
  const attempt = useRef<Attempt | null>(null),
    createKey = useRef<string | null>(null),
    searchRef = useRef<HTMLInputElement>(null),
    scrollRef = useRef<HTMLDivElement>(null);
  const editorRef = useRef<HTMLDivElement>(null),
    linkRef = useRef<HTMLInputElement>(null);
  const [linkOpen, setLinkOpen] = useState(false);
  const auditLink = `${serverUrl?.replace(/\/$/, "") ?? window.location.origin}/inventory/smart-audit${sessionId ? `?session=${sessionId}` : ""}`;
  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(auditLink);
      toast.success("تم نسخ رابط الجرد");
    } catch {
      linkRef.current?.focus();
      linkRef.current?.select();
      toast.info("الرابط محدد؛ اضغط Ctrl+C لنسخه");
    }
  };
  const searchValue = useDebouncedValue(search, 250);
  const [downloadProgress, setDownloadProgress] = useState<string | null>(null);
  const stopDownload = useRef(false);
  const createPayload = useRef<Parameters<typeof finora.inventoryAudit.create>[0] | null>(null);
  const local = useQuery({
    queryKey: ["inventory-audit", "local", scope],
    queryFn: () => finora.inventoryAudit.localStatus(),
    enabled: active,
    refetchInterval: 5000,
  });
  const meta = useQuery({
    queryKey: ["inventory-audit", "meta", scope],
    queryFn: () => finora.inventoryAudit.meta(),
    enabled: active,
  });
  const can = (permission: string) => meta.data?.permissions.includes(permission) ?? false;
  const sessions = useQuery({
    queryKey: ["inventory-audit", "sessions", scope, historyPage, historySize],
    queryFn: () => finora.inventoryAudit.sessions(historyPage, "", historySize),
    enabled: active && (view === "history" || sessionId === null),
  });
  const current = useQuery({
    queryKey: ["inventory-audit", "session", scope, sessionId],
    queryFn: () => finora.inventoryAudit.get(auditRequired(sessionId)),
    enabled: active && sessionId !== null,
  });
  const valuation = useQuery({
    queryKey: ["inventory-audit", "valuation", scope, sessionId, current.data?.version],
    queryFn: () => finora.inventoryAudit.valuation(auditRequired(sessionId)),
    enabled:
      active &&
      reviewOpen &&
      checkValuation &&
      current.data?.ledger_kind === "branch" &&
      current.data.status !== "posted" &&
      can("inventory.audit.cost") &&
      can("inventory.audit.system"),
    staleTime: 0,
  });
  useEffect(() => {
    setReconcileValuation(false);
  }, [valuation.data?.fingerprint, sessionId]);
  const list = useQuery({
    queryKey: ["inventory-audit", "lines", scope, sessionId, location, filter, page, pageSize],
    queryFn: () =>
      finora.inventoryAudit.lines(auditRequired(sessionId), {
        location_key: location || undefined,
        status: filter,
        counted: ["uncounted", "excluded"].includes(filter) ? undefined : true,
        page,
        page_size: pageSize,
      }),
    enabled: active && sessionId !== null,
  });
  const results = useQuery({
    queryKey: ["inventory-audit", "search", scope, sessionId, location, searchValue],
    queryFn: () =>
      finora.inventoryAudit.lines(auditRequired(sessionId), {
        q: searchValue,
        location_key: location || undefined,
        page_size: 20,
      }),
    enabled: active && sessionId !== null && searchValue.length > 0,
  });
  const searchReady = search === searchValue && !results.isPlaceholderData && !results.isFetching;
  const draft = entry !== null && !entry.saved;
  const locked = busy || uncertain || (hasDesktopBridge() && local.data?.available !== true);
  const offline = local.data?.offline ?? false;
  const pendingLocal = local.data?.items.some((item) => item.session_id === sessionId) ?? false;
  useEffect(() => {
    if (hasDesktopBridge()) return;
    const url = new URL(window.location.href);
    if (sessionId) url.searchParams.set("session", String(sessionId));
    else url.searchParams.delete("session");
    window.history.replaceState(null, "", url);
  }, [sessionId]);
  useEffect(() => {
    if (!entry?.ticket || entry.saved) return;
    const frame = requestAnimationFrame(() => {
      editorRef.current?.scrollIntoView({
        block: "center",
        behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
      });
      editorRef.current?.querySelector<HTMLInputElement>("input")?.focus({ preventScroll: true });
    });
    return () => cancelAnimationFrame(frame);
  }, [entry?.line.id, entry?.ticket, entry?.saved]);
  useEffect(() => {
    onBusyChange?.(locked || draft);
    return () => onBusyChange?.(false);
  }, [locked, draft, onBusyChange]);
  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["inventory-audit"] });
    for (const key of ["products", "orders", "pos", "reports", "finance"])
      void queryClient.invalidateQueries({ queryKey: [key] });
  };
  const execute = async (id: number, data: AuditCommand, complete?: Attempt["complete"]) => {
    if (busy) return;
    attempt.current = { id, data, complete };
    setBusy(true);
    setError(null);
    try {
      const result = await finora.inventoryAudit.command(id, data);
      setUncertain(false);
      attempt.current = null;
      await refresh();
      complete?.(result);
      return result;
    } catch (problem) {
      const failure = toFinoraError(problem);
      setError(failure.message);
      const unknown = ["network", "timeout", "invalid_response", "server"].includes(failure.kind);
      setUncertain(unknown);
      if (!unknown) attempt.current = null;
      if (failure.status === 409) await refresh();
    } finally {
      setBusy(false);
    }
  };
  const send = (data: Omit<AuditCommand, "idempotency_key">, complete?: Attempt["complete"]) => {
    if (sessionId === null || locked) return;
    void execute(sessionId, { ...data, idempotency_key: crypto.randomUUID() }, complete);
  };
  const select = async (line: AuditLine, origin: "search" | "row") => {
    if (
      locked ||
      draft ||
      !current.data ||
      current.data.status !== "counting" ||
      line.excluded ||
      !can("inventory.audit.count")
    )
      return;
    setSearch("");
    setEntry({
      line,
      ticket: null,
      quantity: line.counted_quantity === null ? "0" : String(line.counted_quantity),
      notes: line.notes,
      origin,
      saved: false,
    });
    send({ action: "begin_count", line_id: line.id, version: line.version }, (ticket) => {
      setEntry((old) => (old && old.line.id === line.id ? { ...old, ticket } : old));
      if (ticket.concurrent_counts) toast.info("يوجد عد مستقل لنفس الصنف؛ لا تجمع الأعداد تلقائياً");
    });
  };
  const saveEntry = () => {
    if (!entry?.ticket || locked || !/^\d+$/.test(entry.quantity) || Number(entry.quantity) > 1_000_000_000)
      return;
    const saved = entry;
    send(
      {
        action: "save_count",
        line_id: entry.line.id,
        version: entry.ticket.version,
        ticket: entry.ticket.ticket,
        quantity: Number(entry.quantity),
        notes: entry.notes,
      },
      (result) => {
        setEntry({
          ...saved,
          saved: true,
          ticket: null,
          line: {
            ...saved.line,
            version: result.version ?? saved.line.version,
            counted_quantity: Number(saved.quantity),
          },
        });
        setSearch("");
        toast.success(result.queued ? "العد محفوظ محلياً؛ بانتظار المزامنة" : "تمت إضافة المنتج للجرد");
        searchRef.current?.focus();
        if (!result.queued && can("inventory.audit.investigate") && can("inventory.audit.system")) {
          // Separate request: investigating the previous item never blocks adding the next.
          void finora.inventoryAudit
            .command(auditRequired(sessionId), {
              action: "investigate",
              line_id: saved.line.id,
              idempotency_key: crypto.randomUUID(),
            })
            .then(() =>
              queryClient.invalidateQueries({
                queryKey: ["inventory-audit", "details", scope, sessionId, saved.line.id],
              }),
            )
            .catch(() => toast.info("حُفظ العد؛ فحص الأدلة يحتاج إعادة المحاولة من التفاصيل"));
        }
      },
    );
  };
  const scan = async (code: string) => {
    if (
      locked ||
      draft ||
      scanning.current ||
      sessionId === null ||
      current.data?.status !== "counting" ||
      !can("inventory.audit.count")
    )
      return;
    const now = performance.now();
    if (lastScan.current.code === code && now - lastScan.current.time < 500) return;
    lastScan.current = { code, time: now };
    scanning.current = true;
    try {
      const found = await finora.inventoryAudit.lines(sessionId, {
        q: code,
        location_key: location || undefined,
        page_size: 100,
        exact: true,
      });
      const matches = found.items.filter((line) =>
        [
          line.product.barcode,
          line.product.sku,
          line.product.current_barcode,
          line.product.current_sku,
          String(line.product.id),
        ].includes(code),
      );
      if (matches.length !== 1 || found.total !== 1) {
        setSearch(code);
        setCameraOpen(false);
        toast.info(
          matches.length ? "اختر المقاس أو المتغير المطلوب من نتائج البحث" : "الكود غير موجود ضمن موقع الجرد",
        );
        return;
      }
      const line = auditRequired(matches[0]);
      if (scanMode === "select") {
        setCameraOpen(false);
        await select(line, "search");
        return;
      }
      if (line.counted_by !== null && line.counted_by !== useSession.getState().session?.user.id) {
        setSearch(code);
        setCameraOpen(false);
        toast.info("الصنف مجرود من موظف آخر؛ استخدم إعادة العد بدل جمع الأعداد");
        return;
      }
      const quantity = (line.counted_quantity ?? 0) + 1;
      if (quantity > 1_000_000_000) {
        toast.error("تجاوز العدد الحد المسموح؛ راجع العد");
        return;
      }
      const selected: Entry = {
        line,
        ticket: null,
        quantity: String(quantity),
        notes: line.notes,
        origin: "search",
        saved: false,
      };
      setEntry(selected);
      const ticket = await execute(
        sessionId,
        {
          action: "begin_count",
          line_id: line.id,
          version: line.version,
          idempotency_key: crypto.randomUUID(),
        },
        (result) => setEntry({ ...selected, ticket: result }),
      );
      if (!ticket) {
        setCameraOpen(false);
        return;
      }
      const result = await execute(
        sessionId,
        {
          action: "save_count",
          line_id: line.id,
          version: ticket.version,
          ticket: ticket.ticket,
          quantity,
          notes: line.notes,
          idempotency_key: crypto.randomUUID(),
        },
        (saved) => {
          setEntry({
            ...selected,
            saved: true,
            line: { ...line, counted_quantity: quantity, version: saved.version ?? line.version },
          });
          setSearch("");
          toast.success(saved.queued ? "قراءة محفوظة محلياً؛ بانتظار المزامنة" : `تم عد ${quantity} قطعة`);
        },
      );
      if (!result) setCameraOpen(false);
    } catch (problem) {
      setError(toFinoraError(problem).message);
      setCameraOpen(false);
    } finally {
      scanning.current = false;
    }
  };
  useBarcodeScanner(
    (code) => {
      void scan(code);
    },
    active &&
      view === "count" &&
      sessionId !== null &&
      !createOpen &&
      !reviewOpen &&
      !cameraOpen &&
      details === null,
    1,
  );
  useEffect(() => {
    if (!active) {
      setDetails(null);
      setReviewOpen(false);
      setCreateOpen(false);
      setCameraOpen(false);
    }
  }, [active]);
  const start = async () => {
    if (busy || !locationKeys.length) return;
    setBusy(true);
    setError(null);
    createKey.current ??= crypto.randomUUID();
    try {
      createPayload.current ??= {
        idempotency_key: createKey.current,
        ledger_kind: kind,
        location_keys: locationKeys,
        title,
      };
      const result = await finora.inventoryAudit.create(createPayload.current);
      createPayload.current = null;
      createKey.current = null;
      setSessionId(result.session_id);
      setView("count");
      setLocation(locationKeys[0] ?? "");
      setCreateOpen(false);
      await refresh();
    } catch (problem) {
      const failure = toFinoraError(problem);
      setError(failure.message);
      if (!["network", "timeout", "invalid_response", "server"].includes(failure.kind))
        createPayload.current = null;
    } finally {
      setBusy(false);
    }
  };
  const download = async () => {
    if (sessionId === null || locked || draft || offline || pendingLocal) return;
    setBusy(true);
    stopDownload.current = false;
    setError(null);
    setDownloadProgress("جارٍ تجهيز الأصناف…");
    try {
      let page = 1,
        done = 0,
        total = 1;
      while (page <= total && !stopDownload.current) {
        const batch = await finora.inventoryAudit.lines(sessionId, {
          location_key: location || undefined,
          page,
          page_size: 100,
        });
        total = batch.total_pages;
        const identifiers = batch.items.filter((line) => !line.excluded).map((line) => line.id);
        if (identifiers.length) await finora.inventoryAudit.prepareOffline(sessionId, identifiers);
        done += identifiers.length;
        setDownloadProgress(`تم تنزيل ${done} صنف · دفعة ${page} / ${total}`);
        page++;
      }
      toast.success(
        stopDownload.current
          ? "التنزيل متوقف؛ الدفعات السابقة محفوظة"
          : "أصناف هذا الموقع جاهزة للعد بدون إنترنت",
      );
      await refresh();
    } catch (problem) {
      setError(toFinoraError(problem).message);
      await local.refetch();
    } finally {
      setDownloadProgress(null);
      setBusy(false);
    }
  };
  const recovered = (result: AuditCommandResult, key: string, action: string) => {
    const saved = attempt.current;
    if (saved?.data.idempotency_key === key) {
      saved.complete?.(result);
      attempt.current = null;
      setUncertain(false);
    }
    if (action === "create") {
      createPayload.current = null;
      createKey.current = null;
      setSessionId(result.session_id);
      setView("count");
      setCreateOpen(false);
    }
  };
  const resume = (row: AuditSession) => {
    if (locked || draft) return;
    setSessionId(row.id);
    setLocation(row.locations[0]?.key ?? "");
    setView("count");
    setPage(1);
    setEntry(null);
    setSearch("");
  };
  const entryEditor = (selected: Entry) => (
    <div ref={editorRef} className="mt-3 space-y-2" aria-label="بطاقة عد الصنف">
      <div className="grid grid-cols-3 items-end gap-2">
        <div className="rounded-control bg-surface-sunken p-2 text-center">
          <p className="text-[11px] text-ink-soft">رصيد النظام</p>
          <strong className="mt-1 block text-lg ltr-isolate">
            {number(
              selected.ticket?.expected_quantity ??
                selected.line.expected_quantity ??
                selected.line.baseline_quantity,
            )}
          </strong>
        </div>
        <div className="col-span-2">
          <p className="mb-1 text-xs text-ink-soft">العدد الموجود فعلياً</p>
          <Quantity
            value={selected.quantity}
            disabled={locked || selected.saved || !selected.ticket}
            onChange={(quantity) => setEntry((old) => (old ? { ...old, quantity } : old))}
          />
        </div>
      </div>
      {selected.ticket?.expected_quantity !== undefined && /^\d+$/.test(selected.quantity) && (
        <p className="text-sm">
          الفرق:{" "}
          <strong className="ltr-isolate">
            {number(Number(selected.quantity) - selected.ticket.expected_quantity)}
          </strong>
        </p>
      )}
      {!selected.saved && (
        <input
          aria-label="ملاحظة العد"
          placeholder="ملاحظة اختيارية"
          value={selected.notes}
          maxLength={2000}
          onChange={(event) => setEntry((old) => (old ? { ...old, notes: event.target.value } : old))}
          disabled={locked}
          className={`${input} w-full`}
        />
      )}
      <div className="flex gap-2">
        {selected.saved ? (
          <button
            type="button"
            onClick={() => {
              setEntry(null);
              void select(selected.line, selected.origin);
            }}
            disabled={locked}
            className={`${auditButton} flex-1`}
          >
            إعادة العد
          </button>
        ) : (
          <button
            type="button"
            onClick={saveEntry}
            disabled={
              locked ||
              !selected.ticket ||
              !/^\d+$/.test(selected.quantity) ||
              Number(selected.quantity) > 1_000_000_000
            }
            className={`${auditPrimary} flex-1`}
          >
            إضافة إلى الجرد
          </button>
        )}
        <button
          type="button"
          onClick={() => {
            if (entry?.ticket && !entry.saved)
              send(
                {
                  action: "cancel_count",
                  line_id: entry.line.id,
                  version: entry.ticket.version,
                  ticket: entry.ticket.ticket,
                },
                () => setEntry(null),
              );
            else setEntry(null);
          }}
          disabled={locked}
          className={auditButton}
        >
          {selected.saved ? "إغلاق البطاقة" : "إلغاء الإدخال"}
        </button>
      </div>
      {selected.saved && (
        <p role="status" className="flex items-center gap-1 text-xs text-emerald-700">
          <Check size={14} /> محفوظ؛ القائمة السابقة تبقى كما هي
        </p>
      )}
    </div>
  );

  return (
    <div
      className="audit-workspace relative flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto pe-1"
      aria-label="جرد المخزون الذكي"
      dir="rtl"
    >
      <div className="flex flex-wrap items-center gap-2">
        <div className="me-auto min-w-0">
          <h2 className="flex items-center gap-2 text-base font-semibold">
            <ClipboardCheck size={20} className="text-violet" />
            جرد المخزون{" "}
            <FeatureHelp
              label="شرح الجرد"
              text="العد يسجل الموجود الفعلي فقط. المخزون يتغير بعد مراجعة السبب واعتماد الجلسة وترحيلها بصلاحية مستقلة. الصنف غير المجرد لا يحتسب صفراً."
            />
          </h2>
          {current.data && (
            <p className="mt-1 text-xs text-ink-soft">
              {current.data.number} · {current.data.created_by_name}{" "}
              <span className={`ms-2 rounded-full px-2 py-1 ${stateTone(current.data.status)}`}>
                {states[current.data.status]}
              </span>
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={() => setLinkOpen(true)}
          disabled={!serverUrl}
          className={`${auditButton} inline-flex items-center gap-1`}
        >
          <Link size={16} /> رابط الموقع
        </button>
        {current.data &&
          view === "count" &&
          can("inventory.audit.count") &&
          ["counting", "paused"].includes(current.data.status) && (
            <button
              type="button"
              disabled={locked || draft || offline || pendingLocal}
              onClick={() =>
                send(
                  {
                    action: current.data?.status === "paused" ? "resume" : "pause",
                    version: auditRequired(current.data).version,
                  },
                  () => setEntry(null),
                )
              }
              className={`${auditButton} inline-flex items-center gap-1`}
            >
              {current.data.status === "paused" ? <Play size={16} /> : <Pause size={16} />}
              {current.data.status === "paused" ? "استئناف الجرد" : "إيقاف مؤقت"}
            </button>
          )}
        {current.data && (
          <FeatureHelp
            label="شرح حفظ واستئناف الجلسة"
            text="كل عدد محفوظ يبقى في سجل الجرد؛ افتح الجلسة لاحقاً لتعديله أثناء العد. الإيقاف المؤقت يمنع الإدخال ويحفظ الأعداد، ويحتاج اتصالاً ومزامنة الإدخالات أولاً. لقطات Offline القديمة تحتاج تنزيل جديد بعد الاستئناف. بعد الإرسال للمراجعة، يعيد المسؤول فتح العد مع سبب؛ وبعد الترحيل يصبح السجل للعرض فقط."
          />
        )}
        <button
          type="button"
          onClick={() => {
            if (!draft && !locked) setView(view === "history" ? "count" : "history");
          }}
          disabled={draft || locked}
          className={`${auditButton} inline-flex items-center gap-1`}
        >
          <History size={16} />
          سجل الجرد
        </button>
        {can("inventory.audit.count") && (
          <button
            type="button"
            onClick={() => {
              setError(null);
              setCreateOpen(true);
            }}
            disabled={draft || locked}
            className={auditPrimary}
          >
            جلسة جديدة
          </button>
        )}
        <button
          type="button"
          aria-label="تحديث الجرد"
          onClick={() => void refresh()}
          disabled={locked}
          className={auditButton}
        >
          <RefreshCw size={16} />
        </button>
      </div>
      <AuditRecovery
        status={local.data}
        busy={busy || draft}
        onWorking={setBusy}
        onRecovered={recovered}
        onRefresh={refresh}
      />
      {current.data?.status === "paused" && view === "count" && (
        <p
          role="status"
          className="rounded-control border border-amber-100 bg-amber-50 p-3 text-sm text-amber-800"
        >
          الجلسة متوقفة مؤقتاً وأعدادها محفوظة. اضغط «استئناف الجرد» لتكمل أو تعدّل العد؛ لن يتغير المخزون قبل
          الاعتماد والترحيل.
        </p>
      )}
      {sessionId !== null &&
        local.data?.available &&
        can("inventory.audit.count") &&
        current.data?.status === "counting" && (
          <div className="flex shrink-0 flex-wrap items-center gap-2 text-xs">
            <button
              type="button"
              disabled={locked || draft || offline || pendingLocal}
              onClick={() => void download()}
              className={`${auditButton} min-h-10 text-xs`}
            >
              تنزيل هذا الموقع للعد بدون إنترنت
            </button>
            <FeatureHelp text="نزّل أصناف الموقع أثناء الاتصال. كل صنف يحصل على لقطة رصيد مؤرخة وصالحة 24 ساعة. تنزيل موقع ثانٍ لا يخلط العد معه؛ تغيّر الحركات بعد اللقطة يمنع تطبيق العد القديم." />
            {downloadProgress && (
              <>
                <span role="status" className="text-ink-soft">
                  {downloadProgress}
                </span>
                <button
                  type="button"
                  onClick={() => {
                    stopDownload.current = true;
                  }}
                  className={`${auditButton} min-h-10 text-xs`}
                >
                  إيقاف بعد هذه الدفعة
                </button>
              </>
            )}
          </div>
        )}
      {(error || local.error || meta.error || current.error || list.error) && (
        <div
          role="alert"
          className="rounded-control border border-red-100 bg-red-50 p-3 text-sm text-red-700"
        >
          {error ??
            (local.error
              ? "أعد تشغيل نسخة Desktop المحدثة لتفعيل الحفظ الآمن للجرد"
              : toFinoraError(meta.error ?? current.error ?? list.error).message)}
          {uncertain && (
            <>
              <p className="mt-1 text-xs">النتيجة غير مؤكدة؛ أعد نفس الطلب قبل إنشاء طلب بديل.</p>
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  const saved = attempt.current;
                  if (saved) void execute(saved.id, saved.data, saved.complete);
                }}
                className={`${auditButton} mt-2`}
              >
                تأكيد نفس الطلب
              </button>
            </>
          )}
        </div>
      )}
      {view === "history" || sessionId === null ? (
        <div className="min-h-0 flex-1 overflow-auto rounded-panel border border-line bg-white/70 p-3">
          <h3 className="mb-3 text-sm font-semibold">جلسات الجرد السابقة</h3>
          <p className="mb-3 text-xs text-ink-soft">
            افتح الجلسة لمتابعتها أو تعديل أعدادها أثناء الجرد؛ الجلسة المرحلة تعرض سجلها فقط.
          </p>
          {sessions.isLoading && <p className="text-sm text-ink-soft">جارٍ تحميل السجل…</p>}
          {sessions.error && (
            <p role="alert" className="text-sm text-danger">
              {toFinoraError(sessions.error).message}
            </p>
          )}
          {sessions.data?.items.map((row) => (
            <button
              key={row.id}
              type="button"
              onClick={() => resume(row)}
              className="mb-2 flex min-h-20 w-full items-center justify-between gap-3 rounded-panel border border-line bg-white p-3 text-start hover:border-violet/40"
            >
              <span className="min-w-0">
                <strong className="block text-sm">
                  {row.number} {row.title}
                </strong>
                <span className="mt-1 block text-xs text-ink-soft">
                  {row.locations.map((loc) => loc.name).join("، ")} · {row.created_by_name}
                </span>
                <span className="mt-1 block text-xs text-ink-soft">{formatDateTime(row.created_at)}</span>
              </span>
              <span className="shrink-0 text-end">
                <span className={`rounded-full px-2 py-1 text-xs ${stateTone(row.status)}`}>
                  {states[row.status]}
                </span>
                <span className="mt-2 block text-xs text-ink-soft">
                  {row.stats.counted} / {row.stats.planned} صنف
                </span>
                <span className="mt-2 block text-xs text-violet">
                  {row.status === "counting"
                    ? "متابعة وتعديل"
                    : row.status === "paused"
                      ? "فتح واستئناف"
                      : "عرض الجلسة"}
                </span>
              </span>
            </button>
          ))}
          {sessions.data?.items.length === 0 && (
            <p className="py-10 text-center text-sm text-ink-soft">
              ابدأ جلسة جديدة؛ نتائج العد وسجلها تنحفظ هنا.
            </p>
          )}
          {sessions.data && (
            <TablePagination
              page={historyPage}
              totalPages={sessions.data.total_pages}
              total={sessions.data.total}
              pageSize={historySize}
              noun="جلسة"
              onPage={setHistoryPage}
              onPageSize={(size) => {
                setHistorySize(size);
                setHistoryPage(1);
              }}
            />
          )}
        </div>
      ) : current.data ? (
        <>
          <div className="flex flex-wrap items-end gap-2">
            <label className="min-w-0 flex-1 text-xs text-ink-soft">
              موقع العد
              <select
                aria-label="موقع العد"
                value={location}
                disabled={draft || locked}
                onChange={(event) => {
                  setLocation(event.target.value);
                  setPage(1);
                  setEntry(null);
                  setSearch("");
                }}
                className={`${input} mt-1 w-full`}
              >
                {current.data.locations.map((loc) => (
                  <option key={loc.key} value={loc.key}>
                    {loc.branch_name} · {loc.name}
                  </option>
                ))}
              </select>
            </label>
            <FeatureHelp
              label="شرح نطاق الجلسة"
              text="كل صنف يحسب لكل موقع لوحده. نطاق الجلسة ثابت من البداية؛ تبديل موقع العد لا يخلط الكميات، وجرد مخازن الجملة لا يجمع مع مرآة مخزون الفروع."
            />
          </div>
          <div className="grid grid-cols-3 gap-2">
            {[
              ["تم جردها", current.data.stats.counted, "bg-violet-soft/60 text-violet"],
              ["نقص", current.data.stats.shortage, "bg-red-50 text-red-600"],
              ["زيادة", current.data.stats.surplus, "bg-blue-50 text-blue-600"],
            ].map(([label, value, tone]) => (
              <div key={String(label)} className={`rounded-panel p-3 text-center ${tone}`}>
                <strong className="block text-xl ltr-isolate">{number(value as number | undefined)}</strong>
                <span className="text-xs">{label}</span>
              </div>
            ))}
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            <label className="text-xs text-ink-soft">
              المسح{" "}
              <select
                aria-label="وضع مسح الجرد"
                value={scanMode}
                disabled={locked || draft}
                onChange={(event) => setScanMode(event.target.value as "select" | "count")}
                className={`${input} ms-2 h-10`}
              >
                <option value="select">تحديد الصنف</option>
                <option value="count">عد قطعة لكل قراءة</option>
              </select>
            </label>
            <button
              type="button"
              aria-label="مسح بالكاميرا"
              disabled={locked || draft || current.data.status !== "counting"}
              onClick={() => setCameraOpen(true)}
              className={`${auditButton} min-h-10`}
            >
              <ScanLine size={18} />
            </button>
            <FeatureHelp text="القارئ يحدد الصنف أو يزيد العد قطعة لكل قراءة حسب الوضع. الأكواد المشتركة بين مقاسات تتطلب اختيار المقاس، ولا نجمع عد موظف آخر تلقائياً. الأرقام التسلسلية تحتاج سجل وحدات مستقل وهو غير متاح في المصدر الحالي." />
          </div>
          <div className="flex items-center gap-2 rounded-control border border-line bg-white px-3">
            <Search size={18} className="shrink-0 text-ink-soft" />
            <input
              ref={searchRef}
              aria-label="بحث أصناف الجرد"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              disabled={locked || draft}
              placeholder="اسم، باركود، SKU أو موديل…"
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  void scan(search.trim());
                }
              }}
              className="h-11 min-w-0 flex-1 bg-transparent text-sm outline-none"
            />
            {search && (
              <button
                type="button"
                aria-label="مسح البحث"
                disabled={locked || draft}
                onClick={() => setSearch("")}
                className="grid h-11 w-8 shrink-0 place-items-center text-ink-soft"
              >
                <X size={15} />
              </button>
            )}
          </div>
          <div ref={scrollRef} className="audit-scroll min-h-[240px] flex-1 overflow-auto pe-1">
            {search.length > 0 && (
              <div
                className="mb-3 space-y-2 rounded-panel border border-line bg-white/80 p-2"
                aria-label="نتائج بحث الجرد"
              >
                {!searchReady && <p className="p-2 text-xs text-ink-soft">جارٍ البحث…</p>}
                {results.error && (
                  <p role="alert" className="text-sm text-danger">
                    {toFinoraError(results.error).message}
                  </p>
                )}
                {searchReady &&
                  results.data?.items.map((line) => (
                    <button
                      key={line.id}
                      type="button"
                      disabled={draft || locked || current.data.status !== "counting"}
                      onClick={() => void select(line, "search")}
                      className="flex min-h-16 w-full items-center gap-3 rounded-control p-2 text-start hover:bg-violet-soft disabled:opacity-60"
                    >
                      <ProductThumb src={auditImageUrl(line.product.image_url, serverUrl)} size={40} />
                      <span className="min-w-0 flex-1">
                        <strong className="block text-sm">{line.product.name}</strong>
                        <span className="text-xs text-ink-soft">
                          {line.product.variant_name} · {line.product.sku}
                        </span>
                      </span>
                      {line.counted_quantity !== null && (
                        <span className="text-xs text-violet">موجود بالجرد؛ تعديل</span>
                      )}
                    </button>
                  ))}
                {searchReady && results.data?.items.length === 0 && (
                  <p className="p-3 text-xs text-ink-soft">
                    الباركود أو الصنف غير موجود ضمن نطاق هذه الجلسة.
                  </p>
                )}
              </div>
            )}
            {entry?.origin === "search" && (
              <section className="mb-3 rounded-panel border border-violet/30 bg-white p-3">
                <div className="flex gap-3">
                  <ProductThumb src={auditImageUrl(entry.line.product.image_url, serverUrl)} size={52} />
                  <div className="min-w-0">
                    <h3 className="text-sm font-semibold">{entry.line.product.name}</h3>
                    <p className="text-xs text-ink-soft">
                      {entry.line.product.variant_name} · {entry.line.product.sku}
                    </p>
                  </div>
                </div>
                {entryEditor(entry)}
              </section>
            )}
            <div className="mb-3 flex flex-wrap gap-1" aria-label="فلاتر الجرد">
              {(
                [
                  ["all", "الكل"],
                  ["matched", "مطابق"],
                  ["shortage", "نقص"],
                  ["surplus", "زيادة"],
                  ["unreviewed", "قيد المراجعة"],
                  ["uncounted", "غير مجرود"],
                  ["excluded", "مستبعد"],
                ] as const
              )
                .filter(
                  ([value]) =>
                    can("inventory.audit.system") || !["matched", "shortage", "surplus"].includes(value),
                )
                .map(([value, label]) => (
                  <button
                    type="button"
                    key={value}
                    disabled={draft || locked}
                    aria-pressed={filter === value}
                    onClick={() => {
                      setFilter(value);
                      setPage(1);
                    }}
                    className={`min-h-10 rounded-control border px-3 text-xs ${filter === value ? "border-violet/40 bg-violet-soft text-violet" : "border-line bg-white text-ink-soft"}`}
                  >
                    {label}
                  </button>
                ))}
            </div>
            <div
              className="grid items-start gap-2 md:grid-cols-2 2xl:grid-cols-3"
              aria-label="قائمة المنتجات المجردة"
            >
              {list.isLoading && (
                <p className="py-8 text-center text-sm text-ink-soft">جارٍ تحميل الأصناف…</p>
              )}
              {list.data?.items.map((line) => (
                <article key={line.id} className="rounded-panel border border-line bg-white/90 p-3">
                  <div className="flex items-center gap-3">
                    <ProductThumb src={auditImageUrl(line.product.image_url, serverUrl)} size={46} />
                    <div className="min-w-0 flex-1">
                      <h3 className="text-sm font-semibold">{line.product.name}</h3>
                      <p className="mt-1 text-xs text-ink-soft">
                        {line.product.variant_name} · {line.product.sku}
                      </p>
                    </div>
                    <span className={`shrink-0 rounded-full px-2 py-1 text-xs ${stateTone(line.status)}`}>
                      {states[line.status]}
                    </span>
                  </div>
                  <div className="mt-3 grid grid-cols-3 gap-2 text-center text-xs">
                    <p>
                      النظام <strong className="ms-1 ltr-isolate">{number(line.expected_quantity)}</strong>
                    </p>
                    <p>
                      الفعلي <strong className="ms-1 ltr-isolate">{number(line.counted_quantity)}</strong>
                    </p>
                    <p>
                      الفرق <strong className="ms-1 ltr-isolate">{number(line.difference)}</strong>
                    </p>
                  </div>
                  {entry?.origin === "row" && entry.line.id === line.id ? (
                    entryEditor(entry)
                  ) : (
                    <div className="mt-2 flex gap-2">
                      <button
                        type="button"
                        disabled={
                          draft ||
                          locked ||
                          line.excluded ||
                          current.data.status !== "counting" ||
                          !can("inventory.audit.count")
                        }
                        onClick={() => void select(line, "row")}
                        className={`${auditButton} min-h-10 flex-1 text-xs`}
                      >
                        {line.counted_quantity === null ? "بدء العد" : "تعديل العدد / إعادة العد"}
                      </button>
                      <button
                        type="button"
                        onClick={() => setDetails(line)}
                        className={`${auditButton} min-h-10 text-xs`}
                      >
                        التفاصيل
                      </button>
                    </div>
                  )}
                </article>
              ))}
              {list.data?.items.length === 0 && (
                <p className="rounded-panel border border-dashed border-line p-8 text-center text-sm text-ink-soft">
                  ابحث عن الصنف وأضفه، أو افتح «غير مجرود» لمتابعة النطاق المخطط.
                </p>
              )}
            </div>
            {list.data && (
              <TablePagination
                page={page}
                totalPages={list.data.total_pages}
                total={list.data.total}
                pageSize={pageSize}
                noun="صنف"
                onPage={(next) => {
                  if (!draft && !locked) setPage(next);
                }}
                onPageSize={(size) => {
                  if (!draft && !locked) {
                    setPageSize(size);
                    setPage(1);
                  }
                }}
              />
            )}
            <button
              type="button"
              onClick={() => {
                scrollRef.current?.scrollTo({ top: 0, behavior: "auto" });
                searchRef.current?.focus();
              }}
              className="my-3 inline-flex min-h-10 items-center gap-1 rounded-control bg-violet-soft px-3 text-xs text-violet"
            >
              <ArrowUp size={14} />
              العودة إلى البحث
            </button>
          </div>
          <footer className="shrink-0 border-t border-line pt-2">
            <button
              type="button"
              onClick={() => {
                setPartial(false);
                setReviewOpen(true);
              }}
              disabled={draft || locked}
              className={`${auditPrimary} w-full`}
            >
              {current.data.status === "posted"
                ? "عرض تقرير الجرد"
                : current.data.status === "counting"
                  ? "إنهاء الجرد ومراجعة النتائج"
                  : "مراجعة واعتماد الجرد"}
            </button>
          </footer>
          <AuditDetails
            key={details?.id ?? "none"}
            session={current.data}
            scope={scope}
            line={details}
            serverUrl={serverUrl}
            permissions={meta.data?.permissions ?? []}
            busy={locked || draft}
            commandError={error}
            onClose={() => setDetails(null)}
            onCommand={send}
          />
        </>
      ) : (
        <p className="py-10 text-center text-sm text-ink-soft">جارٍ فتح جلسة الجرد…</p>
      )}
      <AuditSheet
        open={createOpen}
        title="بدء جلسة جرد"
        onClose={() => {
          if (!busy) setCreateOpen(false);
        }}
        footer={
          <button
            type="button"
            onClick={() => void start()}
            disabled={busy || !locationKeys.length || offline}
            className={`${auditPrimary} w-full`}
          >
            بدء الجرد
          </button>
        }
      >
        <div className="space-y-3">
          {error && (
            <p role="alert" className="rounded-control bg-red-50 p-3 text-sm text-red-700">
              {error}
            </p>
          )}
          <label className="block text-sm">
            عنوان اختياري
            <input
              aria-label="عنوان جلسة الجرد"
              maxLength={150}
              value={title}
              disabled={busy || createPayload.current !== null}
              onChange={(event) => {
                setTitle(event.target.value);
                createKey.current = null;
              }}
              className={`${input} mt-1 w-full`}
            />
          </label>
          <label className="block text-sm">
            مصدر المخزون
            <select
              aria-label="مصدر مخزون الجرد"
              value={kind}
              disabled={busy || createPayload.current !== null}
              onChange={(event) => {
                setKind(event.target.value as "branch" | "warehouse");
                setLocationKeys([]);
                createKey.current = null;
              }}
              className={`${input} mt-1 w-full`}
            >
              <option value="branch">مخزون الفروع</option>
              {!!meta.data?.locations.warehouse.length && <option value="warehouse">مخازن الجملة</option>}
            </select>
          </label>
          <p className="text-xs leading-6 text-ink-soft">
            اختر موقعاً أو عدة مواقع مسموحة. كل موقع يحتفظ بأعداده؛ نطاق الجلسة لا يتغير بعد البداية.
          </p>
          <button
            type="button"
            disabled={busy || createPayload.current !== null}
            onClick={() => {
              setLocationKeys(meta.data?.locations[kind].map((loc) => loc.key) ?? []);
              createKey.current = null;
            }}
            className={auditButton}
          >
            كل المواقع المسموحة
          </button>
          {meta.data?.locations[kind].map((loc) => (
            <label
              key={loc.key}
              className="flex min-h-12 items-center gap-2 rounded-control border border-line bg-white p-3 text-sm"
            >
              <input
                type="checkbox"
                disabled={busy || createPayload.current !== null}
                checked={locationKeys.includes(loc.key)}
                onChange={(event) => {
                  setLocationKeys((old) =>
                    event.target.checked ? [...old, loc.key] : old.filter((key) => key !== loc.key),
                  );
                  createKey.current = null;
                }}
              />
              {loc.branch_name} · {loc.name}
            </label>
          ))}
          {meta.data?.locations[kind].length === 0 && (
            <p className="text-sm text-ink-soft">لا توجد مواقع متاحة لهذا المصدر.</p>
          )}
        </div>
      </AuditSheet>
      <AuditSheet
        open={linkOpen}
        title="رابط الجرد على الموقع"
        onClose={() => setLinkOpen(false)}
        footer={
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className={auditPrimary}
              onClick={() =>
                void finora.inventoryAudit
                  .openWebsite(sessionId ?? undefined)
                  .catch((problem) => setError(toFinoraError(problem).message))
              }
            >
              <ExternalLink size={16} className="me-2 inline" /> فتح على الموقع
            </button>
            <button type="button" className={auditButton} onClick={() => void copyLink()}>
              نسخ الرابط
            </button>
          </div>
        }
      >
        <p className="mb-3 text-sm text-ink-soft">
          افتح الرابط من الهاتف أو المتصفح وسجّل الدخول بنفس الشركة. الرابط يفتح{" "}
          {sessionId ? "هذه الجلسة المحفوظة" : "صفحة الجرد"} حسب صلاحياتك، ولا يمنح صلاحية لغيرك.
        </p>
        <input
          ref={linkRef}
          aria-label="رابط الجرد على الموقع"
          readOnly
          value={auditLink}
          dir="ltr"
          onFocus={(event) => event.currentTarget.select()}
          className={`${input} w-full`}
        />
      </AuditSheet>
      <AuditSheet
        open={reviewOpen}
        title="مراجعة نتائج الجرد"
        onClose={() => {
          if (!locked) setReviewOpen(false);
        }}
        footer={
          current.data && (
            <div className="space-y-2">
              {current.data.status === "counting" && can("inventory.audit.count") && (
                <button
                  type="button"
                  disabled={
                    locked || offline || pendingLocal || (current.data.stats.uncounted > 0 && !partial)
                  }
                  onClick={() =>
                    send({
                      action: "submit",
                      version: auditRequired(current.data).version,
                      acknowledge_partial: partial,
                      reason,
                    })
                  }
                  className={`${auditPrimary} w-full`}
                >
                  إرسال الجرد للمراجعة
                </button>
              )}
              {current.data.status === "pending_review" && can("inventory.audit.approve") && (
                <button
                  type="button"
                  disabled={locked || offline || pendingLocal}
                  onClick={() =>
                    send({ action: "approve", version: auditRequired(current.data).version, reason })
                  }
                  className={`${auditPrimary} w-full`}
                >
                  اعتماد الجرد
                </button>
              )}
              {current.data.status === "approved" && can("inventory.audit.post") && (
                <button
                  type="button"
                  disabled={
                    locked ||
                    offline ||
                    pendingLocal ||
                    !can("inventory.audit.system") ||
                    !can("edit_current_stock") ||
                    !can("finance.approve") ||
                    (reconcileValuation && (!valuation.data || valuation.isFetching || !reason.trim()))
                  }
                  onClick={() =>
                    send({
                      action: "post",
                      version: auditRequired(current.data).version,
                      ...(reconcileValuation && valuation.data
                        ? {
                            reconcile_valuation: true,
                            valuation_fingerprint: valuation.data.fingerprint,
                            valuation_reason: reason,
                          }
                        : {}),
                    })
                  }
                  className={`${auditPrimary} w-full`}
                >
                  ترحيل التسويات المعتمدة
                </button>
              )}
              {["pending_review", "approved"].includes(current.data.status) &&
                can("inventory.audit.review") && (
                  <button
                    type="button"
                    disabled={locked || offline || pendingLocal || !reason.trim()}
                    onClick={() =>
                      send({ action: "reopen", version: auditRequired(current.data).version, reason }, () =>
                        setReviewOpen(false),
                      )
                    }
                    className={`${auditButton} w-full`}
                  >
                    إعادة فتح العد مع السبب
                  </button>
                )}
            </div>
          )
        }
      >
        {current.data && (
          <div className="space-y-3">
            {(offline || pendingLocal) && (
              <p role="status" className="rounded-control bg-amber-50 p-3 text-xs text-amber-800">
                زامن العد وراجع الطلبات المحلية أولاً. هذه الأرقام قد تخص لقطة محلية؛ الاعتماد والترحيل
                يحتاجان اتصالاً حياً.
              </p>
            )}
            {can("inventory.audit.export") && (
              <div className="flex flex-wrap gap-2">
                {(["print", "pdf", "xlsx"] as const).map((format) => (
                  <button
                    key={format}
                    type="button"
                    disabled={locked || offline || pendingLocal}
                    onClick={() => {
                      void finora.inventoryAudit
                        .export(auditRequired(current.data).id, format)
                        .catch((problem) => setError(toFinoraError(problem).message));
                    }}
                    className={`${auditButton} text-xs`}
                  >
                    {{ print: "طباعة التقرير", pdf: "حفظ PDF", xlsx: "تصدير Excel" }[format]}
                  </button>
                ))}
              </div>
            )}
            {error && (
              <p role="alert" className="rounded-control bg-red-50 p-3 text-sm text-red-700">
                {error}
              </p>
            )}
            <p className="text-sm font-semibold">
              {current.data.number} · {states[current.data.status]}
            </p>
            {current.data.ledger_kind === "branch" &&
              current.data.status !== "posted" &&
              can("inventory.audit.cost") &&
              can("inventory.audit.system") && (
                <div className="rounded-control border border-line bg-violet-soft/40 p-3 text-sm">
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      className={auditButton}
                      disabled={locked || offline || pendingLocal || valuation.isFetching}
                      onClick={() => {
                        setCheckValuation(true);
                        if (checkValuation) void valuation.refetch();
                      }}
                    >
                      فحص مطابقة طبقات التكلفة
                    </button>
                    <FeatureHelp text="قد تكون هناك طبقات تكلفة قديمة لم تواكب حركات الكميات. المطابقة تعيد أساس الطبقات إلى رصيد الفرع قبل الجرد بالأقدم أولاً FIFO، وتغطي النقص بالتكلفة المحفوظة. سجلها منفصل داخل ترحيل الجرد، ولا تعيد احتساب مبيعات سابقة أو قبض أو صرف." />
                  </div>
                  {valuation.error && (
                    <p role="alert" className="mt-2 text-red-600">
                      {toFinoraError(valuation.error).message}
                    </p>
                  )}
                  {valuation.data && (
                    <div className="mt-3 space-y-2">
                      <p>
                        أصناف تحتاج مطابقة: {number(valuation.data.affected_lines)} · طبقات زائدة:{" "}
                        {number(valuation.data.removed_units)} قطعة · رصيد غير مغطى:{" "}
                        {number(valuation.data.added_units)} قطعة
                      </p>
                      {valuation.data.affected_lines > 0 && (
                        <label className="flex items-start gap-2">
                          <input
                            type="checkbox"
                            checked={reconcileValuation}
                            disabled={locked || valuation.isFetching}
                            onChange={(event) => setReconcileValuation(event.target.checked)}
                            className="mt-1 accent-violet"
                          />
                          مطابقة طبقات التكلفة مع رصيد الفرع ضمن الترحيل، مع حفظ السبب أدناه
                        </label>
                      )}
                      <p className="text-xs text-ink-soft">
                        قيد التسوية يخص فرق العد الفعلي فقط. تفاصيل مطابقة الطبقات تحفظ في سجل الترحيل وتقرير
                        الجرد.
                      </p>
                    </div>
                  )}
                </div>
              )}
            <div className="grid grid-cols-2 gap-2">
              {[
                ["تم جردها", current.data.stats.counted],
                ["لم تجرد", current.data.stats.uncounted],
                ["إجمالي النقص", current.data.stats.shortage_units],
                ["إجمالي الزيادة", current.data.stats.surplus_units],
                ["غير مراجعة", current.data.stats.unreviewed],
                ["مستبعدة", current.data.stats.excluded],
              ].map(([label, value]) => (
                <div key={String(label)} className="rounded-control bg-surface-sunken p-3">
                  <span className="text-xs text-ink-soft">{label}</span>
                  <strong className="mt-1 block text-lg ltr-isolate">
                    {number(value as number | undefined)}
                  </strong>
                </div>
              ))}
            </div>
            <p className="rounded-control bg-violet-soft p-3 text-xs leading-6 text-violet">
              العد والاعتماد ما يغيران المخزون. الترحيل وحده يسجل حركة وقيداً غير نقدي؛ السندات والديون تبقى
              حسب مصادرها.
            </p>
            {current.data.status === "counting" && current.data.stats.uncounted > 0 && (
              <label className="flex items-start gap-2 rounded-control border border-amber-200 bg-amber-50 p-3 text-xs leading-6">
                <input
                  type="checkbox"
                  className="mt-1"
                  checked={partial}
                  onChange={(event) => setPartial(event.target.checked)}
                />
                أفهم أن الجرد جزئي؛ الأصناف التي لم تجرد تبقى دون تعديل ولا تعتبر صفراً.
              </label>
            )}
            <textarea
              aria-label="ملاحظة مراجعة الجرد"
              rows={3}
              value={reason}
              maxLength={2000}
              onChange={(event) => setReason(event.target.value)}
              placeholder="ملاحظة المراجعة / سبب إعادة فتح العد"
              className="w-full rounded-control border border-line bg-white p-3 text-sm"
              disabled={locked || offline || pendingLocal}
            />
            <FeatureHelp
              label="شرح الاعتماد والترحيل"
              text="يتحقق الخادم من الصلاحية ومن عدم تغير المخزون والفترة المحاسبية. أي فرق غير مفسر يمنع الاعتماد؛ راجع تفاصيل الصنف وسجل السبب أو أعد العد. لا يوجد تعويض تلقائي بين المواقع."
            />
          </div>
        )}
      </AuditSheet>
      <AuditCamera
        open={cameraOpen}
        onClose={() => setCameraOpen(false)}
        onRead={(code) => {
          void scan(code);
        }}
        caption={
          busy
            ? "جارٍ تثبيت القراءة…"
            : entry?.saved
              ? `${entry.line.product.name} · ${entry.quantity} قطعة`
              : scanMode === "count"
                ? "كل قراءة جديدة تعد قطعة واحدة"
                : "وجّه الكاميرا إلى باركود الصنف"
        }
      />
    </div>
  );
}
