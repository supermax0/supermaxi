import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ScanBarcode, UserPlus, UserRound } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type RefObject } from "react";
import { finora, toFinoraError } from "@/api/finora";
import type { PosCustomer, PosProduct } from "@/api/finora/pos";
import { ConfirmDialog, PickerDialog } from "@/components/Dialog";
import { Popover } from "@/components/Popover";
import { CONFIG_QUERY_KEY } from "@/features/auth/LoginScreen";
import { bankAccountsFor } from "@/features/pos/bankAccounts";
import { cartTotals, useCart } from "@/features/pos/cart";
import { usePosPreferences } from "@/features/pos/posPreferences";
import { useCheckout } from "@/features/pos/useCheckout";
import { scanBeep } from "@/features/pos/feedback";
import { posKeys, type PosProductsQuery } from "@/features/pos/queries";
import { useBarcodeScanner } from "@/hooks/useBarcodeScanner";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { toast } from "@/stores/toasts";
import { useWindowManager } from "@/stores/windowManager";
import { cn } from "@/utils/cn";
import { formatIqd } from "@/utils/money";
import { CartPanel } from "./CartPanel";
import { CustomerPanel } from "./CustomerPanel";
import { EditInvoiceDialog } from "./EditInvoiceDialog";
import { OperatingBranchGate } from "./OperatingBranchGate";
import { ProductsPanel } from "./ProductsPanel";
import { SaleTypePicker } from "./SaleTypePicker";
import { canMutate, useConnection } from "@/stores/connection";
import { useOffline } from "@/stores/offline";

const panel = "glass-solid min-h-0 overflow-hidden rounded-window";
const field =
  "flex h-12 items-center gap-3 rounded-control border border-line bg-white/90 px-4 shadow-control focus-within:border-violet/45 focus-within:ring-4 focus-within:ring-violet/10";

