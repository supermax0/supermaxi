import { ShieldAlert } from "lucide-react";
import { useState } from "react";
import { ProjectPlan, ProjectReview } from "../workspace/ProjectPlan";
import { useCan } from "../data/can";
import { useDecideApproval } from "../data/hooks";
import { showCredentials } from "./CredentialsDialog";
import type { Approval, ApprovalPreview } from "../data/schemas";
import { toast } from "../ui/toast";
import { Badge, FinoraButton, errorText } from "../ui/primitives";

const RISK = {
  low: { label: "منخفض", tone: "green" },
  medium: { label: "متوسط", tone: "amber" },
  high: { label: "مرتفع", tone: "red" },
} as const;

const SPECIALTY: Record<string, string> = {
  dentistry: "أسنان",
  dermatology: "جلدية",
  gynecology: "نسائية وتوليد",
  pediatrics: "أطفال",
  cardiology: "قلبية",
  internal_medicine: "باطنية",
  general: "عام",
};

function useDecision(approval: Approval) {
  const decide = useDecideApproval();
  const pendingDecision = decide.isPending ? decide.variables?.decision : undefined;
  const run = (decision: "approved" | "rejected") =>
    decide.mutate(
      // The approval authorizes exactly the plan on screen: its hash travels with the decision.
      { id: approval.id, decision, planHash: approval.planHash ?? null },
      {
        onSuccess: (result) => {
          toast.success(decision === "approved" ? "تمت الموافقة وتم التنفيذ" : "تم رفض الطلب");
          if (result.credentials) showCredentials(result.credentials);
        },
        onError: (err) => toast.error(errorText(err)),
      },
    );
  return { busy: decide.isPending, pendingDecision, run };
}

function Decision({
  approval,
  reviewOnly,
  blocked = false,
}: {
  approval: Approval;
  reviewOnly?: () => void;
  blocked?: boolean;
}) {
  const { busy, pendingDecision, run } = useDecision(approval);
  const allowed = useCan("approvals.decide");
  if (!allowed) return <p className="ap-readonly">بانتظار قرار مشرف مخوّل</p>;
  return (
    <footer className="ap-actions">
      <FinoraButton
        variant="ghost"
        size="sm"
        loading={pendingDecision === "rejected"}
        disabled={busy}
        onClick={() => run("rejected")}
      >
        رفض
      </FinoraButton>
      {reviewOnly ? (
        <FinoraButton variant="primary" size="sm" disabled={busy} onClick={reviewOnly}>
          مراجعة الخطة
        </FinoraButton>
      ) : (
        <FinoraButton
          variant="primary"
          size="sm"
          loading={pendingDecision === "approved"}
          disabled={busy || blocked}
          onClick={() => run("approved")}
        >
          موافقة
        </FinoraButton>
      )}
    </footer>
  );
}

/** One-line approval shown on the orb stage. A plan with details is approved only after reviewing it in full. */
export function ApprovalBar({ approval, onDetails }: { approval: Approval; onDetails: () => void }) {
  return (
    <article className="approval-bar" aria-label={`طلب موافقة: ${approval.action}`}>
      <span className="ap-icon">
        <ShieldAlert size={16} />
      </span>
      <button type="button" className="ab-text" onClick={onDetails}>
        <strong>طلب موافقة</strong>
        <span>
          {approval.customerName} · {approval.action}
          {approval.agentLimit && <em> (حد الوكيل {approval.agentLimit})</em>}
        </span>
      </button>
      <Decision approval={approval} reviewOnly={approval.preview ? onDetails : undefined} />
    </article>
  );
}

