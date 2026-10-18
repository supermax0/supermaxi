import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { finora, toFinoraError } from "@/api/finora";
import type { HRApplication, HRLookups, HRRecruitForm } from "@/api/finora/hr";
import { useConnection } from "@/stores/connection";
import { SupplierModal } from "../suppliers/SupplierDialogs";
import { HRActionDialog, type HRAction } from "./HRDialogs";
import { hrInput, hrPrimary, hrSecondary } from "./shared";
import { RecruitFormBuilder } from "./RecruitFormBuilder";

const states: Record<string, string> = {
  new: "جديد",
  reviewing: "قيد المراجعة",
  interview: "مقابلة",
  accepted: "مقبول",
  rejected: "مرفوض",
  deferred: "مؤجل",
};
export function Recruitment({
  tools,
  onClose,
  onOpen,
}: {
  tools: HRLookups;
  onClose(): void;
  onOpen(id: number): void;
}) {
  const [formFilter, setFormFilter] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [editor, setEditor] = useState<"new" | HRRecruitForm | null>(null);
  const [action, setAction] = useState<HRAction | null>(null);
  const [selected, setSelected] = useState<HRApplication | null>(null);
  const [linkUrl, setLinkUrl] = useState("");
  const [linkMessage, setLinkMessage] = useState("");
  const queryClient = useQueryClient();
  const data = useQuery({
    queryKey: ["hr", "recruitment", formFilter, status, page],
    queryFn: () => finora.hr.recruitment({ form_id: formFilter, status, page }),
  });
  const commandId = useRef<string | null>(null);
  const publish = useMutation({
    mutationFn: ({
      form,
      pin,
      expires,
      maximum,
    }: {
      form: HRRecruitForm;
      pin: string;
      expires: string;
      maximum: string;
    }) => {
      commandId.current ??= crypto.randomUUID();
      return finora.hr.command(
        "recruitment.link",
        {
          form_id: form.id,
          pin,
          private: !!pin,
          expires_at: `${expires}T23:59:00+03:00`,
          max_submissions: Number(maximum),
        },
        commandId.current,
      );
    },
    onSuccess: async (result) => {
      commandId.current = null;
      setLinkUrl(result.url ?? "");
      await queryClient.invalidateQueries({ queryKey: ["hr", "recruitment"] });
    },
  });
  const online = useConnection((s) => s.status === "online");
  const [linkForm, setLinkForm] = useState<HRRecruitForm | null>(null);
  const [pin, setPin] = useState("");
  const [expires, setExpires] = useState("");
  const [maximum, setMaximum] = useState("100");
  const download = useMutation({
    mutationFn: async (id: number) => {
      const file = await finora.hr.applicantFile(id);
      const url = URL.createObjectURL(
        new Blob([Uint8Array.from(atob(file.content), (c) => c.charCodeAt(0))], { type: file.mime }),
      );
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = file.filename;
      anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    },
  });
  const convert = (application: HRApplication) => {
    const link = data.data?.links.find((l) => l.id === application.link_id),
      form = data.data?.forms.find((f) => f.id === link?.form_id);
    const formFields = application.fields;
    const find = (pattern: RegExp) => {
      const field = formFields.find((f) => pattern.test(f.label));
      const value = field && application.answers[field.key];
      return typeof value === "string" ? value : "";
    };
    setAction({
      title: "إكمال بيانات المتقدم وتحويله إلى موظف",
      action: "recruitment.convert",
      financial: true,
      payload: { application_id: application.id, version: application.version },
      payloadNamespace: "employee",
      fields: [
        { name: "name", label: "الاسم الكامل", required: true, initial: find(/الاسم|name/i) },
        { name: "phone", label: "الهاتف", initial: find(/هاتف|phone/i) },
        { name: "email", label: "البريد الإلكتروني", initial: find(/بريد|email/i) },
        {
          name: "branch_id",
          label: "الفرع",
          numeric: true,
          required: true,
          initial: String(form?.branch_id ?? ""),
          options: tools.branches.map((b) => ({ value: String(b.id), label: b.name })),
        },
        { name: "job_title", label: "الوظيفة", required: true },
        { name: "joined_on", label: "تاريخ التعيين", type: "date", required: true },
        ...(tools.permissions.includes("hr.payroll.prepare")
          ? [
              { name: "salary", label: "الراتب الأساسي", type: "number" as const, required: true },
              {
                name: "salary_type",
                label: "نوع الأجر",
                required: true,
                options: [
                  { value: "monthly", label: "شهري" },
                  { value: "daily", label: "يومي" },
                  { value: "hourly", label: "بالساعة" },
                  { value: "commission", label: "عمولات" },
                ],
              },
            ]
          : []),
      ],
    });
  };
  return (
    <>
      <SupplierModal title="طلبات التوظيف واستمارات التقديم" onClose={onClose} busy={false} wide>
        <div className="space-y-5">
          <div className="flex flex-wrap gap-2">
            <button className={hrPrimary} disabled={!online} onClick={() => setEditor("new")}>
              <Plus size={16} />
              إنشاء استمارة
            </button>
            <select
              aria-label="تصفية استمارات التوظيف"
              className={`${hrInput} w-48`}
              value={formFilter}
              onChange={(e) => {
                setFormFilter(e.target.value);
                setPage(1);
              }}
            >
              <option value="">كل الاستمارات</option>
              {data.data?.forms.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.title}
                </option>
              ))}
            </select>
            <select
              aria-label="حالة طلب التوظيف"
              className={`${hrInput} w-40`}
              value={status}
              onChange={(e) => {
                setStatus(e.target.value);
                setPage(1);
              }}
            >
              <option value="">كل الحالات</option>
              {Object.entries(states).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </div>
          {data.isPending && <p className="text-sm text-ink-faint">تحميل الاستمارات والطلبات...</p>}
          {data.error && (
            <p role="alert" className="text-sm text-danger">
              {toFinoraError(data.error).message}
            </p>
          )}
          <div className="grid gap-3 sm:grid-cols-2">
            {data.data?.forms.map((form) => (
              <section
                key={form.id}
                className="space-y-3 rounded-panel border border-line bg-violet-soft/20 p-4"
              >
                <h3 className="text-sm font-semibold">{form.title}</h3>
                <p className="text-xs text-ink-faint">
                  نسخة {form.version} · {form.fields.length} حقول
                </p>
                <div className="flex gap-2">
                  <button className={hrSecondary} disabled={!online} onClick={() => setEditor(form)}>
                    تعديل
                  </button>
                  <button
                    className={hrSecondary}
                    disabled={!online}
                    onClick={() => {
                      setLinkForm(form);
                      setLinkUrl("");
                      setLinkMessage("");
                    }}
                  >
                    إنشاء رابط التقديم
                  </button>
                </div>
              </section>
            ))}
          </div>
          {data.data?.links.length ? (
            <details className="rounded-panel border border-line p-4">
              <summary className="cursor-pointer text-xs">روابط التقديم المنشورة</summary>
              <div className="mt-3 space-y-3">
                {data.data.links.map((link) => (
                  <div key={link.id} className="flex items-center gap-3 text-xs">
                    <span>
                      #{link.id} · {link.private ? "خاص" : "عام"} · {link.received}/{link.max_submissions} طلب
                      · ينتهي {link.expires_at.slice(0, 10)}
                    </span>
                    <button
                      className="ms-auto text-violet"
                      disabled={!online}
                      onClick={() =>
                        setAction({
                          title: "تغيير استقبال الطلبات",
                          action: "recruitment.link_state",
                          payload: { link_id: link.id, version: link.version, active: !link.active },
                          fields: [],
                        })
                      }
                    >
                      {link.active ? "إيقاف" : "تفعيل"}
                    </button>
                  </div>
                ))}
              </div>
            </details>
          ) : null}
          <h3 className="text-sm font-semibold">الطلبات ({data.data?.total ?? 0})</h3>
          {data.data?.rows.map((row) => (
            <button
              key={row.id}
              className="flex w-full items-center justify-between rounded-panel border border-line p-4 text-start text-xs hover:bg-violet-soft/25"
              onClick={() => setSelected(row)}
            >
              <span>
                طلب #{row.id} · {row.date.slice(0, 10)}
                <small className="mt-2 block text-ink-faint">
                  {Object.values(row.answers)
                    .filter((v) => typeof v === "string")
                    .slice(0, 2)
                    .join(" · ")}
                </small>
              </span>
              <span className="text-violet">{row.person_id ? "تم تحويله إلى موظف" : states[row.status]}</span>
            </button>
          ))}
          {!data.isPending && !data.data?.rows.length && (
            <p className="py-4 text-center text-sm text-ink-faint">لا توجد طلبات تقديم بهذه التصفية</p>
          )}
          <div className="flex items-center justify-between text-xs">
            <button className={hrSecondary} disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
              السابق
            </button>
            <span>
              صفحة {page} من {data.data?.total_pages ?? 1}
            </span>
            <button
              className={hrSecondary}
              disabled={page >= (data.data?.total_pages ?? 1)}
              onClick={() => setPage((p) => p + 1)}
            >
              التالي
            </button>
          </div>
        </div>
      </SupplierModal>
      {editor && (
        <RecruitFormBuilder
          form={editor === "new" ? null : editor}
          tools={tools}
          onClose={() => setEditor(null)}
        />
      )}
      {action && (
        <HRActionDialog
          action={action}
          onClose={() => {
            setAction(null);
            setSelected(null);
          }}
        />
      )}
      {linkForm && (
        <SupplierModal
          title={`رابط التقديم: ${linkForm.title}`}
          onClose={() => setLinkForm(null)}
          busy={publish.isPending}
        >
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault();
              publish.mutate({ form: linkForm, pin, expires, maximum });
            }}
          >
            <label className="block space-y-2 text-xs">
              تاريخ انتهاء الرابط
              <input
                className={hrInput}
                type="date"
                required
                value={expires}
                onChange={(e) => setExpires(e.target.value)}
              />
            </label>
            <label className="block space-y-2 text-xs">
              العدد الأقصى للطلبات
              <input
                className={hrInput}
                type="number"
                required
                min={1}
                max={10000}
                value={maximum}
                onChange={(e) => setMaximum(e.target.value)}
              />
            </label>
            <label className="block space-y-2 text-xs">
              رمز PIN اختياري للرابط الخاص
              <input
                className={hrInput}
                type="password"
                minLength={4}
                maxLength={50}
                value={pin}
                onChange={(e) => setPin(e.target.value)}
              />
            </label>
            <button className={hrPrimary} disabled={!online || publish.isPending || !!linkUrl}>
              إنشاء الرابط
            </button>
            {publish.error && (
              <p role="alert" className="text-sm text-danger">
                {toFinoraError(publish.error).message}
              </p>
            )}
          </form>
          {linkUrl && (
            <div className="mt-4 space-y-3 rounded-panel border border-line p-3">
              <p className="text-xs leading-6">
                الرابط جاهز. انسخه من هنا واحتفظ به؛ تفعيل الطلبات يعتمد على تاريخ الانتهاء والعدد المحدد.
              </p>
              <button
                className={hrSecondary}
                onClick={() => {
                  void (async () => {
                    try {
                      const config = await finora.config.get();
                      if (!config.serverUrl) throw new Error("عنوان السيرفر غير متوفر");
                      await navigator.clipboard.writeText(`${config.serverUrl.replace(/\/$/, "")}${linkUrl}`);
                      setLinkMessage("تم نسخ الرابط");
                    } catch {
                      setLinkMessage("تعذّر النسخ؛ انسخ المسار الظاهر أدناه");
                    }
                  })();
                }}
              >
                نسخ رابط التقديم
              </button>
              <input className={hrInput} readOnly dir="ltr" value={linkUrl} aria-label="مسار رابط التقديم" />
              {linkMessage && <p className="text-xs">{linkMessage}</p>}
            </div>
          )}
        </SupplierModal>
      )}
      {selected && !action && (
        <SupplierModal title={`طلب التوظيف #${selected.id}`} onClose={() => setSelected(null)} busy={false}>
          <div className="space-y-4">
            {Object.entries(selected.answers).map(([key, value]) => (
              <div key={key} className="border-b border-line pb-3 text-xs">
                <p className="text-ink-faint">{selected.fields.find((f) => f.key === key)?.label ?? key}</p>
                <p className="mt-2 break-words">
                  {typeof value === "object" && !Array.isArray(value)
                    ? String((value as Record<string, unknown>)?.filename ?? "مرفق")
                    : Array.isArray(value)
                      ? value.join("، ")
                      : String(value)}
                </p>
              </div>
            ))}
            {selected.files.map((file) => (
              <button
                key={file.id}
                className={hrSecondary}
                disabled={download.isPending}
                onClick={() => download.mutate(file.id)}
              >
                تنزيل {file.filename}
              </button>
            ))}
            {download.error && (
              <p role="alert" className="text-xs text-danger">
                {toFinoraError(download.error).message}
              </p>
            )}
            <p className="text-xs">{selected.note || "بدون ملاحظات مراجعة"}</p>
            {!selected.person_id && (
              <button
                className={hrSecondary}
                disabled={!online}
                onClick={() =>
                  setAction({
                    title: "مراجعة طلب التوظيف",
                    action: "recruitment.decide",
                    payload: { application_id: selected.id, version: selected.version },
                    fields: [
                      {
                        name: "status",
                        label: "الحالة",
                        required: true,
                        options: Object.entries(states).map(([value, label]) => ({ value, label })),
                        initial: selected.status,
                      },
                      { name: "note", label: "ملاحظات المراجعة", type: "textarea", initial: selected.note },
                    ],
                  })
                }
              >
                تحديث حالة الطلب
              </button>
            )}
            {!selected.person_id &&
              selected.status === "accepted" &&
              tools.permissions.includes("hr.employees.create") && (
                <button className={hrPrimary} disabled={!online} onClick={() => convert(selected)}>
                  تحويل إلى موظف
                </button>
              )}
            {selected.person_id && (
              <button
                className={hrSecondary}
                onClick={() => {
                  onClose();
                  if (selected.person_id) onOpen(selected.person_id);
                }}
              >
                فتح ملف الموظف
              </button>
            )}
          </div>
        </SupplierModal>
      )}
    </>
  );
}
