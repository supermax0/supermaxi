import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, ScanLine, Send, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { FinoraApiError, finora } from "@/api/finora";
import type { ShipOrder } from "@/api/finora/shipping";
import { Field } from "@/components/FilterPanel";
import { useConnection } from "@/stores/connection";
import { toast } from "@/stores/toasts";
import { cn } from "@/utils/cn";
import { formatNumber } from "@/utils/format";
import {
  SupplierModal,
  supplierInput,
  supplierPrimary,
  supplierSecondary,
} from "../suppliers/SupplierDialogs";
import { Money, money, splitCodes } from "./shared";

export type DispatchMode = "agent_report" | "assign" | "handover";
type Party = { id: number; name: string };

const MODES: Array<{ id: DispatchMode; label: string; hint: string }> = [
  {
    id: "agent_report",
    label: "كشف مندوب",
    hint: "تُربط الطلبات بالمندوب وتُشحن، وتظهر في بوابته ككشف واحد يبلّغ عنه واصل / راجع / مؤجل.",
  },
  {
    id: "assign",
    label: "إسناد لمندوب",
    hint: "يُربط كل طلب بالمندوب فقط ويظهر في بوابته كطلب منفرد، دون كشف ودون تغيير حالة الطلب.",
  },
  {
    id: "handover",
    label: "تسليم لشركة نقل",
    hint: "كشف تسليم للشركة: تُسند الطلبات إليها وتُشحن. لا تتحرك أي أموال قبل كشف التسوية.",
  },
];

