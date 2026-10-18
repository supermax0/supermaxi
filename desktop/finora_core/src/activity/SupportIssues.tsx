import { CircleCheck, MessageSquare, TriangleAlert } from "lucide-react";
import { useCan } from "../data/can";
import { useResolveIssue, useSupportIssues } from "../data/accountHooks";
import { useUi } from "../state/ui";
import { ErrorState, FinoraButton, Time, errorText } from "../ui/primitives";
import { toast } from "../ui/toast";

export function SupportIssues() {
  const allowed = useCan("settings.manage");
  const issues = useSupportIssues();
  const resolve = useResolveIssue();
  if (!allowed) return null;
  if (issues.isError) return <ErrorState error={issues.error} onRetry={() => void issues.refetch()} />;
  if (!issues.data?.length) return null;
  return (
    <section className="support-inbox" aria-label="تنبيهات حسابات العملاء">
      <h3>
        <TriangleAlert size={17} /> تحتاج متابعتك
      </h3>
      {issues.data.map((issue) => (
        <article className="support-card" key={issue.id}>
          <strong>{issue.title}</strong>
          <span>
            {issue.customerName} · {issue.tenantSlug || "حساب غير مرتبط"}
          </span>
          <p dir="auto">{issue.details}</p>
          <small>
            {issue.verified ? "رصدها النظام أثناء التنفيذ" : "بلاغ أو طلب يحتاج تحققاً"} ·{" "}
            <Time iso={issue.at} />
          </small>
          <footer>
            <FinoraButton
              size="sm"
              variant="soft"
              onClick={() => {
                useUi.setState({
                  view: "workspace",
                  selectedConversationId: issue.conversationId,
                  overlay: "none",
                });
              }}
            >
              <MessageSquare size={14} /> محادثة العميل
            </FinoraButton>
            <FinoraButton
              size="sm"
              variant="ghost"
              loading={resolve.isPending && resolve.variables === issue.id}
              onClick={() => resolve.mutate(issue.id, { onError: (error) => toast.error(errorText(error)) })}
            >
              <CircleCheck size={14} /> تمت المعالجة
            </FinoraButton>
          </footer>
        </article>
      ))}
    </section>
  );
}
