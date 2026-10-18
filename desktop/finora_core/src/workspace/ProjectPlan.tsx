import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useCan } from "../data/can";
import { keys, useSource } from "../data/hooks";
import type { Approval, ProjectConsultation } from "../data/schemas";
import { Badge, FinoraButton, errorText } from "../ui/primitives";
import { toast } from "../ui/toast";
import { ProjectMapLauncher } from "./ProjectMap";

const STAGES: Record<ProjectConsultation["phase"], string> = {
  discovery: "حوار وفهم الفكرة",
  scope_review: "مراجعة النطاق مع العميل",
  internal_review: "بانتظار اعتمادك",
  quote_ready: "العرض معتمد · تسليمه غير مؤكد",
  quote_sent: "بانتظار قبول العميل",
  quote_rejected: "العرض يحتاج تعديل",
  awaiting_deposit: "بانتظار عربون 20٪",
  deposit_review: "تحقق من وصول الدفعة",
  execution_ready: "جاهز لفريق التطوير",
  cancelled: "متوقف",
};

export function ProjectPlan({
  project,
  conversationId,
}: {
  project: ProjectConsultation;
  conversationId?: string;
}) {
  const brief = project.brief;
  const terms = project.terms;
  const currency = terms?.currency === "IQD" ? "د.ع" : "دولار";
  return (
    <div className="project-plan">
      <Badge tone={project.phase === "execution_ready" ? "green" : "amber"}>{STAGES[project.phase]}</Badge>
      <h4>{brief.title}</h4>
      <p>{brief.goal}</p>
      {conversationId && (
        <ProjectMapLauncher key={`${conversationId}-${project.revision}`} conversationId={conversationId} />
      )}
      <p>
        {brief.audience} · {brief.platforms.join("، ")}
      </p>
      {terms && (
        <p>
          {terms.amount.toLocaleString("ar-IQ")} {currency} · {terms.days} يوم · نسخة أولية: {terms.mvpDays}{" "}
          يوم
        </p>
      )}
      {!["quote_ready", "quote_sent", "awaiting_deposit", "deposit_review", "execution_ready"].includes(
        project.phase,
      ) && <p className="ap-note">تقدير داخلي غير معتمد؛ لا يُرسل للعميل قبل موافقتك.</p>}
      {brief.estimate && <p className="ap-note">{brief.estimate.basis}</p>}
      <p className="ap-note">العميل يستلم ملخص أسماء الصفحات؛ تفاصيل الصفحة أو الخطة كاملة تُرسل بطلبه.</p>
      <details>
        <summary>مسارات العمل · {brief.workflows?.length ?? 0}</summary>
        {!brief.workflows?.length && (
          <p className="ap-note">مسارات العمل تُبنى مع المراجعة القادمة للخطة؛ المسودة الحالية محفوظة.</p>
        )}
        {brief.workflows?.map((flow) => (
          <section className="project-page" key={flow.id}>
            <strong>{flow.name}</strong>
            <p>يبدأ عند: {flow.trigger}</p>
            <ol className="project-workflow">
              {flow.steps.map((step, index) => (
                <li key={step.id}>
                  <span className="project-step-number" aria-hidden="true">
                    {index + 1}
                  </span>
                  <div>
                    <strong>
                      {brief.pages.find((page) => page.id === step.pageId)?.name || step.pageId}
                    </strong>
                    <span className="project-step-role">{step.role}</span>
                    <p>{step.action}</p>
                    <p>النتيجة: {step.result}</p>
                    {step.next.length ? (
                      <ul>
                        {step.next.map((edge, branch) => (
                          <li key={`${edge.stepId}-${branch}`}>
                            {edge.condition} ← الخطوة{" "}
                            {flow.steps.findIndex((row) => row.id === edge.stepId) + 1}
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="ap-note">نهاية المسار</p>
                    )}
                  </div>
                </li>
              ))}
            </ol>
            <p>قبول المسار: {flow.acceptance.join("؛ ")}</p>
          </section>
        ))}
      </details>
      <details>
        <summary>الصفحات وترابطها · {brief.pages.length}</summary>
        {brief.pages.map((page) => (
          <section className="project-page" key={page.id}>
            <strong>
              {page.name} · {page.phase === "mvp" ? "نسخة أولية" : "مرحلة لاحقة"}
            </strong>
            <p>{page.purpose}</p>
            <p>الميزات: {page.features.join("، ")}</p>
            <p>
              ترتبط بـ:{" "}
              {page.links.map((id) => brief.pages.find((row) => row.id === id)?.name || id).join("، ") ||
                "بدون رابط مباشر"}
            </p>
            <p>الصلاحيات: {page.roles.join("، ")}</p>
            <p>قبول التسليم: {page.acceptance.join("؛ ")}</p>
          </section>
        ))}
      </details>
      <details>
        <summary>البيانات والصلاحيات والربط</summary>
        {brief.entities.map((row) => (
          <p key={row.name}>
            <strong>{row.name}</strong>: {row.fields.join("، ")} · يرتبط بـ {row.relatedTo.join("، ") || "—"}
          </p>
        ))}
        {brief.roles.map((row) => (
          <p key={row.name}>
            <strong>{row.name}</strong>: {row.permissions.join("، ")}
          </p>
        ))}
        {brief.integrations.map((row) => (
          <p key={row.name}>
            {row.name}: {row.purpose}
            {row.requiresClientAccess && " · يحتاج صلاحيات من العميل"}
          </p>
        ))}
      </details>
      <details>
        <summary>المراحل والافتراضات والأفكار المقترحة</summary>
        {brief.milestones.map((row) => (
          <p key={row.name}>
            <strong>{row.name}</strong>: {row.deliverables.join("، ")}
          </p>
        ))}
        {brief.suggestions.map((row) => (
          <p key={row.title}>
            اقتراح: {row.title} — {row.benefit}
          </p>
        ))}
        <p>الافتراضات: {brief.assumptions.join("؛ ") || "غير محددة"}</p>
        <p>خارج النطاق: {brief.exclusions.join("؛ ") || "غير محدد"}</p>
        <p>المخاطر: {brief.risks.join("؛ ") || "غير محددة"}</p>
      </details>
      {project.paymentClaim && (
        <p className="ap-note">إشعار العميل بالدفع، غير كافٍ لإثبات الاستلام: {project.paymentClaim.text}</p>
      )}
      {project.paymentReference && <p>مرجع مراجعة الدفعة: {project.paymentReference}</p>}
    </div>
  );
}

export function ProjectReview({
  approval,
  onDirty,
}: {
  approval: Approval;
  onDirty: (dirty: boolean) => void;
}) {
  const src = useSource();
  const qc = useQueryClient();
  const canManage = useCan("settings.manage");
  const project = approval.preview?.project;
  const [terms, setTerms] = useState(project?.terms);
  const [reference, setReference] = useState(project?.paymentReference || "");
  const [verified, setVerified] = useState(Boolean(project?.paymentReference));
  const payment = approval.preview?.projectAction === "confirm_project_deposit";
  const dirty = payment
    ? !project?.paymentReference || reference !== project.paymentReference
    : JSON.stringify(terms) !== JSON.stringify(project?.terms);
  const review = useMutation({
    mutationFn: async () => {
      if (!terms) throw new Error("العرض المالي لم يجهّز بعد");
      if (!src.reviseProjectApproval || !approval.planHash) throw new Error("المراجعة غير متاحة بهذا المصدر");
      return src.reviseProjectApproval(
        approval.id,
        approval.planHash,
        payment ? { paymentReference: reference, paymentVerified: verified } : { terms },
      );
    },
    onSuccess: () => {
      toast.success("حُفظت المراجعة؛ راجع الخطة المحدثة ثم وافق");
      void qc.invalidateQueries({ queryKey: keys.approvals });
      if (approval.conversationId)
        void qc.invalidateQueries({ queryKey: keys.customer(approval.conversationId) });
    },
    onError: (error) => toast.error(errorText(error)),
  });
  useEffect(() => {
    onDirty(dirty || review.isPending);
  }, [dirty, review.isPending, onDirty]);
  if (!project || !terms || !canManage || !src.reviseProjectApproval) return null;
  return (
    <form
      className="project-review"
      onSubmit={(event) => {
        event.preventDefault();
        review.mutate();
      }}
    >
      {payment ? (
        <>
          <p>
            تحقق من استلام مبلغ العربون بالكامل: {approval.preview?.depositAmount} {terms.currency} قبل
            الموافقة.
          </p>
          <label>
            مرجع وصول الدفعة
            <input
              required
              minLength={3}
              maxLength={200}
              value={reference}
              onChange={(event) => setReference(event.target.value)}
              placeholder="رقم الحوالة أو مرجع التحقق"
            />
          </label>
          <label className="project-check">
            <input
              type="checkbox"
              required
              checked={verified}
              onChange={(event) => setVerified(event.target.checked)}
            />
            تحققت من وصول العربون؛ كلام العميل وحده ليس إثباتاً
          </label>
        </>
      ) : (
        <div className="project-review-grid">
          <label>
            المبلغ الإجمالي
            <input
              type="number"
              required
              min={5}
              max={10000000000}
              step={1}
              value={terms.amount}
              onChange={(event) => setTerms({ ...terms, amount: event.target.valueAsNumber })}
            />
          </label>
          <label>
            العملة
            <select
              value={terms.currency}
              onChange={(event) =>
                setTerms({ ...terms, currency: event.target.value === "USD" ? "USD" : "IQD" })
              }
            >
              <option value="IQD">دينار عراقي</option>
              <option value="USD">دولار أمريكي</option>
            </select>
          </label>
          <label>
            المدة التقديرية بالأيام
            <input
              type="number"
              required
              min={1}
              max={365}
              value={terms.days}
              onChange={(event) => setTerms({ ...terms, days: event.target.valueAsNumber })}
            />
          </label>
          <label>
            موعد النسخة الأولية بالأيام
            <input
              type="number"
              required
              min={1}
              max={terms.days}
              value={terms.mvpDays}
              onChange={(event) => setTerms({ ...terms, mvpDays: event.target.valueAsNumber })}
            />
          </label>
        </div>
      )}
      <FinoraButton
        type="submit"
        size="sm"
        variant="ghost"
        disabled={!dirty || review.isPending}
        loading={review.isPending}
      >
        حفظ المراجعة
      </FinoraButton>
    </form>
  );
}

export function CustomerProject({
  project,
  conversationId,
}: {
  project: ProjectConsultation;
  conversationId: string;
}) {
  const src = useSource();
  const allowed = useCan("settings.manage");
  const canSend = useCan("messages.send");
  const qc = useQueryClient();
  const resend = useMutation({
    mutationFn: async () => {
      if (!src.resendProjectQuote) throw new Error("إعادة التسليم غير متاحة بهذا المصدر");
      return src.resendProjectQuote(conversationId);
    },
    onSuccess: (result) => {
      if (result.phase === "quote_sent") toast.success("تم تسليم العرض");
      else toast.error("التسليم بعده غير مؤكد؛ راجع سجل النشاط");
      void qc.invalidateQueries({ queryKey: keys.customer(conversationId) });
    },
    onError: (error) => toast.error(errorText(error)),
  });
  const exportPlan = useMutation({
    mutationFn: async () => {
      if (!src.getProjectManifest) throw new Error("نسخ الخطة غير متاح بهذا المصدر");
      const data = await src.getProjectManifest(conversationId);
      await navigator.clipboard.writeText(JSON.stringify(data, null, 2));
    },
    onSuccess: () => toast.success("نُسخت مواصفات المشروع"),
    onError: (error) => toast.error(errorText(error)),
  });
  return (
    <section className="cp-card" aria-label="استشارة برمجية">
      <header className="cp-card-head">
        <h3>استشارة برمجية · نسخة {project.revision}</h3>
      </header>
      <ProjectPlan project={project} conversationId={conversationId} />
      {allowed && canSend && project.phase === "quote_ready" && src.resendProjectQuote && (
        <FinoraButton size="sm" variant="ghost" loading={resend.isPending} onClick={() => resend.mutate()}>
          إعادة إرسال العرض المعتمد
        </FinoraButton>
      )}
      <p className="ap-note">
        مواصفات منظمة للتسليم لفريق التطوير. الربط البرمجي التلقائي مع Claude أو Codex بعده مو مفعّل.
      </p>
      {allowed && src.getProjectManifest && (
        <FinoraButton
          size="sm"
          variant="ghost"
          loading={exportPlan.isPending}
          onClick={() => exportPlan.mutate()}
        >
          نسخ مواصفات التنفيذ
        </FinoraButton>
      )}
    </section>
  );
}
