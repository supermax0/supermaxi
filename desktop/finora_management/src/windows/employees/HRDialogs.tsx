import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Loader2, Save } from "lucide-react";
import { finora, toFinoraError } from "@/api/finora";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import type { HRPerson, HRLookups } from "@/api/finora/hr";
import { MoneyInput } from "@/components/MoneyInput";
import { useConnection } from "@/stores/connection";
import { SupplierModal } from "../suppliers/SupplierDialogs";
import { hrInput, hrPrimary, hrSecondary, labels, hrToday, useHRCommand } from "./shared";

export interface ActionField {
  name: string;
  label: string;
  type?:
    | "text"
    | "number"
    | "date"
    | "month"
    | "time"
    | "datetime-local"
    | "textarea"
    | "checkbox"
    | "weekdays"
    | "file";
  options?: { value: string; label: string }[];
  numeric?: boolean;
  required?: boolean;
  initial?: string | boolean | number[];
}
export interface HRAction {
  title: string;
  action: string;
  payload?: Record<string, unknown>;
  fields: ActionField[];
  financial?: boolean;
  onlineOnly?: boolean;
  notice?: string;
  payloadNamespace?: string;
}
export function HRCalendarDialog({ tools, onClose }: { tools: HRLookups; onClose(): void }) {
  const [branch, setBranch] = useState(String(tools.branches[0]?.id ?? ""));
  const [date, setDate] = useState(hrToday());
  const [title, setTitle] = useState("");
  const [working, setWorking] = useState(false);
  const save = useHRCommand(onClose);
  const online = useConnection((s) => s.status === "online");
  const existing = tools.calendar.find((c) => c.branch_id === Number(branch) && c.on_date === date);
  const selectDay = (nextBranch: string, nextDate: string) => {
    setBranch(nextBranch);
    setDate(nextDate);
    const current = tools.calendar.find((c) => c.branch_id === Number(nextBranch) && c.on_date === nextDate);
    setTitle(current?.title ?? "");
    setWorking(current?.working ?? false);
  };
  return (
    <SupplierModal title="تقويم العمل والعطل" busy={save.isPending} onClose={onClose}>
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate({
            action: "calendar.save",
            payload: {
              branch_id: Number(branch),
              on_date: date,
              title,
              working,
              ...(existing ? { version: existing.version } : {}),
            },
          });
        }}
      >
        <fieldset disabled={save.isPending || !online} className="space-y-4">
          <label className="block space-y-2 text-xs text-ink-soft">
            الفرع
            <select
              required
              className={hrInput}
              value={branch}
              onChange={(e) => selectDay(e.target.value, date)}
            >
              {tools.branches.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                </option>
              ))}
            </select>
          </label>
          <label className="block space-y-2 text-xs text-ink-soft">
            التاريخ
            <input
              required
              type="date"
              className={hrInput}
              value={date}
              onChange={(e) => selectDay(branch, e.target.value)}
            />
          </label>
          <label className="block space-y-2 text-xs text-ink-soft">
            اسم المناسبة
            <input
              required
              maxLength={150}
              className={hrInput}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
          </label>
          <label className="flex gap-2 text-sm">
            <input
              type="checkbox"
              className="accent-violet"
              checked={working}
              onChange={(e) => setWorking(e.target.checked)}
            />{" "}
            يوم عمل استثنائي
          </label>
          <p className="text-xs text-ink-faint">
            اليوم غير المحدد كيوم عمل يُحسب عطلة. الفترات المعتمدة تحتاج تسوية قبل تعديل التقويم.
          </p>
          <button className={hrPrimary}>
            {save.isPending ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}حفظ اليوم
          </button>
        </fieldset>
        {save.error && (
          <p className="text-sm text-danger" role="alert">
            {toFinoraError(save.error).message}
          </p>
        )}
        <div className="max-h-48 space-y-2 overflow-auto">
          {tools.calendar
            .filter((c) => c.branch_id === Number(branch))
            .map((c) => (
              <button
                type="button"
                key={c.id}
                className="flex w-full items-center justify-between rounded-control border border-line px-3 py-2 text-xs text-ink-soft hover:bg-violet-soft"
                onClick={() => selectDay(branch, c.on_date)}
              >
                <span>
                  {c.title} · {c.working ? "عمل" : "عطلة"}
                </span>
                <span dir="ltr">{c.on_date}</span>
              </button>
            ))}
        </div>
      </form>
    </SupplierModal>
  );
}
export function HRActionDialog({ action, onClose }: { action: HRAction; onClose(): void }) {
  const [file, setFile] = useState<{ content: string; mime: string; filename: string } | null>(null);
  const [fileError, setFileError] = useState("");
  const [values, setValues] = useState<Record<string, string | boolean | number[]>>(() =>
    Object.fromEntries(action.fields.map((f) => [f.name, f.initial ?? (f.type === "weekdays" ? [] : "")])),
  );
  const online = useConnection((s) => s.status === "online");
  const save = useHRCommand(onClose);
  return (
    <SupplierModal title={action.title} busy={save.isPending} onClose={onClose}>
      <form
        className="space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          const payload: Record<string, unknown> = { ...action.payload };
          if (action.action === "attendance.record") {
            payload.occurred_at = new Date().toISOString();
            if (!online) payload.source = "offline";
          }
          for (const field of action.fields) {
            const value = values[field.name];
            if (field.type === "file") {
              if (!file) {
                setFileError("اختر المستند أولاً");
                return;
              }
              Object.assign(payload, file);
              continue;
            }
            payload[field.name] =
              field.type === "weekdays"
                ? value
                : field.type === "checkbox"
                  ? value === true
                  : field.numeric || field.type === "number"
                    ? Number(value)
                    : field.type === "datetime-local"
                      ? value
                        ? new Date(`${String(value)}+03:00`).toISOString()
                        : ""
                      : value;
          }
          save.mutate({
            action: action.action,
            payload: action.payloadNamespace
              ? {
                  ...action.payload,
                  [action.payloadNamespace]: Object.fromEntries(
                    Object.entries(payload).filter(([key]) => !(key in (action.payload ?? {}))),
                  ),
                }
              : payload,
          });
        }}
      >
        <fieldset disabled={save.isPending} className="space-y-4">
          {action.fields.map((field) => {
            const FieldContainer = field.type === "weekdays" ? "fieldset" : "label";
            return (
              <FieldContainer key={field.name} className="block space-y-2 text-xs text-ink-soft">
                <span>{field.label}</span>
                {field.type === "file" ? (
                  <input
                    type="file"
                    accept="application/pdf,image/png,image/jpeg"
                    required={field.required}
                    className={hrInput}
                    onChange={(e) => {
                      setFile(null);
                      setFileError("");
                      const selected = e.target.files?.[0];
                      if (!selected) return;
                      if (
                        selected.size > 4 * 1024 * 1024 ||
                        !["application/pdf", "image/png", "image/jpeg"].includes(selected.type)
                      ) {
                        setFileError("اختر PDF أو صورة، بحجم أقصى 4 ميغابايت");
                        return;
                      }
                      const reader = new FileReader();
                      reader.onload = () =>
                        setFile({
                          filename: selected.name,
                          mime: selected.type,
                          content: String(reader.result).split(",")[1] ?? "",
                        });
                      reader.onerror = () => setFileError("تعذّرت قراءة الملف");
                      reader.readAsDataURL(selected);
                    }}
                  />
                ) : field.type === "weekdays" ? (
                  <span className="flex flex-wrap gap-3">
                    {["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"].map(
                      (label, index) => (
                        <label key={label} className="inline-flex items-center gap-1">
                          <input
                            type="checkbox"
                            className="accent-violet"
                            checked={
                              Array.isArray(values[field.name]) &&
                              (values[field.name] as number[]).includes(index)
                            }
                            onChange={(e) =>
                              setValues((v) => ({
                                ...v,
                                [field.name]: e.target.checked
                                  ? [
                                      ...(Array.isArray(v[field.name]) ? (v[field.name] as number[]) : []),
                                      index,
                                    ]
                                  : (Array.isArray(v[field.name]) ? (v[field.name] as number[]) : []).filter(
                                      (d) => d !== index,
                                    ),
                              }))
                            }
                          />
                          {label}
                        </label>
                      ),
                    )}
                  </span>
                ) : field.options ? (
                  <select
                    className={hrInput}
                    value={String(values[field.name])}
                    required={field.required}
                    onChange={(e) => setValues((v) => ({ ...v, [field.name]: e.target.value }))}
                  >
                    <option value="">اختر...</option>
                    {field.options.map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                ) : field.type === "textarea" ? (
                  <textarea
                    maxLength={2000}
                    className={`${hrInput} h-24 py-3`}
                    value={String(values[field.name])}
                    required={field.required}
                    onChange={(e) => setValues((v) => ({ ...v, [field.name]: e.target.value }))}
                  />
                ) : (
                  <input
                    type={field.type ?? "text"}
                    className={field.type === "checkbox" ? "ms-3 accent-violet" : hrInput}
                    value={field.type === "checkbox" ? undefined : String(values[field.name])}
                    checked={field.type === "checkbox" ? values[field.name] === true : undefined}
                    required={field.required}
                    min={field.type === "number" ? 0 : undefined}
                    step={field.type === "number" ? 1 : undefined}
                    onChange={(e) =>
                      setValues((v) => ({
                        ...v,
                        [field.name]: field.type === "checkbox" ? e.target.checked : e.target.value,
                      }))
                    }
                  />
                )}
              </FieldContainer>
            );
          })}
        </fieldset>
        {fileError && (
          <p role="alert" className="text-sm text-danger">
            {fileError}
          </p>
        )}
        {action.financial && (
          <p className="rounded-control bg-violet-soft/50 p-3 text-xs leading-6 text-ink-soft">
            الاعتماد والصرف يتطلبان اتصالاً بالسيرفر وتحققاً من الصلاحيات والرصيد.
          </p>
        )}
        {action.notice && (
          <p className="rounded-control bg-violet-soft/50 p-3 text-xs leading-6 text-ink-soft">
            {action.notice}
          </p>
        )}
        {save.error && (
          <p role="alert" className="text-sm text-danger">
            {toFinoraError(save.error).message}
          </p>
        )}
        <footer className="flex justify-end gap-2 border-t border-line pt-4">
          <button type="button" className={hrSecondary} disabled={save.isPending} onClick={onClose}>
            إلغاء
          </button>
          <button
            className={hrPrimary}
            disabled={save.isPending || ((action.financial || action.onlineOnly) && !online)}
          >
            {save.isPending ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}حفظ
          </button>
        </footer>
      </form>
    </SupplierModal>
  );
}

