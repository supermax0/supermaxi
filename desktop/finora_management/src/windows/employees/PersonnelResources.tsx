import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { finora, toFinoraError } from "@/api/finora";
import type { HRDetails, HRLookups } from "@/api/finora/hr";
import type { HRAction } from "./HRDialogs";
import { hrSecondary } from "./shared";
import { formatIqd } from "@/utils/money";
import { HRReportDialog } from "./HRReportDialog";
const genderLabels: Record<string, string> = { male: "ذكر", female: "أنثى", other: "آخر" };

export function PersonnelResources({
  details,
  tools,
  can,
  onAction,
}: {
  details: HRDetails;
  tools: HRLookups;
  can(permission: string): boolean;
  onAction(action: HRAction): void;
}) {
  const person = details.person;
  const payload = { person_id: person.id };
  const [settlementReport, setSettlementReport] = useState(false);
  const download = useMutation({
    mutationFn: async (id: number) => {
      const file = await finora.hr.document(id);
      const bytes = Uint8Array.from(atob(file.content), (c) => c.charCodeAt(0));
      const url = URL.createObjectURL(new Blob([bytes], { type: file.mime }));
      const link = document.createElement("a");
      link.href = url;
      link.download = file.filename;
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    },
  });
  return (
    <div className="space-y-4">
      {details.offboarding && (
        <section className="rounded-panel border border-line/70 bg-violet-soft/20 p-4">
          <h3 className="text-sm font-semibold">كشف نهاية الخدمة · {details.offboarding.ends_on}</h3>
          <p className="mt-2 text-xs text-ink-soft">{details.offboarding.reason}</p>
          {[
            ["approved_salary_due", "رواتب سابقة معتمدة لم تُصرف"],
            ["advance_remaining", "سلف متبقية"],
            ["commission_due", "عمولات معتمدة متبقية"],
            ["commission_pending", "عمولات تحتاج مراجعة"],
          ].map(
            ([key, label]) =>
              typeof details.offboarding?.settlement[key ?? ""] === "number" && (
                <p key={key} className="mt-3 flex justify-between text-xs">
                  <span>{label}</span>
                  <span>{formatIqd(Number(details.offboarding?.settlement[key ?? ""]))}</span>
                </p>
              ),
          )}
          {details.offboarding.settlement.earned_payroll &&
          typeof details.offboarding.settlement.earned_payroll === "object" ? (
            <p className="mt-3 text-xs">
              المحتسب حتى آخر يوم عمل:{" "}
              {formatIqd(
                Number((details.offboarding.settlement.earned_payroll as Record<string, unknown>).net ?? 0),
              )}
            </p>
          ) : null}
          <p className="mt-3 text-xs leading-6 text-ink-faint">
            يُعتمد الأجر المحتسب ضمن مسير الفترة عند إقفالها، ثم يُصرف من الخزينة بصلاحية الصرف. رصيد الإجازة
            يُسوّى بحسب السياسة ببدل موثّق. هذا الكشف لا ينشئ دفعة تلقائية.
          </p>
          {["hr.payroll.view", "hr.commission.view", "hr.advance.view", "hr.reports.view"].every(can) && (
            <button className={`${hrSecondary} mt-3`} onClick={() => setSettlementReport(true)}>
              طباعة كشف نهاية الخدمة
            </button>
          )}
        </section>
      )}
      {settlementReport && (
        <HRReportDialog
          tab="settlement"
          query={{ period: "this_month", person_id: person.id }}
          onClose={() => setSettlementReport(false)}
        />
      )}
      {Object.keys(details.private_info).length > 0 && (
        <section className="rounded-panel border border-line/70 p-4">
          <h3 className="text-xs font-semibold">البيانات الخاصة</h3>
          {(
            [
              ["birth_date", "تاريخ الميلاد"],
              ["national_id", "رقم الهوية"],
              ["gender", "الجنس"],
              ["bank_name", "المصرف"],
              ["bank_account", "الحساب المصرفي"],
            ] as const
          ).map(
            ([key, label]) =>
              details.private_info[key] && (
                <p key={key} className="mt-3 flex justify-between gap-3 text-xs">
                  <span className="text-ink-faint">{label}</span>
                  <span>
                    {key === "gender"
                      ? (genderLabels[details.private_info[key]] ?? details.private_info[key])
                      : details.private_info[key]}
                  </span>
                </p>
              ),
          )}
        </section>
      )}
      {can("hr.employees.edit") &&
        can("hr.resources.manage") &&
        (can("hr.documents.view") || can("hr.payroll.prepare")) && (
          <button
            className={hrSecondary}
            onClick={() =>
              onAction({
                title: "البيانات الشخصية والمصرفية الخاصة",
                action: "employee.update",
                financial: true,
                payload: { person_id: person.id, version: person.version },
                fields: [
                  ...(can("hr.documents.view")
                    ? [
                        {
                          name: "birth_date",
                          label: "تاريخ الميلاد",
                          type: "date" as const,
                          initial: details.private_info.birth_date ?? "",
                        },
                        {
                          name: "national_id",
                          label: "رقم الهوية",
                          initial: details.private_info.national_id ?? "",
                        },
                        {
                          name: "gender",
                          label: "الجنس",
                          initial: details.private_info.gender ?? "",
                          options: [
                            { value: "male", label: "ذكر" },
                            { value: "female", label: "أنثى" },
                            { value: "other", label: "آخر" },
                          ],
                        },
                      ]
                    : []),
                  ...(can("hr.payroll.prepare") &&
                  (can("hr.payroll.view") || details.private_info.bank_name !== undefined)
                    ? [
                        { name: "bank_name", label: "المصرف", initial: details.private_info.bank_name ?? "" },
                        {
                          name: "bank_account",
                          label: "الحساب المصرفي",
                          initial: details.private_info.bank_account ?? "",
                        },
                      ]
                    : []),
                ],
              })
            }
          >
            تعديل البيانات الخاصة
          </button>
        )}
      {can("hr.employees.state") && person.status !== "terminated" && (
        <button
          className={hrSecondary}
          onClick={() =>
            onAction({
              title: "تغيير الحالة الوظيفية",
              action: "employee.state",
              financial: true,
              payload: { person_id: person.id, version: person.version },
              fields: [
                {
                  name: "status",
                  label: "الحالة",
                  required: true,
                  initial: person.status,
                  options: [
                    { value: "active", label: "نشط" },
                    { value: "suspended", label: "موقوف" },
                    { value: "leave", label: "إجازة" },
                  ],
                },
                { name: "reason", label: "سبب التغيير", required: true },
                ...(can("manage_employees") && person.employee_id
                  ? [
                      {
                        name: "change_login",
                        label: "تطبيق الحالة على حساب الدخول أيضاً",
                        type: "checkbox" as const,
                      },
                    ]
                  : []),
              ],
            })
          }
        >
          تغيير الحالة
        </button>
      )}
      {can("hr.resources.manage") && (
        <div className="flex flex-wrap gap-2">
          <button
            className={hrSecondary}
            onClick={() =>
              onAction({
                title: "إضافة مستند خاص",
                action: "document.create",
                payload,
                fields: [
                  { name: "title", label: "عنوان المستند", required: true },
                  {
                    name: "kind",
                    label: "نوع المستند",
                    required: true,
                    options: [
                      { value: "contract", label: "عقد" },
                      { value: "identity", label: "هوية" },
                      { value: "certificate", label: "شهادة" },
                      { value: "medical", label: "مستند طبي" },
                      { value: "other", label: "أخرى" },
                      { value: "photo", label: "صورة الموظف" },
                    ],
                  },
                  { name: "expires_on", label: "تاريخ الانتهاء", type: "date" },
                  { name: "content", label: "PDF أو صورة، حتى 4 ميغابايت", type: "file", required: true },
                ],
              })
            }
          >
            إضافة مستند
          </button>
          <button
            className={hrSecondary}
            disabled={!tools.assets.some((a) => a.branch_id === person.branch_id)}
            onClick={() =>
              onAction({
                title: "تسليم عهدة من الأصول",
                action: "asset.assign",
                payload,
                fields: [
                  {
                    name: "asset_id",
                    label: "الأصل",
                    numeric: true,
                    required: true,
                    options: tools.assets
                      .filter((a) => a.branch_id === person.branch_id)
                      .map((a) => ({ value: String(a.id), label: a.name })),
                  },
                  { name: "note", label: "حالة الأصل عند التسليم", type: "textarea", required: true },
                ],
              })
            }
          >
            تسليم عهدة
          </button>
          {can("manage_employees") && (
            <button
              className={hrSecondary}
              onClick={() =>
                onAction({
                  title: "ربط حساب دخول موجود",
                  action: "employee.update",
                  payload: { ...payload, version: person.version },
                  fields: [
                    {
                      name: "employee_id",
                      label: "حساب الدخول",
                      numeric: true,
                      required: true,
                      options: tools.accounts
                        .filter((a) => !a.branch_id || a.branch_id === person.branch_id)
                        .map((a) => ({ value: String(a.id), label: a.name })),
                    },
                  ],
                })
              }
            >
              ربط حساب دخول
            </button>
          )}
        </div>
      )}
      {details.documents.length > 0 && (
        <section className="rounded-panel border border-line/70 p-4">
          <h3 className="text-xs font-semibold">المستندات الخاصة</h3>
          {details.documents.map((d) => (
            <div key={d.id} className="mt-3 flex items-center justify-between gap-2 text-xs">
              <span>
                {d.title}
                <small className="block text-ink-faint">{d.expires_on && `ينتهي: ${d.expires_on}`}</small>
              </span>
              <button
                className="text-violet"
                disabled={download.isPending}
                onClick={() => download.mutate(d.id)}
              >
                تنزيل
              </button>
            </div>
          ))}
          {download.error && (
            <p role="alert" className="mt-3 text-xs text-danger">
              {toFinoraError(download.error).message}
            </p>
          )}
        </section>
      )}
      {person.employee_id && can("manage_employees") && can("hr.settings.manage") && (
        <button
          className={hrSecondary}
          onClick={() =>
            onAction({
              title: "نطاق حساب الموظف في الموارد البشرية",
              action: "scope.update",
              financial: true,
              payload: {
                employee_id: person.employee_id,
                version: tools.access_scopes.find((s) => s.employee_id === person.employee_id)?.version ?? 1,
              },
              fields: [
                {
                  name: "mode",
                  label: "الموظفون المسموح عرضهم وإدارتهم",
                  initial:
                    tools.access_scopes.find((s) => s.employee_id === person.employee_id)?.mode ?? "all",
                  required: true,
                  options: [
                    { value: "all", label: "كل الموظفين ضمن الفروع المسموحة" },
                    { value: "department", label: "قسم محدد" },
                    { value: "manager", label: "المرؤوسون المباشرون" },
                    { value: "self", label: "ملفه الشخصي فقط" },
                  ],
                },
                {
                  name: "department_id",
                  label: "القسم (عند اختيار قسم محدد)",
                  numeric: true,
                  options: tools.departments
                    .filter((d) => !d.branch_id || d.branch_id === person.branch_id)
                    .map((d) => ({ value: String(d.id), label: d.name })),
                },
              ],
            })
          }
        >
          نطاق الصلاحيات
        </button>
      )}
      {details.assets.length > 0 && (
        <section className="rounded-panel border border-line/70 p-4">
          <h3 className="text-xs font-semibold">عُهد الموظف</h3>
          {details.assets.map((a) => (
            <div key={a.id} className="mt-3 flex justify-between gap-2 text-xs">
              <span>
                {a.name}
                <small className="block text-ink-faint">
                  {a.code} · {a.returned_at ? "مُرجعة" : "بعهدة الموظف"}
                </small>
              </span>
              {!a.returned_at && can("hr.resources.manage") && (
                <button
                  className="text-violet"
                  onClick={() =>
                    onAction({
                      title: "إرجاع عهدة",
                      action: "asset.return",
                      payload: { custody_id: a.id, version: a.version },
                      fields: [{ name: "reason", label: "حالة الأصل عند الإرجاع", required: true }],
                    })
                  }
                >
                  إرجاع
                </button>
              )}
            </div>
          ))}
        </section>
      )}
      {details.leave_balances.length > 0 && (
        <section className="rounded-panel border border-line/70 p-4">
          <h3 className="text-xs font-semibold">أرصدة الإجازات لهذه السنة</h3>
          {details.leave_balances.map((b) => (
            <p key={b.id} className="mt-3 flex justify-between text-xs">
              <span>{b.name}</span>
              <span>
                مستخدم {b.used} يوم · {b.remaining === null ? "بدون حد سنوي" : `متبقي ${b.remaining} يوم`}
              </span>
            </p>
          ))}
        </section>
      )}
      {can("hr.payroll.prepare") && (
        <button
          className={hrSecondary}
          onClick={() =>
            onAction({
              title: "تسوية على مسير غير معتمد",
              action: "payroll.adjustment",
              payload,
              financial: true,
              fields: [
                { name: "month", label: "الشهر", type: "month", required: true },
                {
                  name: "kind",
                  label: "نوع التسوية",
                  required: true,
                  options: [
                    { value: "allowance", label: "بدل / مكافأة" },
                    { value: "deduction", label: "استقطاع" },
                  ],
                },
                { name: "title", label: "سبب التسوية", required: true },
                { name: "amount", label: "المبلغ (د.ع)", type: "number", required: true },
              ],
            })
          }
        >
          إضافة بدل أو استقطاع
        </button>
      )}
      {can("hr.employees.state") && can("hr.resources.manage") && person.status !== "terminated" && (
        <button
          className={`${hrSecondary} text-danger`}
          onClick={() =>
            onAction({
              title: "إنهاء الخدمة وتوثيق التسوية",
              action: "employee.terminate",
              payload: { ...payload, version: person.version },
              financial: true,
              fields: [
                { name: "ends_on", label: "آخر يوم عمل", type: "date", required: true },
                { name: "reason", label: "سبب إنهاء الخدمة", required: true },
                { name: "settlement_note", label: "ملاحظات التسوية النهائية", type: "textarea" },
                {
                  name: "advance_agreement",
                  label: "تم توثيق اتفاق تسوية السلفة المتبقية",
                  type: "checkbox",
                },
                ...(can("manage_employees") && person.employee_id
                  ? [{ name: "disable_login", label: "إيقاف حساب الدخول أيضاً", type: "checkbox" as const }]
                  : []),
              ],
            })
          }
        >
          إنهاء الخدمة
        </button>
      )}
    </div>
  );
}
