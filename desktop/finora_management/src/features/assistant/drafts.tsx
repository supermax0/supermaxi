import { useState } from "react";
import { FilePenLine } from "lucide-react";
import { finora } from "@/api/finora";
import { useSession } from "@/stores/session";
import { useCart } from "@/features/pos/cart";
import { useComposer } from "@/features/purchases/composer";
import { openWorkspaceTarget, actionAllowed, runWorkspaceAction } from "@/features/workspace/navigation";
import { allowedWindow, type ActionId } from "@/features/workspace/state";
import { useAssistant, type AssistantProposal } from "./state";
import { currentAssistantScope, rowsFromData, sourceWindow } from "./engine";
import { queueAssistantDraft } from "./draftQueue";
import { draftSchemas, validateDraft, type DraftKind } from "./draftSchema";

const LABELS: Record<string, string> = {
  name: "الاسم",
  sku: "رمز المنتج",
  barcode: "الباركود",
  description: "الوصف",
  buyPrice: "سعر الشراء",
  salePrice: "سعر البيع",
  phone: "الهاتف",
  city: "المدينة",
  address: "العنوان",
  note: "ملاحظة",
  title: "العنوان",
  amount: "المبلغ",
  items: "المنتجات والكميات",
};
function dialogOpen() {
  return (
    Array.from(
      document.querySelectorAll(
        '[role="dialog"]:not([data-window]), [role="complementary"]:not(.finora-assistant-panel)',
      ),
    ).length > 0
  );
}
function cartEmpty() {
  const c = useCart.getState();
  return !c.lines.length && !c.customer && !c.editingOrderId && !c.discountValue && !c.submissionToken;
}
function purchaseEmpty() {
  const c = useComposer.getState();
  return (
    !c.open &&
    !c.lines.length &&
    !c.supplier &&
    !c.notes &&
    !c.supplierInvoiceNo &&
    !c.discount &&
    !c.shippingExtra &&
    !c.downPayment &&
    !c.bankAccountId
  );
}
export async function openPreparedDraft(proposal: AssistantProposal) {
  const kind = proposal.action as DraftKind,
    fields = validateDraft(kind, proposal.fields ?? {}),
    scope = currentAssistantScope();
  const check = () => {
    if (scope !== currentAssistantScope()) throw Error("تغيّر الحساب أو الفرع؛ أعد تجهيز المقترح.");
    if (dialogOpen()) throw Error("أكمل النموذج المفتوح أو أغلقه أولاً حتى تبقى تعديلاتك محفوظة.");
  };
  check();
  if (kind === "sale" || kind === "purchase") {
    const window = kind === "sale" ? "pos" : "purchases";
    if (!allowedWindow(window, useSession.getState().session)) throw Error("لا تملك صلاحية هذا القسم");
    const empty = kind === "sale" ? cartEmpty : purchaseEmpty;
    if (!empty()) throw Error("توجد مسودة حالية. أكملها أو أفرغها بنفسك قبل فتح مقترح جديد.");
    const items = draftSchemas[kind].parse(fields).items ?? [];
    const ids = new Set<number>();
    const lookups = items.map((item) => {
      if (ids.has(item.product_id)) throw Error("كرر المنتج مرة واحدة فقط واجمع كميته.");
      ids.add(item.product_id);
      const rows = useAssistant
        .getState()
        .messages.flatMap((m) =>
          (m.sources ?? [])
            .filter((s) => sourceWindow(s.name) === "products")
            .flatMap((s) => rowsFromData(s.data)),
        );
      const verified = rows.find((r) => Number(r.id ?? r.product_id) === item.product_id);
      if (!verified || typeof verified.name !== "string")
        throw Error("ابحث عن المنتج من المساعد أولاً حتى نتحقق من هويته، أو اختره يدوياً داخل النموذج.");
      return { item, name: verified.name };
    });
    // Resolve every row from the original, permission-scoped API before touching a draft.
    if (kind === "sale") {
      const bootstrap = await finora.pos.bootstrap();
      if (!bootstrap.branch_id) throw Error("اختر فرع تشغيل محدداً داخل نقطة البيع أولاً.");
      const products = await Promise.all(
        lookups.map(async ({ item, name }) => {
          const page = await finora.pos.products({ page: 1, pageSize: 50, search: name });
          const product = page.rows.find((p) => p.id === item.product_id);
          if (!product) throw Error("أحد المنتجات غير متاح للبيع ضمن الفرع الحالي.");
          const color = item.color ? product.colors.find((c) => c.name === item.color) : null;
          if (product.has_colors && !color) throw Error("حدد لون المنتج بدقة قبل تجهيز المسودة.");
          if ((color?.qty ?? product.quantity) < item.quantity)
            throw Error("الكمية المقترحة تتجاوز الرصيد الحالي؛ راجع المخزون.");
          return { product, item };
        }),
      );
      check();
      if (!cartEmpty()) throw Error("تغيّرت السلة أثناء قراءة المنتجات؛ لم يتم استبدالها.");
      for (const { product, item } of products) {
        const line = useCart.getState().add(product, item.color);
        useCart.getState().setQty(line.key, item.quantity);
      }
      openWorkspaceTarget({ window: "pos" });
    } else {
      const products = await Promise.all(
        lookups.map(async ({ item, name }) => {
          const product = (await finora.purchases.searchProducts(name)).find((p) => p.id === item.product_id);
          if (!product) throw Error("أحد المنتجات غير متاح ضمن نطاق المشتريات الحالي.");
          if (product.has_colors && !product.colors.some((c) => c.name === item.color && c.active !== false))
            throw Error("حدد لوناً فعالاً للمنتج قبل تجهيز المسودة.");
          return { product, item };
        }),
      );
      check();
      if (!purchaseEmpty()) throw Error("تغيّرت مسودة المشتريات؛ لم يتم استبدالها.");
      for (const { product, item } of products) {
        const line = useComposer.getState().addProduct(product);
        useComposer
          .getState()
          .updateLine(line.key, { qty: item.quantity, ...(item.color ? { color: item.color } : {}) });
      }
      useComposer.getState().patch({ notes: typeof fields.note === "string" ? fields.note : "" });
      openWorkspaceTarget({ window: "purchases" });
      useComposer.getState().setOpen(true);
    }
  } else {
    if (!actionAllowed(kind as ActionId)) throw Error("لا تملك صلاحية فتح هذا النموذج");
    queueAssistantDraft(kind, fields);
    runWorkspaceAction(kind as ActionId);
  }
  useAssistant.getState().close();
}
export function PreparedDraftCard({ proposal }: { proposal: AssistantProposal }) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [opened, setOpened] = useState(false);
  let fields: Record<string, unknown> = {};
  let invalid = "";
  try {
    fields = validateDraft(proposal.action ?? "", proposal.fields ?? {});
  } catch (e) {
    invalid = e instanceof Error ? e.message : "مسودة غير صالحة";
  }
  return (
    <section className="assistant-draft">
      <strong>
        <FilePenLine size={16} />
        {proposal.title}
      </strong>
      <p className="assistant-muted">
        مقترح غير محفوظ. راجع الحقول، ثم أكمل الأطراف والحسابات والخيارات داخل النموذج الأصلي. الأسعار الحالية
        للفاتورة تُقرأ من فينورا.
      </p>
      <dl>
        {Object.entries(fields).map(([key, value]) => (
          <div key={key}>
            <dt>{LABELS[key] ?? key}</dt>
            <dd dir="auto">{typeof value === "object" ? JSON.stringify(value) : String(value)}</dd>
          </div>
        ))}
      </dl>
      {(invalid || error) && (
        <p role="alert" className="assistant-error">
          {invalid || error}
        </p>
      )}
      <button
        className="workspace-button"
        disabled={busy || !!invalid || opened}
        onClick={() => {
          setBusy(true);
          setError("");
          void openPreparedDraft(proposal)
            .then(
              () => setOpened(true),
              (e: unknown) => setError(e instanceof Error ? e.message : "تعذر تجهيز النموذج"),
            )
            .finally(() => setBusy(false));
        }}
      >
        {busy ? "أتحقق…" : opened ? "تم فتح المقترح للمراجعة" : "مراجعة في النموذج الأصلي"}
      </button>
    </section>
  );
}
