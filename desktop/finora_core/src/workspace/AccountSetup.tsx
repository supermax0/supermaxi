import { Building2, ShieldCheck, Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useCan } from "../data/can";
import { useAccount, useLinkAccount, useProposeAccount } from "../data/accountHooks";
import type { AccountProposal } from "../data/accounts";
import { ErrorState, FinoraButton, errorText } from "../ui/primitives";
import { toast } from "../ui/toast";
import { useUi } from "../state/ui";

export function AccountSetup({
  conversationId,
  tenantSlug,
}: {
  conversationId: string;
  tenantSlug: string | null;
}) {
  const allowed = useCan("settings.manage");
  const [open, setOpen] = useState(false);
  const [slug, setSlug] = useState("");
  const [reason, setReason] = useState("");
  const [verified, setVerified] = useState(false);
  const [feature, setFeature] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [employee, setEmployee] = useState("");
  const [preset, setPreset] = useState("sales");
  const [role, setRole] = useState("");
  const account = useAccount(conversationId, open && allowed);
  const link = useLinkAccount(conversationId);
  const proposal = useProposeAccount(conversationId);
  const setOverlay = useUi((state) => state.setOverlay);
  const request = (value: AccountProposal) =>
    proposal.mutate(value, {
      onSuccess: () => {
        toast.success("خطة حساب العميل جاهزة للمراجعة");
        setOverlay("activity");
      },
      onError: (error) => toast.error(errorText(error)),
    });
  const data = account.data;
  const state = data?.account;
  const card = useRef<HTMLElement>(null);
  useEffect(() => {
    const element = card.current;
    const pane = element?.closest(".cp-scroll");
    if (open && data && element && pane) {
      pane.scrollTo?.({
        top: pane.scrollTop + element.getBoundingClientRect().top - pane.getBoundingClientRect().top,
        behavior: "smooth",
      });
    }
  }, [open, data]);
  return (
    <section ref={card} className="cp-card account-setup" aria-label="حساب العميل وترتيبه">
      <header className="cp-card-head">
        <h3>
          <Building2 size={16} /> حساب العميل
        </h3>
      </header>
      <p className="account-scope" dir="auto">
        {state
          ? `${state.companyName} · ${state.tenantSlug}`
          : tenantSlug || "غير مرتبط — يلزم التحقق من ملكية الحساب"}
      </p>
      {allowed && (
        <FinoraButton size="sm" variant="soft" onClick={() => setOpen((value) => !value)}>
          <Sparkles size={15} />
          {open ? "إغلاق أدوات الحساب" : "ترتيب حساب العميل"}
        </FinoraButton>
      )}
      {open && (
        <div className="account-tools">
          <p className="account-scope">
            <ShieldCheck size={14} /> كل تعديل يخص حساب هذا العميل فقط، ويُراجع قبل التطبيق.
          </p>
          {account.isPending && <p role="status">جارٍ فحص الحساب…</p>}
          {account.isError && <ErrorState error={account.error} onRetry={() => void account.refetch()} />}
          {data?.error && (
            <p className="media-error" role="alert">
              {data.error}
            </p>
          )}
          {data && !data.tenantSlug && (
            <form
              onSubmit={(event) => {
                event.preventDefault();
                link.mutate(
                  { tenantSlug: slug, reason, ownershipVerified: verified },
                  { onError: (error) => toast.error(errorText(error)) },
                );
              }}
            >
              <label>
                معرّف شركة العميل
                <input
                  aria-label="معرّف شركة العميل"
                  value={slug}
                  onChange={(event) => setSlug(event.target.value)}
                  dir="ltr"
                  placeholder="company-slug"
                  required
                />
              </label>
              <label>
                دليل التحقق من الملكية
                <textarea
                  aria-label="دليل التحقق من الملكية"
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  minLength={8}
                  maxLength={300}
                  placeholder="مثلاً: تأكيد المالك عبر قناة الشركة المسجلة"
                  required
                />
              </label>
              <label className="account-check">
                <input
                  type="checkbox"
                  checked={verified}
                  onChange={(event) => setVerified(event.target.checked)}
                />{" "}
                تحققت من ملكية العميل؛ الاسم أو كلامه وحده لا يكفي
              </label>
              <FinoraButton
                size="sm"
                variant="primary"
                type="submit"
                disabled={!verified || reason.trim().length < 8 || !slug.trim()}
                loading={link.isPending}
              >
                ربط الحساب الموثّق
              </FinoraButton>
            </form>
          )}
          {state && (
            <>
              <div className="account-section">
                <strong>ترتيب حسب النشاط</strong>
                <div className="account-profiles">
                  {data.profiles.map((profile) => (
                    <button
                      type="button"
                      key={profile.key}
                      disabled={proposal.isPending}
                      onClick={() => request({ operation: "profile", profile: profile.key })}
                    >
                      <strong>{profile.label}</strong>
                      <small>{profile.needs}</small>
                    </button>
                  ))}
                </div>
              </div>
              <div className="account-section">
                <strong>إظهار أو إخفاء صفحة</strong>
                <select
                  aria-label="صفحة حساب العميل"
                  value={feature}
                  onChange={(event) => setFeature(event.target.value)}
                >
                  <option value="">اختَر الصفحة</option>
                  {state.features
                    .filter((row) => !row.protected)
                    .map((row) => (
                      <option key={row.key} value={row.key}>
                        {row.label} — {row.enabled ? "ظاهرة" : "مخفية"}
                        {!row.available ? " · خارج الباقة" : ""}
                      </option>
                    ))}
                </select>
                <label className="account-check">
                  <input
                    type="checkbox"
                    checked={enabled}
                    onChange={(event) => setEnabled(event.target.checked)}
                  />{" "}
                  إظهار الصفحة للعميل
                </label>
                <FinoraButton
                  size="sm"
                  variant="soft"
                  disabled={!feature || proposal.isPending}
                  onClick={() => request({ operation: "feature", feature, enabled })}
                >
                  مراجعة تغيير الصفحة
                </FinoraButton>
              </div>
              <div className="account-section">
                <strong>صلاحيات موظفي هذا الحساب</strong>
                <select
                  aria-label="موظف حساب العميل"
                  value={employee}
                  onChange={(event) => {
                    setEmployee(event.target.value);
                    setRole("");
                  }}
                >
                  <option value="">اختَر الموظف</option>
                  {state.employees
                    .filter((row) => !row.owner && row.active)
                    .map((row) => (
                      <option key={row.id} value={row.id}>
                        {row.name} · {row.username}
                      </option>
                    ))}
                </select>
                <select
                  aria-label="نمط صلاحيات الموظف"
                  value={preset}
                  onChange={(event) => setPreset(event.target.value)}
                >
                  {data.permissionPresets.map((row) => (
                    <option key={row.key} value={row.key}>
                      {row.label}
                    </option>
                  ))}
                </select>
                <select
                  aria-label="الدور التفصيلي للموظف"
                  value={role}
                  onChange={(event) => setRole(event.target.value)}
                >
                  <option value="">الحفاظ على الأدوار التفصيلية الحالية</option>
                  {state.roles
                    .filter(
                      (row) =>
                        !/admin|manage_users|manage_permissions|delete_tenant/i.test(
                          `${row.name} ${row.permissions.join(" ")}`,
                        ),
                    )
                    .map((row) => (
                      <option key={row.id} value={row.id}>
                        استبدال الأدوار بـ {row.name}
                      </option>
                    ))}
                </select>
                <small>
                  صلاحيات المالك محفوظة. تغيير النمط يضبط صلاحيات البيع والمخزون والمال؛ الدور التفصيلي يضبط
                  صلاحيات الأقسام مثل العيادة.
                </small>
                <FinoraButton
                  size="sm"
                  variant="soft"
                  disabled={!employee || proposal.isPending}
                  onClick={() =>
                    request({
                      operation: "permissions",
                      employee_id: Number(employee),
                      permission_preset: preset,
                      ...(role ? { role_ids: [Number(role)] } : {}),
                    })
                  }
                >
                  مراجعة صلاحيات الموظف
                </FinoraButton>
              </div>
            </>
          )}
        </div>
      )}
    </section>
  );
}
