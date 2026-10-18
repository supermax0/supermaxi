import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Package, Plus, Trash2 } from "lucide-react";
import { useRef, useState } from "react";
import { finora, toFinoraError } from "@/api/finora";
import type { SupplierRow, SupplierSaleProduct } from "@/api/finora/suppliers";
import { IconButton } from "@/components/IconButton";
import { MoneyInput } from "@/components/MoneyInput";
import { SearchBox } from "@/components/SearchBox";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { canMutate, useConnection } from "@/stores/connection";
import { toast } from "@/stores/toasts";
import { useOffline } from "@/stores/offline";
import { desktopBridge } from "@/services/bridge";
import { cn } from "@/utils/cn";
import { formatIqd } from "@/utils/money";
import {
  SupplierModal,
  supplierInput,
  supplierPrimary,
  supplierSecondary,
  useRefreshSuppliers,
} from "./SupplierDialogs";

interface Line {
  key: number;
  product: SupplierSaleProduct;
  qty: number;
  price: number;
  color: string;
}

export function SupplierSaleDialog({ supplier, onClose }: { supplier: SupplierRow; onClose(): void }) {
  const [searchText, setSearchText] = useState("");
  const search = useDebouncedValue(searchText.trim(), 250);
  const [lines, setLines] = useState<Line[]>([]);
  const [note, setNote] = useState("");
  const [reservedSale, setReservedSale] = useState(false);
  const nextKey = useRef(0);
  const online = useConnection((s) => s.status === "online");
  const offline = useOffline((s) => s.status);
  const client = useQueryClient();
  const refresh = useRefreshSuppliers();
  const products = useQuery({
    queryKey: ["suppliers", "sale-products", search],
    queryFn: () => finora.suppliers.saleProducts(search),
    enabled: (online || offline.available) && !!search,
    staleTime: 0,
  });
  const total = lines.reduce((sum, line) => sum + line.qty * line.price, 0);
  const remaining = supplier.remaining - total;
  const reserve = useMutation({
    mutationFn: async () => {
      const bridge = desktopBridge().offline;
      if (!bridge?.reserveStock) throw new Error("حدّث التطبيق لتفعيل حصة المخزون.");
      const quantities = new Map<string, { product_id: number; qty: number; variant_color?: string }>();
      for (const line of lines) {
        const key = `${line.product.id}:${line.color}`;
        const item = quantities.get(key) ?? {
          product_id: line.product.id,
          qty: 0,
          ...(line.color ? { variant_color: line.color } : {}),
        };
        item.qty += line.qty;
        quantities.set(key, item);
      }
      return bridge.reserveStock([...quantities.values()]);
    },
    onSuccess: (status) => {
      useOffline.getState().set(status);
      setReservedSale(true);
      toast.success("تم حجز الكمية لهذا الجهاز. يمكنك اعتماد البيع من الحصة بدون نت.");
    },
  });
  let validation = "";
  const quantities = new Map<number, number>();
  const colors = new Map<string, number>();
  for (const line of lines) {
    if (!Number.isInteger(line.qty) || line.qty < 1 || !Number.isInteger(line.price) || line.price < 1) {
      validation = "أدخل كمية وسعر بيع أكبر من صفر لكل منتج.";
      break;
    }
    const requested = (quantities.get(line.product.id) ?? 0) + line.qty;
    quantities.set(line.product.id, requested);
    if (!reservedSale && requested > line.product.quantity)
      validation = `الكمية المطلوبة من ${line.product.name} تتجاوز المخزون المتوفر.`;
    if (line.product.has_colors) {
      const color = line.product.colors.find((c) => c.name === line.color);
      if (!color) {
        validation = `اختر لون ${line.product.name}.`;
        break;
      }
      const key = `${line.product.id}:${line.color}`;
      const colorQty = (colors.get(key) ?? 0) + line.qty;
      colors.set(key, colorQty);
      if (!reservedSale && colorQty > color.qty)
        validation = `الكمية المطلوبة من لون ${line.color} تتجاوز المخزون المتوفر.`;
    }
  }
  if (total > 2147483647) validation = "قيمة الفاتورة تتجاوز الحد المسموح.";
  const save = useMutation({
    mutationFn: async () => {
      if (!lines.length || validation) throw new Error(validation || "أضف منتجاً إلى الفاتورة.");
      const bridge = desktopBridge().offline;
      if (offline.available && bridge) {
        const saved = await bridge.saveSupplierDraft({
          supplierId: supplier.id,
          supplierName: supplier.name,
          items: lines.map((line) => ({
            product_id: line.product.id,
            qty: line.qty,
            price: line.price,
            ...(line.color ? { variant_color: line.color } : {}),
          })),
          note,
          ...(reservedSale ? { stockMode: "reserved" as const } : {}),
        });
        // Local acknowledgment precedes transmission. A lost reply remains in the durable queue.
        if (canMutate()) {
          try {
            await bridge.synchronize();
          } catch (error) {
            useOffline.getState().set({
              ...useOffline.getState().status,
              error: error instanceof Error ? error.message : "المسودة محفوظة لكن تعذّرت المزامنة.",
            });
          }
        }
        void client.invalidateQueries({ queryKey: ["offline"] });
        return { local: true as const, id: saved.id, localInvoiceNo: saved.localInvoiceNo };
      }
      if (!canMutate()) throw new Error("يلزم تسجيل دخول أونلاين لتجهيز التخزين المحلي أولاً.");
      return finora.suppliers.sell(
        supplier.id,
        lines.map((line) => ({
          product_id: line.product.id,
          qty: line.qty,
          price: line.price,
          ...(line.color ? { variant_color: line.color } : {}),
        })),
        note,
      );
    },
    onSuccess: async (result) => {
      if ("local" in result) {
        let status;
        try {
          status = await desktopBridge().offline?.status();
        } catch (error) {
          useOffline.getState().set({
            ...useOffline.getState().status,
            error: error instanceof Error ? error.message : "تعذّر تحديث حالة المسودة المحفوظة.",
          });
        }
        if (status) useOffline.getState().set(status);
        const operation = status?.operations.find((o) => o.id === result.id);
        if (operation?.status === "done") toast.success(`تم تسجيل البيع — ${operation.invoiceNo}`);
        else if (result.localInvoiceNo)
          toast.success(
            `البيع محفوظ من حصة الجهاز — ${result.localInvoiceNo}${operation?.status === "conflict" ? " · يحتاج مراجعة عند الترحيل" : " · بانتظار الترحيل للسيرفر"}`,
          );
        else
          toast.info(
            operation?.status === "conflict"
              ? `المسودة محفوظة وتحتاج مراجعة: ${operation.error}`
              : "المسودة محفوظة محلياً وتنتظر تحقق السيرفر. راجعها من إعدادات الأوفلاين والمزامنة.",
          );
      } else toast.success(`تم تسجيل البيع — ${result.invoice_no}`);
      onClose();
      await Promise.all([refresh(), client.invalidateQueries({ queryKey: ["products"] })]);
    },
  });
  const patch = (key: number, changes: Partial<Line>) => {
    save.reset();
    setLines((current) => current.map((line) => (line.key === key ? { ...line, ...changes } : line)));
  };
  const add = (product: SupplierSaleProduct) => {
    save.reset();
    const key = nextKey.current++;
    setLines((current) => {
      const existing = current.find((line) => line.product.id === product.id && !product.has_colors);
      return existing
        ? current.map((line) => (line.key === existing.key ? { ...line, qty: line.qty + 1, product } : line))
        : [...current, { key, product, qty: 1, price: product.sale_price, color: "" }];
    });
    setSearchText("");
  };
  return (
    <SupplierModal title="بيع للمورد" wide busy={save.isPending || reserve.isPending} onClose={onClose}>
      <fieldset disabled={save.isPending || reserve.isPending} className="space-y-4 disabled:opacity-60">
        <div className="flex items-center justify-between gap-4 rounded-control border border-line/70 bg-violet-soft/45 px-4 py-3">
          <div>
            <p className="text-xs text-ink-faint">المورد</p>
            <p className="mt-1 font-semibold text-ink">{supplier.name}</p>
          </div>
          <div className="text-left">
            <p className="text-xs text-ink-faint">
              {supplier.remaining < 0 ? "الرصيد الحالي لنا" : "المستحق الحالي للمورد"}
            </p>
            <p className="mt-1 text-sm font-semibold text-violet">
              {formatIqd(Math.abs(supplier.remaining))}
            </p>
          </div>
        </div>
        <div className="relative">
          <SearchBox
            value={searchText}
            onChange={setSearchText}
            scanner
            busy={products.isFetching}
            placeholder="ابحث عن منتج بالاسم أو الكود أو الباركود…"
          />
          {!!searchText.trim() && search === searchText.trim() && (
            <div className="mt-2 max-h-48 overflow-y-auto rounded-control border border-line bg-white shadow-control">
              {products.isError ? (
                <p role="alert" className="p-3 text-sm text-danger">
                  {toFinoraError(products.error).message}
                </p>
              ) : products.isFetching ? (
                <p className="p-3 text-sm text-ink-faint">جارٍ البحث عن المنتجات…</p>
              ) : !products.data?.length ? (
                <p className="p-3 text-sm text-ink-faint">لا توجد منتجات مطابقة.</p>
              ) : (
                products.data.map((product) => (
                  <button
                    key={product.id}
                    type="button"
                    disabled={(!online && !offline.available) || product.quantity < 1 || lines.length >= 100}
                    onClick={() => add(product)}
                    className="flex w-full items-center gap-3 border-b border-line/40 px-4 py-3 text-right last:border-0 hover:bg-violet-soft/60 disabled:opacity-45"
                  >
                    <Package size={18} className="text-violet" />
                    <span className="min-w-0 flex-1">
                      <span className="block text-sm font-medium text-ink">{product.name}</span>
                      <span className="text-xs text-ink-faint">
                        {product.sku || product.barcode} · المتوفر {product.quantity}
                      </span>
                    </span>
                    <span className="text-sm text-violet">{formatIqd(product.sale_price)}</span>
                    <Plus size={16} className="text-violet" />
                  </button>
                ))
              )}
            </div>
          )}
        </div>
        {!lines.length ? (
          <div className="rounded-control border border-dashed border-line py-8 text-center">
            <Package size={28} className="mx-auto mb-2 text-violet/50" />
            <p className="text-sm text-ink-soft">ابحث عن المنتجات وأضفها إلى فاتورة البيع</p>
          </div>
        ) : (
          <div className="overflow-x-auto rounded-control border border-line/80">
            <table className="w-full min-w-[600px] text-right text-sm" aria-label="منتجات البيع للمورد">
              <thead className="bg-violet-soft/60 text-xs text-ink-soft">
                <tr>
                  <th className="px-3 py-3">المنتج</th>
                  <th className="px-2 py-3">الكمية</th>
                  <th className="px-2 py-3">سعر البيع</th>
                  <th className="px-2 py-3">الإجمالي</th>
                  <th className="w-12">
                    <span className="sr-only">حذف</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {lines.map((line) => (
                  <tr key={line.key} className="border-t border-line/60 bg-white/75">
                    <td className="max-w-[260px] px-3 py-3">
                      <p className="font-medium text-ink">{line.product.name}</p>
                      {line.product.has_colors && (
                        <select
                          aria-label={`لون ${line.product.name}`}
                          value={line.color}
                          onChange={(e) => {
                            const color = line.product.colors.find((c) => c.name === e.target.value);
                            patch(line.key, {
                              color: e.target.value,
                              price: color?.sale_price ?? line.product.sale_price,
                            });
                          }}
                          className={cn(supplierInput, "mt-2 h-9 text-xs")}
                        >
                          <option value="">اختر اللون</option>
                          {line.product.colors.map((color) => (
                            <option key={color.name} value={color.name} disabled={color.qty < 1}>
                              {color.name} — المتوفر {color.qty}
                            </option>
                          ))}
                        </select>
                      )}
                      <p className="mt-1 text-[11px] text-ink-faint">
                        المتوفر{" "}
                        {line.color
                          ? (line.product.colors.find((c) => c.name === line.color)?.qty ?? 0)
                          : line.product.quantity}
                      </p>
                    </td>
                    <td className="w-20 px-2">
                      <input
                        aria-label={`كمية ${line.product.name}`}
                        type="number"
                        inputMode="numeric"
                        min={1}
                        step={1}
                        value={line.qty || ""}
                        onChange={(e) => patch(line.key, { qty: Number(e.target.value) })}
                        className={cn(supplierInput, "h-9 px-2 text-center")}
                      />
                    </td>
                    <td className="w-36 px-2">
                      <MoneyInput
                        label={`سعر بيع ${line.product.name}`}
                        value={line.price}
                        onChange={(price) => patch(line.key, { price })}
                        className="w-full"
                      />
                    </td>
                    <td className="whitespace-nowrap px-2 font-semibold text-ink">
                      {formatIqd(line.qty * line.price)}
                    </td>
                    <td className="px-2">
                      <IconButton
                        label={`حذف ${line.product.name}`}
                        onClick={() => {
                          save.reset();
                          setLines((current) => current.filter((l) => l.key !== line.key));
                        }}
                      >
                        <Trash2 size={16} />
                      </IconButton>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <label className="block text-xs text-ink-soft">
          ملاحظات <span className="text-ink-faint">(اختياري)</span>
          <input
            maxLength={255}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="ملاحظة على الفاتورة"
            className={cn(supplierInput, "mt-2")}
          />
        </label>
        <div className="grid grid-cols-2 gap-4 rounded-control border border-line/70 bg-white/80 p-4">
          <div>
            <p className="text-xs text-ink-faint">إجمالي فاتورة البيع</p>
            <p className="mt-1 text-xl font-bold text-violet">{formatIqd(total)}</p>
          </div>
          <div>
            <p className="text-xs text-ink-faint">
              {remaining < 0 ? "رصيد لنا بعد البيع" : "المستحق للمورد بعد البيع"}
            </p>
            <p className={cn("mt-1 text-xl font-bold", remaining < 0 ? "text-emerald-600" : "text-maroon")}>
              {formatIqd(Math.abs(remaining))}
            </p>
          </div>
          <p className="col-span-2 text-xs leading-5 text-ink-soft">
            تُخصم قيمة البيع من حساب المورد، ولا تُسجَّل كدفعة نقدية.
          </p>
        </div>
        {validation && (
          <p role="alert" className="text-sm text-danger">
            {validation}
          </p>
        )}
        {save.isError && (
          <p role="alert" className="rounded-control bg-maroon-soft p-3 text-sm text-danger">
            {toFinoraError(save.error).message}
          </p>
        )}
        {offline.available && desktopBridge().offline?.reserveStock && (
          <div className="space-y-3 rounded-control border border-line/70 bg-violet-soft/35 p-3 text-xs text-ink-soft">
            <div className="flex items-center justify-between gap-3">
              <label className="flex items-center gap-2 font-semibold text-violet">
                <input
                  type="checkbox"
                  checked={reservedSale}
                  onChange={(event) => {
                    setReservedSale(event.target.checked);
                    save.reset();
                  }}
                  className="accent-violet"
                />
                اعتماد البيع من حصة هذا الجهاز
              </label>
              {online && (
                <button
                  type="button"
                  className={cn(supplierSecondary, "text-xs")}
                  disabled={
                    !lines.length || !!validation || offline.stock?.busy || offline.stock?.pendingRequest
                  }
                  onClick={() => reserve.mutate()}
                >
                  {reserve.isPending ? "جارٍ الحجز…" : "حجز هذه الكمية للجهاز"}
                </button>
              )}
            </div>
            <p className="leading-5">
              احجز الكمية أونلاين قبل الانقطاع. البيع من الحصة يحصل على رقم محلي ويستهلكها فوراً؛ لا يمكن لأي
              جهاز آخر استهلاك نفس الكمية. الحصة مرتبطة بالمستخدم والفرع الحالي.
            </p>
            {lines.map((line) => (
              <p key={line.key} className="text-ink-faint">
                {line.product.name}
                {line.color ? ` · ${line.color}` : ""} — المتبقي من حصة الجهاز:{" "}
                {offline.stock?.rows
                  .filter((row) => row.productId === line.product.id && row.color === line.color)
                  .reduce((sum, row) => sum + row.available, 0) ?? 0}
              </p>
            ))}
            {reserve.isError && (
              <p role="alert" className="text-danger">
                {toFinoraError(reserve.error).message}
              </p>
            )}
          </div>
        )}
        {!online && (
          <p role="status" className="text-xs leading-6 text-ink-soft">
            {reservedSale
              ? "سيُحفظ البيع ويُخصم من حصة هذا الجهاز في نفس الخطوة. يبقى ترحيل الحساب والفاتورة إلى السيرفر عند عودة الاتصال."
              : offline.available
                ? "ستُحفظ مسودة محلية بانتظار تحقق السيرفر؛ الرصيد المعروض تقديري ولا تعتمد البيع أو تسلّم البضاعة قبل التأكيد."
                : "يلزم تسجيل دخول أونلاين لتجهيز التخزين المحلي أولاً."}
          </p>
        )}
        <footer className="flex justify-end gap-2 pt-1">
          <button type="button" onClick={onClose} className={supplierSecondary}>
            إلغاء
          </button>
          <button
            type="button"
            disabled={(!online && !offline.available) || !lines.length || !!validation || save.isPending}
            onClick={() => save.mutate()}
            className={supplierPrimary}
          >
            {save.isPending && <Loader2 size={16} className="animate-spin" />}
            {reservedSale ? "اعتماد البيع من الحصة" : online ? "تسجيل البيع" : "حفظ مسودة للمزامنة"}
          </button>
        </footer>
      </fieldset>
    </SupplierModal>
  );
}