const PERMISSION_LABELS: Record<string, string> = {
  can_see_orders: "عرض الطلبات",
  can_see_orders_placed: "طلبات تم الطلب",
  can_see_orders_delivered: "طلبات التسليم",
  can_see_orders_returned: "الطلبات الراجعة",
  can_see_orders_shipped: "طلبات الشحن",
  can_edit_price: "تعديل السعر",
  can_see_reports: "التقارير",
  can_manage_inventory: "إدارة المخزون",
  can_see_expenses: "المصاريف",
  can_manage_suppliers: "الموردون",
  can_manage_customers: "الزبائن",
  can_see_accounts: "الحسابات",
  can_see_financial: "البيانات المالية",
};
function PlanPreview({ preview }: { preview: ApprovalPreview }) {
  const size = preview.size;
  const sizeText = size
    ? [
        size.doctors != null && `${size.doctors} أطباء`,
        size.employees != null && `${size.employees} موظفين`,
        size.branches != null && `${size.branches} فروع`,
      ]
        .filter(Boolean)
        .join(" · ")
    : "";
  return (
    <dl className="ap-grid ap-plan" aria-label="الخطة المقترحة">
      {preview.businessTypeChange && (
        <>
          <dt>نوع نشاط الشركة</dt>
          <dd>
            {preview.businessTypeChange.before} ← {preview.businessTypeChange.after}
          </dd>
        </>
      )}
      {!!preview.unavailableFeatures?.length && (
        <>
          <dt>تحتاج تدخلك</dt>
          <dd>
            هذه الأقسام خارج الباقة وتبقى غير مفعلة:{" "}
            {preview.unavailableFeatures.map((row) => row.label).join("، ")}
          </dd>
        </>
      )}
      {preview.accountScope && (
        <>
          <dt>الحساب المستهدف</dt>
          <dd>
            <bdi>{preview.accountScope.tenantSlug}</bdi>
            <br />
            {preview.accountScope.label}
          </dd>
        </>
      )}
      {!!preview.changes?.length && (
        <>
          <dt>تغييرات الصفحات</dt>
          <dd className="ap-list">
            {preview.changes.map((change) => (
              <span key={change.key}>
                {change.label}: {change.before ? "ظاهرة" : "مخفية"} ← {change.after ? "إظهار" : "إخفاء"}
              </span>
            ))}
          </dd>
        </>
      )}
      {preview.employeeId != null && (
        <>
          <dt>الموظف المستهدف</dt>
          <dd>{preview.employeeName || `رقم ${preview.employeeId}`} داخل هذا الحساب فقط</dd>
        </>
      )}
      {!!preview.permissionDiff?.length && (
        <>
          <dt>تغييرات صلاحيات الموظف</dt>
          <dd className="ap-list">
            {preview.permissionDiff.map((item) => (
              <span key={item.key}>
                {PERMISSION_LABELS[item.key] || item.key}: {item.before ? "مسموح" : "غير مسموح"} ←{" "}
                {item.after ? "مسموح" : "غير مسموح"}
              </span>
            ))}
          </dd>
        </>
      )}
      {preview.roleChanges && (
        <>
          <dt>الأدوار التفصيلية</dt>
          <dd>
            {preview.roleChanges.before.join("، ") || "بدون دور"} ←{" "}
            {preview.roleChanges.after.join("، ") || "بدون دور"}
          </dd>
        </>
      )}
      {preview.businessType && (
        <>
          <dt>نوع النشاط</dt>
          <dd>{preview.businessType.label}</dd>
        </>
      )}
      {preview.specialty && (
        <>
          <dt>الاختصاص</dt>
          <dd>{SPECIALTY[preview.specialty] ?? preview.specialty}</dd>
        </>
      )}
      {preview.plan?.name && (
        <>
          <dt>الباقة</dt>
          <dd>{preview.plan.name}</dd>
        </>
      )}
      {sizeText && (
        <>
          <dt>الحجم</dt>
          <dd>{sizeText}</dd>
        </>
      )}
      {preview.modules && preview.modules.length > 0 && (
        <>
          <dt>الأقسام المفعّلة</dt>
          <dd className="ap-list">
            {preview.modules.map((m) => (
              <span key={m.key}>
                {m.label}{" "}
                <em>
                  ({m.enabled}/{m.total})
                </em>
              </span>
            ))}
          </dd>
        </>
      )}
      {preview.tenantActions && preview.tenantActions.length > 0 && (
        <>
          <dt>إجراءات الحساب</dt>
          <dd className="ap-list">
            {preview.tenantActions.map((a) => (
              <span key={a.action}>{a.label}</span>
            ))}
          </dd>
        </>
      )}
      {preview.users && preview.users.length > 0 && (
        <>
          <dt>المستخدمون</dt>
          <dd className="ap-list">
            {preview.users.map((u) => (
              <span key={u.username}>
                {u.username} ({u.role}) — {u.credentials}
                {u.mustChangePassword && " · يغيّرها عند أول دخول"}
              </span>
            ))}
          </dd>
        </>
      )}
      {preview.subscription && (
        <>
          <dt>الاشتراك</dt>
          <dd>
            {preview.subscription.trialDays ? `تجربة ${preview.subscription.trialDays} يوم — ` : ""}
            {preview.subscription.billing}
          </dd>
        </>
      )}
    </dl>
  );
}

export function ApprovalCard({ approval }: { approval: Approval }) {
  const risk = RISK[approval.risk];
  const [projectDirty, setProjectDirty] = useState(false);
  const project = approval.preview?.project;
  return (
    <article className="approval-card" aria-label={`طلب موافقة: ${approval.action}`}>
      <header className="ap-head">
        <span className="ap-icon">
          <ShieldAlert size={16} />
        </span>
        <h3>طلب موافقة</h3>
        {approval.planVersion !== undefined && approval.planVersion > 1 && (
          <Badge tone="amber">خطة محدّثة v{approval.planVersion}</Badge>
        )}
        <Badge tone={risk.tone}>خطورة {risk.label}</Badge>
      </header>
      <dl className="ap-grid">
        <dt>العميل</dt>
        <dd>{approval.customerName}</dd>
        <dt>الطلب</dt>
        <dd className="ap-strong">{approval.action}</dd>
        {approval.oldValue !== null && (
          <>
            <dt>التغيير</dt>
            <dd>
              <span className="ap-old">{approval.oldValue}</span>
              <span className="ap-arrow" aria-hidden="true">
                ←
              </span>
              <span className="ap-new">{approval.newValue}</span>
            </dd>
          </>
        )}
        {approval.agentLimit && (
          <>
            <dt>حد صلاحية الوكيل</dt>
            <dd>{approval.agentLimit}</dd>
          </>
        )}
        <dt>السبب</dt>
        <dd className="ap-reason">{approval.reason}</dd>
      </dl>
      {approval.preview && <PlanPreview preview={approval.preview} />}
      {project && <ProjectPlan project={project} conversationId={approval.conversationId ?? undefined} />}
      {project && <ProjectReview approval={approval} onDirty={setProjectDirty} />}
      {approval.preview && (
        <p className="ap-note">الموافقة تخص هذه الخطة بالضبط؛ أي تغيير فيها يحتاج موافقة جديدة.</p>
      )}
      <Decision
        approval={approval}
        blocked={
          projectDirty ||
          (approval.preview?.projectAction === "confirm_project_deposit" && !project?.paymentReference)
        }
      />
    </article>
  );
}
