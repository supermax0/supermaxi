import { useQuery } from "@tanstack/react-query";
import { Loader2, Pencil, Plus, RefreshCcw, Save, Search, Trash2, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { finora } from "@/api/finora";
import type { OrderDetails, QuickOrderEdit } from "@/api/finora/orders";
import type { PosProduct } from "@/api/finora/pos";
import { Field } from "@/components/FilterPanel";
import { IconButton } from "@/components/IconButton";
import { MoneyInput } from "@/components/MoneyInput";
import { orderFailureMessage, useOrderDetails, useQuickEditOrder } from "@/features/orders/useOrders";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useConnection } from "@/stores/connection";
import { useCan } from "@/stores/session";
import { formatIqd } from "@/utils/money";

const inputClass =
  "h-10 w-full rounded-control border border-line bg-white px-3 text-sm text-ink outline-none focus:border-violet/50 focus:ring-4 focus:ring-violet/10 disabled:bg-surface-sunken disabled:text-ink-soft";
const secondary =
  "h-10 rounded-control border border-line bg-white px-4 text-sm font-semibold text-ink hover:bg-violet-soft disabled:opacity-50";
type Line = QuickOrderEdit["items"][number] & { key: number; name: string; colors: PosProduct["colors"] };

function EditForm({ data: loadedData, onClose }: { data: OrderDetails; onClose(): void }) {
  const [data] = useState(loadedData);
  const { order } = data;
  const canSearch = useCan("view_pos");
  const online = useConnection((s) => s.status === "online");
  const save = useQuickEditOrder();
  const sequence = useRef(data.items.length);
  const submitting = useRef(false);
  const searchInput = useRef<HTMLInputElement>(null);
  const [replaceKey, setReplaceKey] = useState<number | null>(null);
  const [lines, setLines] = useState<Line[]>(() =>
    data.items.map((item, key) => ({
      key,
      product_id: item.product_id ?? 0,
      name: item.name ?? "منتج",
      qty: item.qty,
      price: item.price ?? 0,
      color: item.variant_color ?? "",
      sale_mode: item.sale_mode ?? "normal",
      colors: [],
    })),
  );
  const [customer, setCustomer] = useState({
    name: order.customer ?? "",
    phone: order.phone ?? "",
    phone2: order.phone2,
    city: order.city ?? "",
    address: order.address ?? "",
  });
  const [note, setNote] = useState(order.note ?? "");
  const [discount, setDiscount] = useState(order.discount_amount ?? 0);
  const [search, setSearch] = useState("");
  const [dirty, setDirty] = useState(false);
  const [discard, setDiscard] = useState(false);
  const [error, setError] = useState("");
  const panel = useRef<HTMLFormElement>(null);
  const query = useDebouncedValue(search.trim(), 220);
  const products = useQuery({
    queryKey: ["pos", "quick-order-products", query],
    queryFn: () => finora.pos.products({ page: 1, pageSize: 12, search: query }),
    enabled: canSearch && online && query.length >= 2,
  });
  const editable = order.can_edit_invoice;
  const busy = save.isPending;
  const shipping = Math.max(
    0,
    (order.total ?? 0) +
      (order.discount_amount ?? 0) -
      data.items.reduce((sum, item) => sum + item.qty * (item.price ?? 0), 0),
  );
  const subtotal = lines.reduce((sum, item) => sum + item.qty * item.price, 0);
  const total = Math.max(0, subtotal - discount + shipping);
  const patchLine = (key: number, patch: Partial<Line>) => {
    setDirty(true);
    setLines((current) => current.map((line) => (line.key === key ? { ...line, ...patch } : line)));
  };
  const close = () => {
    if (!busy) {
      if (dirty) setDiscard(true);
      else onClose();
    }
  };
  const closeRef = useRef(close);
  closeRef.current = close;

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const frame = requestAnimationFrame(() =>
      panel.current?.querySelector<HTMLElement>("input:not(:disabled), button:not(:disabled)")?.focus(),
    );
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopImmediatePropagation();
        closeRef.current();
      } else if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
        event.preventDefault();
        panel.current?.requestSubmit();
      } else if (event.key === "Tab") {
        const controls = panel.current?.querySelectorAll<HTMLElement>(
          "button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled)",
        );
        const first = controls?.[0];
        const last = controls?.[controls.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }
    };
    window.addEventListener("keydown", key, true);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("keydown", key, true);
      previous?.focus({ preventScroll: true });
    };
  }, []);

  const add = (product: PosProduct) => {
    const color = product.colors[0];
    const nextLine: Line = {
      key: sequence.current++,
      product_id: product.id,
      name: product.name,
      qty: 1,
      price: color?.sale_price ?? product.price,
      color: color?.name ?? "",
      sale_mode: "normal",
      colors: product.colors,
    };
    setLines((current) =>
      replaceKey === null
        ? [...current, nextLine]
        : current.map((line) => (line.key === replaceKey ? nextLine : line)),
    );
    setReplaceKey(null);
    setDirty(true);
    setSearch("");
  };
  const submit = async () => {
    if (submitting.current || busy || !online || !editable || !dirty) return;
    if (order.can_edit_customer && (!customer.name.trim() || !customer.phone.trim())) {
      setError("اسم الزبون ورقم الهاتف مطلوبان.");
      return;
    }
    if (
      !lines.length ||
      lines.some(
        (line) =>
          !line.product_id ||
          !Number.isSafeInteger(line.qty) ||
          line.qty <= 0 ||
          !Number.isSafeInteger(line.price) ||
          line.price <= 0,
      )
    ) {
      setError("أضف منتجاً واحداً على الأقل وتحقق من الكمية والسعر.");
      return;
    }
    if (!Number.isSafeInteger(discount) || discount < 0 || discount > subtotal) {
      setError("الخصم يجب أن لا يتجاوز مجموع المنتجات.");
      return;
    }
    setError("");
    const payload: QuickOrderEdit = {
      note: note.trim() || null,
      discount_amount: discount,
      items: lines.map(({ product_id, qty, price, color, sale_mode }) => ({
        product_id,
        qty,
        price,
        color,
        sale_mode,
      })),
    };
    if (order.can_edit_customer)
      payload.customer = Object.fromEntries(
        Object.entries(customer).map(([key, value]) => [key, value.trim()]),
      ) as typeof customer;
    submitting.current = true;
    try {
      await save.mutateAsync({ id: order.id, input: payload });
      onClose();
    } catch (failure) {
      setError(orderFailureMessage(failure));
    } finally {
      submitting.current = false;
    }
  };

  return createPortal(
    <div
      className="no-drag fixed inset-0 z-[90] grid place-items-center bg-ink/20 p-5"
      onPointerDown={(event) => {
        if (event.target === event.currentTarget) close();
      }}
    >
      <form
        noValidate
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-label={`تعديل سريع للطلب #${order.id}`}
        dir="rtl"
        className="glass-solid flex max-h-[92vh] w-[980px] max-w-full flex-col overflow-hidden rounded-panel shadow-panel"
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <header className="flex shrink-0 items-center gap-3 border-b border-line/70 px-6 py-4">
          <span className="grid h-11 w-11 place-items-center rounded-control bg-maroon-soft text-maroon">
            <Pencil size={22} />
          </span>
          <div className="flex-1">
            <h2 className="text-lg font-bold text-ink">
              تعديل سريع <span className="text-violet">#{order.id}</span>
            </h2>
            <p className="mt-1 text-xs text-ink-soft">عدّل الطلب واحفظ من هنا · Ctrl+Enter للحفظ</p>
          </div>
          <IconButton label="إغلاق التعديل" onClick={close} disabled={busy}>
            <X size={18} />
          </IconButton>
        </header>
        <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-6">
          {!editable && (
            <p role="alert" className="rounded-control bg-warning-soft p-3 text-sm text-ink">
              هذا الطلب غير متاح للتعديل حسب حالته وصلاحياتك.
            </p>
          )}
          {!online && (
            <p role="alert" className="rounded-control bg-warning-soft p-3 text-sm text-ink">
              يلزم الاتصال لحفظ تعديلات الطلب.
            </p>
          )}
          <fieldset disabled={busy || !editable} className="space-y-5">
            <section className="rounded-panel border border-line bg-white/80 p-4">
              <h3 className="mb-3 text-sm font-bold text-ink">بيانات الزبون</h3>
              <div className="grid grid-cols-3 gap-3">
                {(
                  [
                    { key: "name", title: "اسم الزبون", max: 150 },
                    { key: "phone", title: "الهاتف", max: 20 },
                    { key: "phone2", title: "هاتف إضافي", max: 20 },
                    { key: "city", title: "المحافظة", max: 100 },
                    { key: "address", title: "العنوان", max: 255 },
                  ] as const
                ).map((field) => (
                  <Field key={field.key} label={field.title}>
                    <input
                      aria-label={field.title}
                      className={inputClass}
                      maxLength={field.max}
                      disabled={!order.can_edit_customer}
                      value={customer[field.key]}
                      onChange={(event) => {
                        setDirty(true);
                        setCustomer((current) => ({ ...current, [field.key]: event.target.value }));
                      }}
                    />
                  </Field>
                ))}
              </div>
            </section>
            <section className="rounded-panel border border-line bg-white/80 p-4">
              <h3 className="mb-3 text-sm font-bold text-ink">
                منتجات الطلب <span className="text-ink-faint">({lines.length})</span>
              </h3>
              {canSearch && (
                <div className="relative mb-3">
                  {replaceKey !== null && (
                    <div className="mb-2 flex items-center justify-between rounded-control bg-violet-soft px-3 py-2 text-xs text-violet-deep">
                      <span>اختر المنتج البديل لـ {lines.find((line) => line.key === replaceKey)?.name}</span>
                      <button
                        type="button"
                        onClick={() => {
                          setReplaceKey(null);
                          setSearch("");
                        }}
                      >
                        إلغاء التبديل
                      </button>
                    </div>
                  )}
                  <Search size={17} className="pointer-events-none absolute end-3 bottom-3 text-violet" />
                  <input
                    ref={searchInput}
                    aria-label="إضافة منتج للطلب"
                    className={`${inputClass} pe-10`}
                    placeholder="ابحث باسم المنتج أو الباركود لإضافته…"
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                  />
                  {query.length >= 2 && search.trim() === query && (
                    <div className="absolute inset-x-0 top-full mt-1 z-10 max-h-56 overflow-auto rounded-control border border-line bg-white shadow-panel">
                      {products.isFetching && <p className="p-3 text-sm text-ink-soft">جارٍ البحث…</p>}
                      {products.error && (
                        <p role="alert" className="p-3 text-sm text-danger">
                          {orderFailureMessage(products.error)}
                        </p>
                      )}
                      {!products.isFetching && !products.error && !products.data?.rows.length && (
                        <p className="p-3 text-sm text-ink-soft">لا توجد منتجات مطابقة.</p>
                      )}
                      {!products.isFetching &&
                        products.data?.rows.map((product) => (
                          <button
                            key={product.id}
                            type="button"
                            className="flex w-full items-center gap-3 border-b border-line/50 p-3 text-start hover:bg-violet-soft"
                            onClick={() => add(product)}
                          >
                            <Plus size={17} className="shrink-0 text-violet" />
                            <span className="min-w-0 flex-1">
                              <span className="block text-sm font-semibold text-ink">{product.name}</span>
                              <span className="text-xs text-ink-soft">
                                {product.sku} · المتوفر {product.quantity}
                              </span>
                            </span>
                            <span className="shrink-0 text-sm font-semibold text-violet">
                              {formatIqd(product.price)}
                            </span>
                          </button>
                        ))}
                    </div>
                  )}
                </div>
              )}
              <div className="overflow-x-auto">
                <table aria-label="منتجات تعديل الطلب" className="w-full text-start text-sm">
                  <thead className="bg-violet-soft/50 text-xs text-ink-soft">
                    <tr>
                      {["المنتج", "الكمية", "السعر", "الإجمالي", ""].map((label, index) => (
                        <th key={index} className="p-2 text-start font-medium">
                          {label}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {lines.map((line) => (
                      <tr key={line.key} className="border-b border-line/60">
                        <td className="min-w-[210px] p-2">
                          <span className="font-semibold text-ink">{line.name}</span>
                          {line.colors.length ? (
                            <select
                              aria-label={`${line.colors.some((option) => option.attributes && Object.keys(option.attributes).some((axis) => axis !== "اللون")) ? "خيار" : "لون"} ${line.name}`}
                              className={`${inputClass} mt-1 !h-8`}
                              value={line.color}
                              onChange={(event) => {
                                const color = line.colors.find((entry) => entry.name === event.target.value);
                                patchLine(line.key, {
                                  color: event.target.value,
                                  ...(color?.sale_price != null ? { price: color.sale_price } : {}),
                                });
                              }}
                            >
                              {line.colors.map((color) => (
                                <option key={color.name} value={color.name}>
                                  {color.name} · {color.qty ?? 0}
                                </option>
                              ))}
                            </select>
                          ) : (
                            line.color && (
                              <span className="mt-1 block text-xs text-ink-soft">الخيار: {line.color}</span>
                            )
                          )}
                        </td>
                        <td className="w-24 p-2">
                          <input
                            aria-label={`كمية ${line.name}`}
                            dir="ltr"
                            type="number"
                            min={1}
                            step={1}
                            className={`${inputClass} text-center`}
                            value={line.qty}
                            onChange={(event) => patchLine(line.key, { qty: Number(event.target.value) })}
                          />
                        </td>
                        <td className="w-36 p-2">
                          {order.can_edit_price ? (
                            <MoneyInput
                              label={`سعر ${line.name}`}
                              value={line.price}
                              onChange={(price) => patchLine(line.key, { price })}
                              className="w-full"
                            />
                          ) : (
                            <span className="whitespace-nowrap text-ink">{formatIqd(line.price)}</span>
                          )}
                        </td>
                        <td className="whitespace-nowrap p-2 font-semibold text-ink">
                          {formatIqd(line.qty * line.price)}
                        </td>
                        <td className="p-2">
                          {canSearch && (
                            <IconButton
                              label={`تبديل ${line.name}`}
                              onClick={() => {
                                setReplaceKey(line.key);
                                setSearch("");
                                searchInput.current?.focus();
                              }}
                            >
                              <RefreshCcw size={16} className="text-violet" />
                            </IconButton>
                          )}
                          <IconButton
                            label={`حذف ${line.name}`}
                            onClick={() => {
                              setDirty(true);
                              setLines((current) => current.filter((item) => item.key !== line.key));
                            }}
                          >
                            <Trash2 size={16} className="text-danger" />
                          </IconButton>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {!lines.length && <p className="py-4 text-center text-sm text-ink-soft">أضف منتجاً للطلب.</p>}
            </section>
            <div className="grid grid-cols-[1fr_240px] gap-4">
              <Field label="ملاحظات الطلب">
                <textarea
                  aria-label="ملاحظات الطلب"
                  className={`${inputClass} !h-24 resize-none py-3`}
                  maxLength={4000}
                  value={note}
                  onChange={(event) => {
                    setDirty(true);
                    setNote(event.target.value);
                  }}
                />
              </Field>
              <Field label="الخصم">
                <MoneyInput
                  label="خصم الطلب"
                  value={discount}
                  onChange={(value) => {
                    setDirty(true);
                    setDiscount(value);
                  }}
                  className="!h-10 w-full"
                />
                <p className="mt-2 text-xs text-ink-soft">
                  مجموع المنتجات: {formatIqd(subtotal)}
                  {shipping > 0 && <span className="mt-1 block">أجور التوصيل: {formatIqd(shipping)}</span>}
                </p>
              </Field>
            </div>
          </fieldset>
          {error && (
            <p role="alert" className="rounded-control bg-danger-soft p-3 text-sm text-danger">
              {error}
            </p>
          )}
        </div>
        <footer className="shrink-0 border-t border-line/70 bg-white/80 px-6 py-4">
          {discard ? (
            <div className="flex items-center gap-3">
              <p className="flex-1 text-sm text-ink">عندك تعديلات غير محفوظة. تريد تتركها؟</p>
              <button type="button" className={secondary} onClick={() => setDiscard(false)}>
                متابعة التعديل
              </button>
              <button
                type="button"
                className="h-10 rounded-control bg-danger px-4 text-sm font-semibold text-white"
                onClick={onClose}
              >
                ترك التعديلات
              </button>
            </div>
          ) : (
            <div className="flex items-center gap-3">
              <div className="flex-1">
                <p className="text-xs text-ink-soft">الإجمالي بعد التعديل</p>
                <p className="mt-1 text-xl font-bold text-maroon">{formatIqd(total)}</p>
              </div>
              <button type="button" className={secondary} disabled={busy} onClick={close}>
                تراجع
              </button>
              <button
                type="submit"
                disabled={busy || !online || !editable || !dirty}
                className="flex h-11 items-center gap-2 rounded-control bg-maroon px-5 text-sm font-bold text-white shadow-control disabled:opacity-45"
              >
                {busy ? <Loader2 size={17} className="animate-spin" /> : <Save size={17} />}
                {busy ? "جارٍ الحفظ…" : "حفظ التعديلات"}
              </button>
            </div>
          )}
        </footer>
      </form>
    </div>,
    document.body,
  );
}

export function QuickOrderEditor({ orderId, onClose }: { orderId: number; onClose(): void }) {
  const details = useOrderDetails(orderId);
  if (details.data) return <EditForm key={orderId} data={details.data} onClose={onClose} />;
  return createPortal(
    <div className="no-drag fixed inset-0 z-[90] grid place-items-center bg-ink/20">
      <div
        role="dialog"
        aria-modal="true"
        aria-label="تحميل تعديل الطلب"
        dir="rtl"
        className="glass-solid w-[420px] rounded-panel p-6"
      >
        <p role={details.error ? "alert" : undefined} className="text-sm text-ink">
          {details.error ? orderFailureMessage(details.error) : "جارٍ تحميل الطلب…"}
        </p>
        <div className="mt-4 flex gap-2">
          {details.error && (
            <button type="button" className={secondary} onClick={() => void details.refetch()}>
              إعادة المحاولة
            </button>
          )}
          <button type="button" className={secondary} onClick={onClose}>
            إغلاق
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
