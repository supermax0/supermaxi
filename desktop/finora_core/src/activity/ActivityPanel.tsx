import { useState } from "react";
import { SupportIssues } from "./SupportIssues";
import { ApprovalCard } from "../approvals/ApprovalCard";
import { MergeSuggestions } from "../approvals/MergeSuggestions";
import { useCan } from "../data/can";
import { useActivity, useApprovals } from "../data/hooks";
import type { ActivityCategory } from "../data/schemas";
import { EmptyState, ErrorState, Skeleton, Time, cx } from "../ui/primitives";

const CATS: { key: ActivityCategory | "all"; label: string }[] = [
  { key: "all", label: "الكل" },
  { key: "messages", label: "الرسائل" },
  { key: "ai", label: "AI" },
  { key: "finora", label: "FINORA" },
  { key: "approvals", label: "الموافقات" },
  { key: "errors", label: "الأخطاء" },
];

/** Actions and results only — never model reasoning (spec §29). */
export function ActivityPanel() {
  const canView = useCan("audit.view");
  return canView ? <Activity /> : <EmptyState title="لا تملك صلاحية عرض سجل النشاط" />;
}

function Activity() {
  const [cat, setCat] = useState<ActivityCategory | "all">("all");
  const q = useActivity(cat);
  const approvals = useApprovals();
  const pending = approvals.data ?? [];

  return (
    <div className="activity">
      <SupportIssues />
      <MergeSuggestions />
      {pending.length > 0 && (
        <section className="act-approvals" aria-label="طلبات بانتظار الموافقة">
          {pending.map((a) => (
            <ApprovalCard key={a.id} approval={a} />
          ))}
        </section>
      )}

      <div className="chips" role="tablist" aria-label="تصفية النشاط">
        {CATS.map((c) => (
          <button
            key={c.key}
            type="button"
            role="tab"
            aria-selected={cat === c.key}
            className={cx("chip", cat === c.key && "is-active")}
            onClick={() => setCat(c.key)}
          >
            {c.label}
          </button>
        ))}
      </div>

      {q.isPending ? (
        <div className="act-skel" aria-busy="true">
          {Array.from({ length: 5 }, (_, i) => (
            <Skeleton key={i} w="100%" h={46} r={12} />
          ))}
        </div>
      ) : q.isError ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      ) : q.data.length === 0 ? (
        <EmptyState title="لا يوجد نشاط" />
      ) : (
        <ol className="timeline">
          {q.data.map((e) => (
            <li key={e.id} className={cx("tl-item", `cat-${e.category}`, `res-${e.result}`)}>
              <Time iso={e.at} className="tl-time" />
              <span className="tl-dot" aria-hidden="true" />
              <div className="tl-body">
                <strong>{e.title}</strong>
                {(e.detail || e.customerName) && (
                  <span className="tl-detail">{[e.customerName, e.detail].filter(Boolean).join(" · ")}</span>
                )}
                <code className="tl-corr" dir="ltr" title="Correlation ID">
                  {e.correlationId}
                </code>
              </div>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