export function EmployeeEditor({
  employee,
  lookups,
  onClose,
  onSaved,
}: {
  employee: HRPerson | null;
  lookups: HRLookups;
  onClose(): void;
  onSaved(id: number, pending?: boolean): void;
}) {
  const [fields, setFields] = useState(() => ({
    name: employee?.name ?? "",
    code: employee?.code ?? "",
    phone: employee?.phone ?? "",
    phone2: employee?.phone2 ?? "",
    email: employee?.email ?? "",
    address: employee?.address ?? "",
    emergency_name: employee?.emergency_name ?? "",
    emergency_phone: employee?.emergency_phone ?? "",
    notes: employee?.notes ?? "",
    job_title: employee?.job_title ?? "",
    branch_id: String(employee?.branch_id ?? lookups.branches[0]?.id ?? ""),
    department_id: String(employee?.department_id ?? ""),
    manager_id: String(employee?.manager_id ?? ""),
    joined_on: employee?.joined_on ?? hrToday(),
    contract_type: employee?.contract_type ?? "full_time",
    contract_end: employee?.contract_end ?? "",
    salary_type: employee?.salary_type ?? "monthly",
    effective_from: hrToday(),
  }));
  const [salary, setSalary] = useState(employee?.salary ?? 0);
  const [payRules, setPayRules] = useState({
    overtime_hourly_bonus: employee?.overtime_hourly_bonus ?? 0,
    late_minute_penalty: employee?.late_minute_penalty ?? 0,
    absence_daily_penalty: employee?.absence_daily_penalty ?? 0,
  });
  const finance =
    employee?.status !== "terminated" &&
    lookups.permissions.includes("hr.payroll.prepare") &&
    (!employee || employee.salary !== undefined);
  const online = useConnection((s) => s.status === "online");
  const [managerSearch, setManagerSearch] = useState("");
  const managerTerm = useDebouncedValue(managerSearch, 250);
  const managers = useQuery({
    queryKey: ["hr", "managers", fields.branch_id, managerTerm],
    queryFn: () =>
      finora.hr.list({
        search: managerTerm,
        branch_id: fields.branch_id,
        department_id: "",
        status: "active",
        sort: "name",
        page: 1,
        page_size: 25,
      }),
  });
  const save = useHRCommand(onSaved);
  const patch = (key: keyof typeof fields, value: string) => setFields((v) => ({ ...v, [key]: value }));
  const field = (key: keyof typeof fields, label: string, type = "text", required = false) => (
    <label className="block space-y-2 text-xs text-ink-soft">
      <span>{label}</span>
      <input
        className={hrInput}
        type={type}
        value={fields[key]}
        disabled={
          (key === "contract_end" && (!online || !finance)) ||
          (key === "joined_on" && !!employee && (!online || !finance))
        }
        required={required}
        maxLength={key === "name" ? 150 : key === "phone" || key === "phone2" ? 30 : 255}
        onChange={(e) => patch(key, e.target.value)}
      />
    </label>
  );
  return (
    <SupplierModal
      title={employee ? "تعديل الموظف" : "إضافة موظف"}
      placement="right"
      busy={save.isPending}
      onClose={onClose}
    >
      <form
        className="space-y-5"
        onSubmit={(event) => {
          event.preventDefault();
          const { salary_type, effective_from, ...profile } = fields;
          const payload: Record<string, unknown> = {
            ...profile,
            branch_id: Number(fields.branch_id),
            department_id: fields.department_id ? Number(fields.department_id) : null,
            manager_id: fields.manager_id ? Number(fields.manager_id) : null,
          };
          if (!fields.code && !employee) delete payload.code;
          if (finance && online)
            Object.assign(payload, {
              salary,
              ...payRules,
              salary_type,
              effective_from: employee ? effective_from : fields.joined_on,
            });
          if (employee) Object.assign(payload, { person_id: employee.id, version: employee.version });
          if (!finance) {
            delete payload.contract_type;
            delete payload.contract_end;
            if (employee) delete payload.joined_on;
          }
          if (!online) {
            delete payload.contract_type;
            delete payload.contract_end;
            delete payload.manager_id;
            if (employee) {
              delete payload.branch_id;
              delete payload.joined_on;
            }
          }
          save.mutate({ action: employee ? "employee.update" : "employee.create", payload });
        }}
      >
        <fieldset disabled={save.isPending} className="space-y-5">
          <section>
            <h3 className="mb-4 text-sm font-semibold">المعلومات الشخصية</h3>
            <div className="grid grid-cols-2 gap-4">
              {field("name", "الاسم الكامل", "text", true)}
              {field("code", "الرقم الوظيفي (تلقائي عند تركه فارغاً)")}
              {field("phone", "الهاتف", "tel")}
              {field("phone2", "هاتف إضافي", "tel")}
              {field("email", "البريد الإلكتروني", "email")}
              {field("address", "العنوان")}
              {field("emergency_name", "اسم جهة اتصال الطوارئ")}
              {field("emergency_phone", "هاتف الطوارئ", "tel")}
            </div>
          </section>
          <section className="border-t border-line pt-4">
            <h3 className="mb-4 text-sm font-semibold">المعلومات الوظيفية</h3>
            <div className="grid grid-cols-2 gap-4">
              <label className="space-y-2 text-xs text-ink-soft">
                <span>الفرع</span>
                <select
                  className={hrInput}
                  required
                  value={fields.branch_id}
                  disabled={!online && !!employee}
                  onChange={(e) => {
                    patch("branch_id", e.target.value);
                    patch("department_id", "");
                  }}
                >
                  {lookups.branches.map((b) => (
                    <option key={b.id} value={b.id}>
                      {b.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="space-y-2 text-xs text-ink-soft">
                <span>القسم</span>
                <select
                  className={hrInput}
                  value={fields.department_id}
                  onChange={(e) => patch("department_id", e.target.value)}
                >
                  <option value="">بدون قسم</option>
                  {lookups.departments
                    .filter((d) => !d.branch_id || d.branch_id === Number(fields.branch_id))
                    .map((d) => (
                      <option key={d.id} value={d.id}>
                        {d.name}
                      </option>
                    ))}
                </select>
              </label>
              {field("job_title", "الوظيفة")}
              <label className="space-y-2 text-xs text-ink-soft">
                <span>المدير المباشر</span>
                <input
                  aria-label="ابحث عن المدير"
                  placeholder="ابحث باسم المدير..."
                  className={hrInput}
                  value={managerSearch}
                  disabled={!online}
                  onChange={(e) => setManagerSearch(e.target.value)}
                />
                <select
                  aria-label="المدير المباشر"
                  className={hrInput}
                  value={fields.manager_id}
                  disabled={!online}
                  onChange={(e) => patch("manager_id", e.target.value)}
                >
                  <option value="">بدون مدير</option>
                  {fields.manager_id &&
                    !managers.data?.rows.some((p) => p.id === Number(fields.manager_id)) && (
                      <option value={fields.manager_id}>المدير الحالي #{fields.manager_id}</option>
                    )}
                  {managers.data?.rows
                    .filter((p) => p.id !== employee?.id)
                    .map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name} · {p.code}
                      </option>
                    ))}
                </select>
                {managers.error && <span className="text-danger">تعذر تحميل المديرين؛ أعد البحث</span>}
              </label>
              {field("joined_on", "تاريخ التعيين", "date", true)}
              <label className="space-y-2 text-xs text-ink-soft">
                <span>نوع العقد</span>
                <select
                  className={hrInput}
                  value={fields.contract_type}
                  disabled={!online || !finance}
                  onChange={(e) => patch("contract_type", e.target.value)}
                >
                  {["full_time", "part_time", "temporary"].map((s) => (
                    <option key={s} value={s}>
                      {labels[s]}
                    </option>
                  ))}
                </select>
              </label>
              {field("contract_end", "انتهاء العقد", "date")}
            </div>
          </section>
          {finance && online && (
            <section className="border-t border-line pt-4">
              <h3 className="mb-4 text-sm font-semibold">بيانات الأجر</h3>
              <div className="grid grid-cols-2 gap-4">
                <label className="space-y-2 text-xs text-ink-soft">
                  <span>نوع الأجر</span>
                  <select
                    className={hrInput}
                    value={fields.salary_type}
                    onChange={(e) => patch("salary_type", e.target.value)}
                  >
                    {["monthly", "weekly", "daily", "hourly", "commission", "monthly_commission"].map((s) => (
                      <option key={s} value={s}>
                        {labels[s]}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="space-y-2 text-xs text-ink-soft">
                  <span>الأجر الأساسي (د.ع)</span>
                  <MoneyInput label="الأجر الأساسي" value={salary} onChange={setSalary} className={hrInput} />
                </label>
                {employee && field("effective_from", "تاريخ سريان التعديل المالي", "date", true)}
                {(
                  [
                    ["overtime_hourly_bonus", "بدل الساعة الإضافية فوق الأجر"],
                    ["late_minute_penalty", "جزاء دقيقة التأخير"],
                    ["absence_daily_penalty", "حسم يوم الغياب للأجر الشهري أو الأسبوعي"],
                  ] as const
                ).map(([key, label]) => (
                  <label key={key} className="space-y-2 text-xs text-ink-soft">
                    <span>{label} (د.ع)</span>
                    <MoneyInput
                      label={label}
                      value={payRules[key]}
                      onChange={(value) => setPayRules((old) => ({ ...old, [key]: value }))}
                      className={hrInput}
                    />
                  </label>
                ))}
              </div>
            </section>
          )}
          <label className="block space-y-2 text-xs text-ink-soft">
            <span>ملاحظات</span>
            <textarea
              className={`${hrInput} h-20 py-2`}
              value={fields.notes}
              maxLength={1000}
              onChange={(e) => patch("notes", e.target.value)}
            />
          </label>
          {!employee && (
            <p className="rounded-control bg-violet-soft/40 px-3 py-2 text-xs leading-6 text-ink-soft">
              يُنشأ ملف وظيفي مستقل. ربط حساب FINORA يتم من الملف الوظيفي بصلاحية إدارة الموارد.
            </p>
          )}
        </fieldset>
        {save.error && (
          <p role="alert" className="text-sm text-danger">
            {toFinoraError(save.error).message}
          </p>
        )}
        <footer className="flex justify-end gap-2">
          <button type="button" onClick={onClose} disabled={save.isPending} className={hrSecondary}>
            إلغاء
          </button>
          {!online && (
            <p className="text-xs leading-6 text-ink-faint">
              تُحفظ البيانات الشخصية كطلب محلي للمزامنة. بيانات الأجر والعقد تحتاج اتصالاً بالسيرفر.
            </p>
          )}
          <button className={hrPrimary} disabled={save.isPending}>
            {save.isPending && <Loader2 size={16} className="animate-spin" />}حفظ الموظف
          </button>
        </footer>
      </form>
    </SupplierModal>
  );
}