/** One place to hand orders over: agent manifest, agent assignment or carrier handover — scan, paste or preload. */
export function DispatchDialog({
  carriers,
  agents,
  initialIds = [],
  initialMode = "agent_report",
  onClose,
}: {
  carriers: Party[];
  agents: Party[];
  initialIds?: number[];
  initialMode?: DispatchMode;
  onClose(): void;
}) {
  const client = useQueryClient();
  const online = useConnection((s) => s.status === "online");
  const [mode, setMode] = useState<DispatchMode>(initialMode);
  const [agentId, setAgentId] = useState(agents[0] ? String(agents[0].id) : "");
  const [carrierId, setCarrierId] = useState(carriers[0] ? String(carriers[0].id) : "");
  const [entry, setEntry] = useState("");
  const [orders, setOrders] = useState<ShipOrder[]>([]);
  const [missing, setMissing] = useState<string[]>([]);
  const input = useRef<HTMLInputElement>(null);

  const lookup = useMutation({
    mutationFn: (codes: string[]) => finora.shipping.lookup(codes),
    onSuccess: (res) => {
      setOrders((current) => {
        const seen = new Set(current.map((o) => o.id));
        return [...current, ...res.found.filter((o) => !seen.has(o.id))];
      });
      setMissing(res.missing);
      input.current?.focus();
    },
    onError: (e: unknown) => toast.error(errorText(e)),
  });
  useEffect(() => {
    if (initialIds.length) lookup.mutate(initialIds.map(String));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const run = useMutation({
    mutationFn: async (): Promise<string> => {
      const ids = orders.map((o) => o.id);
      if (mode === "agent_report") {
        const res = await finora.shipping.agentReport(Number(agentId), ids);
        return res.already_exists
          ? `الكشف موجود مسبقاً: ${res.report_number}`
          : `أُنشئ كشف المندوب ${res.report_number}`;
      }
      if (mode === "handover") {
        const res = await finora.shipping.handover(Number(carrierId), ids);
        return res.message || `أُنشئ كشف التسليم ${res.report_number}`;
      }
      const failed: number[] = [];
      for (const id of ids) {
        try {
          await finora.orders.setDeliveryAgent(id, Number(agentId));
        } catch {
          failed.push(id);
        }
      }
      if (failed.length === ids.length) throw new Error("تعذر إسناد الطلبات — قد تكون مقفلة للمخزون");
      return failed.length
        ? `أُسند ${formatNumber(ids.length - failed.length)} طلب، وتعذر: ${failed.map((id) => `#${id}`).join("، ")}`
        : `أُسند ${formatNumber(ids.length)} طلب للمندوب`;
    },
    onSuccess: async (message) => {
      toast.success(message);
      await Promise.all([
        client.invalidateQueries({ queryKey: ["orders"] }),
        client.invalidateQueries({ queryKey: ["shipping"] }),
      ]);
      onClose();
    },
    onError: (e: unknown) => toast.error(errorText(e)),
  });

  const submit = (text: string) => {
    const codes = splitCodes(text);
    if (codes.length) lookup.mutate(codes);
    setEntry("");
  };
  const target = mode === "handover" ? carrierId : agentId;
  const total = orders.reduce((sum, o) => sum + o.remaining, 0);
  const current = MODES.find((m) => m.id === mode);

  return (
    <SupplierModal title="تسليم وإسناد الطلبات" icon={Send} busy={run.isPending} onClose={onClose} wide>
      <div className="grid gap-4">
        <div
          className="flex gap-1 rounded-control bg-surface-sunken p-1"
          role="radiogroup"
          aria-label="نوع العملية"
        >
          {MODES.map((m) => (
            <button
              key={m.id}
              type="button"
              role="radio"
              aria-checked={mode === m.id}
              disabled={(m.id === "handover" ? carriers : agents).length === 0}
              onClick={() => setMode(m.id)}
              className={cn(
                "h-9 flex-1 rounded-[10px] text-[13px] font-medium disabled:opacity-40",
                mode === m.id ? "bg-white text-maroon shadow-control" : "text-ink-soft",
              )}
            >
              {m.label}
            </button>
          ))}
        </div>
        <p className="-mt-2 text-[12px] leading-5 text-ink-faint">{current?.hint}</p>

        <div className="grid grid-cols-[220px_1fr] gap-4">
          <Field label={mode === "handover" ? "شركة النقل" : "المندوب"}>
            {mode === "handover" ? (
              <select
                className={supplierInput}
                value={carrierId}
                onChange={(e) => setCarrierId(e.target.value)}
              >
                {carriers.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            ) : (
              <select className={supplierInput} value={agentId} onChange={(e) => setAgentId(e.target.value)}>
                {agents.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field label="امسح باركود الطلب أو اكتب رقمه ثم Enter — أو الصق مجموعة">
            <div className="relative">
              <ScanLine
                size={17}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-maroon"
                aria-hidden
              />
              <input
                ref={input}
                autoFocus
                aria-label="مسح الطلبات"
                className={cn(supplierInput, "pr-10")}
                value={entry}
                onChange={(e) => setEntry(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    submit(entry);
                  }
                }}
                onPaste={(e) => {
                  const text = e.clipboardData.getData("text");
                  if (splitCodes(text).length > 1) {
                    e.preventDefault();
                    submit(text);
                  }
                }}
                placeholder="رقم الطلب / باركود الفاتورة / بوليصة الشركة"
              />
            </div>
          </Field>
        </div>
        {missing.length > 0 && (
          <p className="rounded-control bg-warning-soft px-3 py-2 text-xs text-warning" role="status">
            لم يُعثر على: <span className="ltr-isolate">{missing.join("، ")}</span>
          </p>
        )}
        <div className="max-h-[320px] overflow-y-auto rounded-control border border-line/70">
          {orders.length === 0 ? (
            <p className="py-10 text-center text-[13px] text-ink-faint">
              {lookup.isPending ? "جارٍ جلب الطلبات…" : "امسح الطلبات لتظهر هنا"}
            </p>
          ) : (
            <ul className="divide-y divide-line/60 text-[13px]" aria-label="الطلبات المحددة">
              {orders.map((o) => (
                <li key={o.id} className="flex items-center gap-3 px-3 py-2">
                  <span className="ltr-isolate w-16 font-bold">#{o.id}</span>
                  <span className="min-w-0 flex-1 truncate">
                    {o.customer_name} <span className="text-ink-faint">· {o.customer_city}</span>
                  </span>
                  <span className="text-[11px] text-ink-faint">{o.status}</span>
                  {(o.delivery_agent || o.shipping_company) && (
                    <span className="text-[11px] text-warning">
                      مع {o.delivery_agent || o.shipping_company}
                    </span>
                  )}
                  <Money value={o.remaining} className="font-semibold" />
                  <button
                    type="button"
                    aria-label={`إزالة ${o.id}`}
                    className="text-ink-faint hover:text-danger"
                    onClick={() => setOrders((list) => list.filter((x) => x.id !== o.id))}
                  >
                    <Trash2 size={14} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="flex items-center gap-2">
          <p className="flex-1 text-[13px] text-ink-soft">
            <span className="ltr-isolate font-bold">{formatNumber(orders.length)}</span> طلب · المستحق{" "}
            <span className="font-bold text-maroon">{money(total)}</span>
            {lookup.isPending && <Loader2 size={14} className="ms-2 inline animate-spin" />}
          </p>
          <button type="button" className={supplierSecondary} onClick={onClose}>
            إلغاء
          </button>
          <button
            type="button"
            className={supplierPrimary}
            disabled={!target || orders.length === 0 || !online || run.isPending}
            onClick={() => run.mutate()}
          >
            {run.isPending && <Loader2 size={16} className="animate-spin" />}
            {mode === "agent_report"
              ? "إنشاء كشف المندوب"
              : mode === "assign"
                ? "إسناد للمندوب"
                : "إنشاء كشف التسليم"}
          </button>
        </div>
      </div>
    </SupplierModal>
  );
}

function errorText(error: unknown): string {
  if (error instanceof FinoraApiError || error instanceof Error) return error.message;
  return String(error);
}
