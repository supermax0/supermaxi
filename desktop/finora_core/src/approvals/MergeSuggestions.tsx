import { Users } from "lucide-react";
import { useCan } from "../data/can";
import { useDecideMerge, useMergeSuggestions } from "../data/hooks";
import type { MergeSuggestion } from "../data/schemas";
import type { MergeDecision } from "../data/source";
import { toast } from "../ui/toast";
import { Badge, FinoraButton, errorText } from "../ui/primitives";

const KIND: Record<string, string> = {
  phone: "هاتف",
  email: "بريد",
  instagram_id: "Instagram",
  facebook_psid: "Messenger",
  telegram_user_id: "Telegram",
  finora_tenant: "حساب FINORA",
};

const DONE: Record<MergeDecision, string> = {
  merge: "تم دمج الملفين (يمكن التراجع من السجل)",
  separate: "سيبقى الملفان منفصلين",
  dismiss: "تم تجاهل الاقتراح",
};

function Side({ title, side }: { title: string; side: MergeSuggestion["customer"] }) {
  return (
    <div className="merge-side">
      <strong>
        {title}: {side.name ?? "—"}
      </strong>
      <ul>
        {side.identifiers.map((i, n) => (
          <li key={n}>
            {KIND[i.kind] ?? i.kind}: <code>{i.masked}</code>
            {i.verified && " ✓"}
          </li>
        ))}
        {side.hasTenant && <li>لديه حساب FINORA</li>}
      </ul>
    </div>
  );
}

/** Uncertain customer matches from the resolver. Never merged automatically; every decision is audited. */
export function MergeSuggestions() {
  const q = useMergeSuggestions();
  const decide = useDecideMerge();
  const canDecide = useCan("settings.manage");
  const items = q.data ?? [];
  if (items.length === 0) return null;

  const run = (id: string, decision: MergeDecision) =>
    decide.mutate(
      { id, decision },
      { onSuccess: () => toast.success(DONE[decision]), onError: (err) => toast.error(errorText(err)) },
    );
  const busyFor = (id: string, d: MergeDecision) =>
    decide.isPending && decide.variables?.id === id && decide.variables.decision === d;

  return (
    <section className="merge-list" aria-label="اقتراحات دمج ملفات العملاء">
      {items.map((m) => (
        <article key={m.id} className="merge-card" aria-label={`اقتراح دمج ${m.customer.name ?? ""}`}>
          <header className="ap-head">
            <span className="ap-icon">
              <Users size={16} />
            </span>
            <h3>قد يكونان نفس العميل</h3>
            <Badge tone="amber">ثقة {Math.round(m.confidence * 100)}%</Badge>
          </header>
          <p className="merge-why">
            المطابقة:{" "}
            {m.matched.map((x, n) => (
              <span key={n}>
                {KIND[x.kind ?? ""] ?? x.kind}
                {x.masked && (
                  <>
                    {" "}
                    <code dir="ltr">{x.masked}</code>
                  </>
                )}
                {n < m.matched.length - 1 && "، "}
              </span>
            ))}
          </p>
          <div className="merge-sides">
            <Side title="الملف" side={m.customer} />
            <Side title="المرشح" side={m.candidate} />
          </div>
          {canDecide ? (
            <footer className="ap-actions">
              <FinoraButton
                variant="ghost"
                size="sm"
                loading={busyFor(m.id, "dismiss")}
                disabled={decide.isPending}
                onClick={() => run(m.id, "dismiss")}
              >
                تجاهل
              </FinoraButton>
              <FinoraButton
                variant="soft"
                size="sm"
                loading={busyFor(m.id, "separate")}
                disabled={decide.isPending}
                onClick={() => run(m.id, "separate")}
              >
                إبقاء منفصلين
              </FinoraButton>
              <FinoraButton
                variant="primary"
                size="sm"
                loading={busyFor(m.id, "merge")}
                disabled={decide.isPending}
                onClick={() => run(m.id, "merge")}
              >
                دمج
              </FinoraButton>
            </footer>
          ) : (
            <p className="ap-readonly">بانتظار قرار مشرف مخوّل</p>
          )}
        </article>
      ))}
    </section>
  );
}
