import { useMutation, useQueryClient } from "@tanstack/react-query";
import { finora, toFinoraError } from "@/api/finora";
import type { PaymentAccount, PosBootstrap } from "@/api/finora/pos";
import { canMutate } from "@/stores/connection";
import { toast } from "@/stores/toasts";
import { formatIqd } from "@/utils/money";
import { cartTotals, useCart, type SaleType } from "./cart";
import { usePosPreferences } from "./posPreferences";
import { useOffline } from "@/stores/offline";

export class CheckoutBlocked extends Error {}

/** Default cash drawer of the branch (or any cash account), or the chosen bank account. */
export function pickAccount(
  accounts: PaymentAccount[],
  saleType: SaleType,
  branchId: number | null,
  bankAccountId: number | null,
): PaymentAccount | null {
  if (saleType === "bank") return accounts.find((a) => a.id === bankAccountId) ?? null;
  const cash = accounts.filter((a) => a.type.toLowerCase() === "cash");
  const ranked = [...cash].sort(
    (a, b) =>
      Number(b.branch_id === branchId) - Number(a.branch_id === branchId) ||
      Number(b.is_default) - Number(a.is_default),
  );
  return ranked[0] ?? null;
}

interface CheckoutArgs {
  reserved?: boolean;
  print: boolean;
  bootstrap: PosBootstrap;
  bankAccountId: number | null;
}

export function useCheckout() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ print, bootstrap, bankAccountId, reserved }: CheckoutArgs) => {
      const local = !!reserved || !canMutate();
      const cart = useCart.getState();
      if (!cart.customer) throw new CheckoutBlocked("اختر زبوناً أو أضف زبوناً جديداً.");
      if (cart.lines.length === 0) throw new CheckoutBlocked("السلة فارغة.");
      if (local && cart.lines.some((line) => line.saleMode === "exchange"))
        throw new CheckoutBlocked(
          "الاستبدال يحتاج اتصالاً بالإنترنت؛ ألغِ البيع من حصة الجهاز واتصل لتنفيذ الفاتورة.",
        );
      const { discount } = cartTotals(cart.lines, cart.discountMode, cart.discountValue);
      const editing = cart.editingOrderId;
      if (local && editing)
        throw new CheckoutBlocked("تعديل الفواتير يحتاج اتصالاً؛ البيع المحلي يدعم فاتورة جديدة.");
      if (local && cart.saleType !== "credit" && !bootstrap.can_pay)
        throw new CheckoutBlocked("ليست لديك صلاحية التحصيل؛ اختر البيع الآجل.");
      const payNow = !editing && cart.saleType !== "credit" && bootstrap.can_pay;

      let account: PaymentAccount | null = null;
      if (payNow) {
        account = pickAccount(
          await finora.pos.paymentAccounts(),
          cart.saleType,
          bootstrap.branch_id,
          bankAccountId,
        );
        if (!account) {
          throw new CheckoutBlocked(
            cart.saleType === "bank"
              ? "اختر الحساب البنكي."
              : "لا يوجد صندوق نقدي مفعّل لهذا الفرع في FINORA.",
          );
        }
      }

      if (local) {
        if ((bootstrap.storage_sources?.length ?? 0) > 0)
          throw new CheckoutBlocked("اتصل بالإنترنت لتنفيذ البيع من مخازن الفرع.");
        const bridge = window.finoraDesktop?.offline;
        if (!bridge || !useOffline.getState().status.available)
          throw new CheckoutBlocked("يلزم تسجيل دخول حديث وحصة مخزون محفوظة لهذا الجهاز.");
        const saved = await bridge.savePosSale(cart.takeSubmissionToken(), {
          kind: "pos",
          customerId: cart.customer.id,
          customerName: cart.customer.name,
          items: cart.lines.map((l) => ({
            product_id: l.productId,
            qty: l.qty,
            price: l.unitPrice,
            ...(l.color ? { variant_color: l.color } : {}),
          })),
          discount,
          total: cartTotals(cart.lines, cart.discountMode, cart.discountValue).total,
          payment: cart.saleType,
          accountId: account?.id ?? null,
        });
        useOffline.getState().set(await bridge.status());
        if (print && bootstrap.can_print)
          void bridge.printPosSale(saved.id).catch((e: unknown) => toast.error(toFinoraError(e).message));
        void bridge
          .synchronize()
          .then((status) => useOffline.getState().set(status))
          .catch((e: unknown) => toast.error(toFinoraError(e).message));
        return {
          order: { invoice_id: 0, total: saved.total },
          localNumber: saved.localInvoiceNo,
          editing: null,
          paymentError: null,
          account,
          stockLocked: false,
        };
      }

      const order = await finora.pos.createOrder({
        customerId: cart.customer.id,
        lines: cart.lines.map((line) => ({
          product_id: line.productId,
          qty: line.qty,
          price: line.unitPrice,
          color: line.color || undefined,
          ...(line.saleMode === "exchange" ? { sale_mode: line.saleMode } : {}),
          ...(line.storageSource
            ? { storage_location_id: line.storageSource.id, storage_automatic: line.storageSource.automatic }
            : {}),
        })),
        discountAmount: discount,
        branchId: bootstrap.branch_id,
        orderId: editing,
        submissionToken: cart.takeSubmissionToken(),
      });

      let paymentError: string | null = null;
      if (payNow && account && !order.stock_locked) {
        try {
          await finora.pos.pay(order.invoice_id, account.id, order.total);
        } catch (error) {
          paymentError = toFinoraError(error).message;
        }
      }
      if (print && bootstrap.can_print) {
        finora.orders
          .print([order.invoice_id])
          .catch((error: unknown) => toast.error(toFinoraError(error).message));
      }
      return {
        order,
        editing,
        paymentError,
        account,
        stockLocked: Boolean(order.stock_locked),
        localNumber: undefined,
      };
    },
    onSuccess: ({ order, editing, paymentError, account, stockLocked, localNumber }) => {
      const head = localNumber
        ? `تم اعتماد البيع المحلي #${localNumber.split("-").pop()}`
        : editing
          ? `تم حفظ تعديل الطلب #${order.invoice_id}`
          : `تم تنفيذ الطلب #${order.invoice_id}`;
      toast.success(
        `${head} — ${formatIqd(order.total)}${account && !paymentError && !stockLocked ? ` · ${account.name}` : ""}`,
      );
      if (stockLocked) toast.info("الطلب مقفل بانتظار المخزون؛ لم يُسجَّل الدفع.");
      if (paymentError) {
        toast.error(
          `أُنشئ الطلب #${order.invoice_id} لكن لم يُسجَّل الدفع: ${paymentError} — سجّله من نافذة الطلبات.`,
        );
      }
      useCart.getState().reset(usePosPreferences.getState().defaultSaleType);
      void queryClient.invalidateQueries({ queryKey: ["orders"] });
      void queryClient.invalidateQueries({ queryKey: ["products"] });
      void queryClient.invalidateQueries({ queryKey: ["pos", "products"] });
    },
    onError: (error) =>
      toast.error(error instanceof CheckoutBlocked ? error.message : toFinoraError(error).message),
  });
}