function CustomerSearch({
  branchId,
  onAdd,
  inputRef,
}: {
  branchId: number | null;
  onAdd(): void;
  inputRef: RefObject<HTMLInputElement>;
}) {
  const setCustomer = useCart((s) => s.setCustomer);
  const [text, setText] = useState("");
  const [open, setOpen] = useState(false);
  const anchor = useRef<HTMLDivElement>(null);
  const q = useDebouncedValue(text.trim(), 300);
  const results = useQuery({
    queryKey: ["pos", "customers", q, branchId],
    queryFn: () => finora.pos.searchCustomers(q, branchId),
    enabled: q.length >= 2,
    placeholderData: keepPreviousData,
  });

  const choose = (customer: PosCustomer) => {
    if (customer.blacklisted) {
      toast.error(customer.blacklist_message || "هذا الزبون في القائمة السوداء.");
      return;
    }
    setCustomer(customer);
    setText("");
    setOpen(false);
  };

  return (
    <div className="relative flex min-w-0 flex-1 gap-3" ref={anchor}>
      <button
        type="button"
        onClick={onAdd}
        className="flex h-12 shrink-0 items-center gap-2 rounded-control bg-azure-soft/80 px-4 text-sm font-semibold text-azure ring-1 ring-azure/15 hover:bg-azure-soft"
      >
        <UserPlus size={18} aria-hidden />
        إضافة زبون
      </button>
      <label className={cn(field, "min-w-0 flex-1")}>
        <input
          ref={inputRef}
          value={text}
          onChange={(event) => {
            setText(event.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          placeholder="البحث عن زبون بالاسم أو الرقم…"
          aria-label="البحث عن زبون"
          className="h-full min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-ink-faint"
        />
        <UserRound size={18} className="text-ink-faint" aria-hidden />
      </label>
      <Popover
        open={open && q.length >= 2}
        onClose={() => setOpen(false)}
        anchor={anchor}
        label="نتائج الزبائن"
        align="end"
        width={360}
      >
        {results.isLoading && <p className="px-3 py-4 text-sm text-ink-faint">جارٍ البحث…</p>}
        {results.error && (
          <p className="px-3 py-4 text-sm text-danger">{toFinoraError(results.error).message}</p>
        )}
        {results.data?.length === 0 && <p className="px-3 py-4 text-sm text-ink-faint">لا يوجد زبون مطابق</p>}
        <ul className="max-h-[300px] overflow-y-auto">
          {results.data?.map((customer) => (
            <li key={customer.id}>
              <button
                type="button"
                onClick={() => choose(customer)}
                className="flex w-full items-center gap-3 rounded-control px-3 py-2.5 text-start hover:bg-violet-soft"
              >
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-semibold text-ink">{customer.name}</span>
                  <span className="block truncate text-xs text-ink-faint">{customer.city}</span>
                </span>
                <span className="ltr-isolate text-xs text-ink-soft">{customer.phone}</span>
                {customer.blacklisted && (
                  <span className="rounded-full bg-danger-soft px-2 text-[11px] text-danger">محظور</span>
                )}
              </button>
            </li>
          ))}
        </ul>
      </Popover>
    </div>
  );
}

export function PosWindow() {
  const active = useWindowManager((s) => s.active === "pos");
  const saleType = useCart((s) => s.saleType);
  const setSaleType = useCart((s) => s.setSaleType);
  const add = useCart((s) => s.add);
  const prefs = usePosPreferences();
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");
  const [page, setPage] = useState(1);
  const [addingCustomer, setAddingCustomer] = useState(false);
  const [colorFor, setColorFor] = useState<PosProduct | null>(null);
  const [saleFor, setSaleFor] = useState<{ product: PosProduct; color: string } | null>(null);
  const [editOpen, setEditOpen] = useState(false);
  const [bankAccountId, setBankAccountId] = useState<number | null>(prefs.defaultBankAccountId);
  const [confirmTotal, setConfirmTotal] = useState<{ print: boolean; total: number } | null>(null);
  const [reservedSale, setReservedSale] = useState(false);
  const [reserving, setReserving] = useState(false);
  const online = useConnection((s) => s.status === "online");
  const offline = useOffline((s) => s.status);
  const lines = useCart((s) => s.lines);
  const quotaAvailable = (productId: number, color: string) =>
    (offline.stock?.rows ?? [])
      .filter((r) => r.productId === productId && r.color === color)
      .reduce((n, r) => n + r.available, 0);
  const reserveCart = async () => {
    const bridge = window.finoraDesktop?.offline;
    if (!bridge || !canMutate() || !lines.length || reserving) return;
    setReserving(true);
    try {
      const items = lines.map((l) => ({
        product_id: l.productId,
        qty: l.qty,
        ...(l.color ? { variant_color: l.color } : {}),
      }));
      useOffline.getState().set(await bridge.reserveStock(items));
      setReservedSale(true);
      toast.success("تم حجز كميات السلة لهذا الجهاز؛ تقدر تبيعها بدون نت.");
    } catch (error) {
      toast.error(toFinoraError(error).message);
    } finally {
      setReserving(false);
    }
  };
  const searchInput = useRef<HTMLInputElement>(null);
  const customerInput = useRef<HTMLInputElement>(null);
  const debouncedSearch = useDebouncedValue(search, 250);

  const config = useQuery({
    queryKey: CONFIG_QUERY_KEY,
    queryFn: () => finora.config.get(),
    staleTime: Infinity,
  });
  const serverUrl = config.data?.serverUrl ?? null;
  const bootstrap = useQuery({
    queryKey: posKeys.bootstrap,
    queryFn: () => finora.pos.bootstrap(),
    staleTime: 5 * 60_000,
  });
  const query = useMemo<PosProductsQuery>(
    () => ({ page, pageSize: prefs.pageSize, search: debouncedSearch, category: category || undefined }),
    [page, prefs.pageSize, debouncedSearch, category],
  );
  const products = useQuery({
    queryKey: posKeys.products(query),
    queryFn: () => finora.pos.products(query),
  });
  const accounts = useQuery({
    queryKey: ["pos", "accounts"],
    queryFn: () => finora.pos.paymentAccounts(),
    enabled: bootstrap.data?.can_pay ?? false,
    staleTime: 5 * 60_000,
  });
  const bankAccounts = useMemo(
    () => bankAccountsFor(accounts.data ?? [], bootstrap.data?.branch_id ?? null),
    [accounts.data, bootstrap.data?.branch_id],
  );
  const checkout = useCheckout();

  useEffect(() => {
    if (useCart.getState().lines.length === 0) setSaleType(prefs.defaultSaleType);
  }, [prefs.defaultSaleType, setSaleType]);
  // Keep the chosen account valid for this branch; auto-pick when there is only one.
  useEffect(() => {
    if (bankAccounts.length === 0) return;
    if (bankAccountId !== null && bankAccounts.some((a) => a.id === bankAccountId)) return;
    const preferred = bankAccounts.find((a) => a.id === prefs.defaultBankAccountId);
    setBankAccountId(preferred?.id ?? (bankAccounts.length === 1 ? (bankAccounts[0]?.id ?? null) : null));
  }, [bankAccounts, bankAccountId, prefs.defaultBankAccountId]);

  const chooseSaleMode = useCallback(
    (product: PosProduct, color = "") => {
      if (product.has_exchange_sale && (product.exchange_sale_price ?? 0) > 0) {
        setSaleFor({ product, color });
        return;
      }
      const line = add(product, color);
      const used = useCart
        .getState()
        .lines.filter((item) => item.productId === product.id && item.color === color)
        .reduce((sum, item) => sum + item.qty, 0);
      if (used > line.available)
        toast.info(`${product.name}: الكمية أكبر من المتوفر — سيُقفل الطلب بانتظار المخزون`);
    },
    [add],
  );
  const addProduct = useCallback(
    (product: PosProduct) => {
      if (product.has_colors && product.colors.length > 0) {
        setColorFor(product);
        return;
      }
      chooseSaleMode(product);
    },
    [chooseSaleMode],
  );

  /** Barcode: exactly one match → straight into the cart (POS behaviour); otherwise show the matches. */
  const lookupCode = useCallback(
    async (code: string) => {
      setSearch(code);
      setPage(1);
      const { scanAddsToCart, scanSound } = usePosPreferences.getState();
      if (!scanAddsToCart) return;
      try {
        const found = await finora.pos.products({ page: 1, pageSize: 2, search: code });
        const [only] = found.rows;
        if (found.rows.length === 1 && only) {
          addProduct(only);
          setSearch("");
          if (scanSound) scanBeep(true);
        } else if (found.rows.length === 0) {
          if (scanSound) scanBeep(false);
          toast.error(`لا يوجد منتج بالباركود ${code}`);
        }
      } catch (error) {
        toast.error(toFinoraError(error).message);
      }
    },
    [addProduct],
  );
  useBarcodeScanner(
    useCallback((code: string) => void lookupCode(code), [lookupCode]),
    active && !addingCustomer && !editOpen && !colorFor && !saleFor,
  );

  const execute = useCallback(
    (print: boolean) => {
      if (!bootstrap.data || checkout.isPending) return;
      checkout.mutate({ print, bootstrap: bootstrap.data, bankAccountId, reserved: reservedSale });
    },
    [bootstrap.data, checkout, bankAccountId, reservedSale],
  );
  /** Large sales (Settings → حد التأكيد) ask once before going to FINORA. */
  const runCheckout = useCallback(
    (print: boolean) => {
      const { lines, discountMode, discountValue } = useCart.getState();
      const { total } = cartTotals(lines, discountMode, discountValue);
      const limit = usePosPreferences.getState().confirmAbove;
      if (limit > 0 && total > limit) setConfirmTotal({ print, total });
      else execute(print);
    },
    [execute],
  );

  // Cashier shortcuts while the POS window is open.
  useEffect(() => {
    if (!active) return;
    const onKey = (event: KeyboardEvent) => {
      if (document.querySelector('[aria-modal="true"]')) return;
      if (event.key === "F2") {
        event.preventDefault();
        searchInput.current?.focus();
        searchInput.current?.select();
      } else if (event.key === "F3") {
        event.preventDefault();
        customerInput.current?.focus();
      } else if (event.key === "F9" || (event.key === "Enter" && (event.ctrlKey || event.metaKey))) {
        event.preventDefault();
        if (useCart.getState().lines.length > 0) {
          runCheckout(usePosPreferences.getState().autoPrint && (bootstrap.data?.can_print ?? false));
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [active, runCheckout, bootstrap.data]);

  return (
    <div className="flex h-full flex-col gap-3">
      <div className="flex items-center gap-3">
        <SaleTypePicker
          value={saleType}
          onChange={setSaleType}
          canPay={bootstrap.data?.can_pay !== false}
          bankAccounts={bankAccounts}
          bankAccountId={bankAccountId}
          onBankAccount={setBankAccountId}
          loadingAccounts={accounts.isLoading}
        />
        <CustomerSearch
          branchId={bootstrap.data?.branch_id ?? null}
          onAdd={() => setAddingCustomer(true)}
          inputRef={customerInput}
        />
        <label className={cn(field, "min-w-0 flex-[1.2]")}>
          <input
            ref={searchInput}
            type="search"
            value={search}
            onChange={(event) => {
              setSearch(event.target.value);
              setPage(1);
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter" && search.trim()) void lookupCode(search.trim());
            }}
            placeholder="البحث عن منتج باسم المنتج أو الباركود…"
            aria-label="البحث عن منتج"
            className="h-full min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-ink-faint [&::-webkit-search-cancel-button]:hidden"
          />
          <ScanBarcode size={20} className="text-ink" aria-label="يدعم قارئ الباركود" />
        </label>
      </div>

      {bootstrap.error && (
        <p role="alert" className="rounded-control bg-danger-soft px-4 py-2.5 text-sm text-danger">
          {toFinoraError(bootstrap.error).message}
        </p>
      )}

      <OperatingBranchGate branchId={bootstrap.data ? bootstrap.data.branch_id : undefined} />

      {window.finoraDesktop?.offline && (
        <div className="flex flex-wrap items-center gap-3 rounded-control border border-violet/15 bg-violet-soft/60 px-4 py-2 text-xs text-ink-soft">
          <label className="flex items-center gap-2 font-semibold text-violet">
            <input
              type="checkbox"
              checked={reservedSale || !online}
              disabled={!online || checkout.isPending || reserving}
              onChange={(e) => setReservedSale(e.target.checked)}
            />
            البيع من حصة هذا الجهاز
          </label>
          <span className="min-w-0 flex-1">
            {reservedSale || !online
              ? "الفاتورة والدفع ينحفظن محلياً ثم يتزامنن تلقائياً."
              : "احجز كميات السلة أونلاين حتى تكون متاحة للبيع بدون نت."}
          </span>
          <button
            type="button"
            onClick={() => void reserveCart()}
            disabled={!online || !lines.length || reserving || checkout.isPending}
            className="rounded-control bg-white px-3 py-2 font-semibold text-violet shadow-control disabled:opacity-40"
          >
            {reserving ? "جارٍ الحجز…" : "حجز كميات السلة للجهاز"}
          </button>
          {(reservedSale || !online) && lines.length > 0 && (
            <p className="w-full">
              {lines
                .map(
                  (l) =>
                    `${l.name}${l.color ? ` · ${l.color}` : ""}: متاح ${quotaAvailable(l.productId, l.color)}`,
                )
                .join(" — ")}
            </p>
          )}
        </div>
      )}

      <div className="grid min-h-0 flex-1 grid-cols-[minmax(290px,0.95fr)_minmax(0,1.75fr)_minmax(300px,1fr)] gap-3">
        <div className={panel}>
          <CustomerPanel bootstrap={bootstrap.data} adding={addingCustomer} onAdding={setAddingCustomer} />
        </div>
        <div className={panel}>
          <CartPanel
            bootstrap={bootstrap.data}
            serverUrl={serverUrl}
            busy={checkout.isPending || reserving || !bootstrap.data}
            successToken={checkout.data ? checkout.submittedAt : 0}
            onCheckout={runCheckout}
            onEditInvoice={() => setEditOpen(true)}
          />
        </div>
        <div className={panel}>
          <ProductsPanel
            page={products.data}
            loading={products.isLoading}
            error={products.error ? toFinoraError(products.error).message : null}
            category={category}
            serverUrl={serverUrl}
            onCategory={(next) => {
              setCategory(next);
              setPage(1);
            }}
            onPage={setPage}
            onAdd={addProduct}
          />
        </div>
      </div>

      <PickerDialog
        open={colorFor !== null}
        title={colorFor ? `اختر ${colorFor.option_axes?.length ? "الخيار" : "اللون"} — ${colorFor.name}` : ""}
        description="اختر الحجم أو المقاس أو اللون المطلوب. السعر والمخزون يخصّان هذا الخيار، ويظهر الاختيار في الطلب والفاتورة."
        options={(colorFor?.colors ?? [])
          .filter((color) => color.active !== false)
          .map((color) => ({
            value: color.name,
            label: color.name,
            hint: `متوفر ${color.qty ?? 0} · ${formatIqd(color.sale_price ?? colorFor?.price ?? 0)}`,
          }))}
        confirmLabel="إضافة للسلة"
        onConfirm={(color) => {
          if (colorFor) chooseSaleMode(colorFor, color);
          setColorFor(null);
        }}
        onClose={() => setColorFor(null)}
      />
      <PickerDialog
        open={saleFor !== null}
        title={saleFor ? `بيع أو استبدال — ${saleFor.product.name}` : ""}
        description="اختر نوع العملية لهذا الصنف؛ طريقة الدفع تختارها من نقد أو آجل أو بنك."
        options={
          saleFor
            ? [
                {
                  value: "normal",
                  label: "بيع",
                  hint: formatIqd(
                    saleFor.product.colors.find((color) => color.name === saleFor.color)?.sale_price ||
                      saleFor.product.price,
                  ),
                },
                {
                  value: "exchange",
                  label: "استبدال",
                  hint: formatIqd(saleFor.product.exchange_sale_price ?? 0),
                },
              ]
            : []
        }
        confirmLabel="إضافة للسلة"
        onConfirm={(mode) => {
          if (saleFor && (mode === "normal" || mode === "exchange")) {
            const line = add(saleFor.product, saleFor.color, mode);
            const used = useCart
              .getState()
              .lines.filter((item) => item.productId === line.productId && item.color === line.color)
              .reduce((sum, item) => sum + item.qty, 0);
            if (used > line.available)
              toast.info(`${line.name}: الكمية أكبر من المتوفر — سيُقفل الطلب بانتظار المخزون`);
          }
          setSaleFor(null);
        }}
        onClose={() => setSaleFor(null)}
      />
      <EditInvoiceDialog open={editOpen} onClose={() => setEditOpen(false)} />
      <ConfirmDialog
        open={confirmTotal !== null}
        title="تأكيد تنفيذ البيع"
        message={confirmTotal ? `إجمالي هذه الفاتورة ${formatIqd(confirmTotal.total)}. هل تريد التنفيذ؟` : ""}
        confirmLabel="تنفيذ"
        onConfirm={() => {
          if (confirmTotal) execute(confirmTotal.print);
          setConfirmTotal(null);
        }}
        onClose={() => setConfirmTotal(null)}
      />
    </div>
  );
}
