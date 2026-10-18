import { useState } from "react";
import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";
import { toFinoraError } from "@/api/finora";
import type { HRLookups, HRRecruitField, HRRecruitForm } from "@/api/finora/hr";
import { useConnection } from "@/stores/connection";
import { SupplierModal } from "../suppliers/SupplierDialogs";
import { hrInput, hrPrimary, hrSecondary, useHRCommand } from "./shared";

const types = {
  short_text: "نص قصير",
  long_text: "نص طويل",
  number: "رقم",
  phone: "هاتف",
  email: "بريد إلكتروني",
  date: "تاريخ",
  single: "اختيار واحد",
  multiple: "اختيارات متعددة",
  dropdown: "قائمة",
  file: "ملف",
  image: "صورة",
  heading: "عنوان قسم",
  description: "وصف",
  consent: "موافقة",
};
function freshField(): HRRecruitField {
  return {
    key: `field_${crypto.randomUUID().replaceAll("-", "").slice(0, 12)}`,
    type: "short_text",
    label: "",
    description: "",
    required: false,
    options: [],
    max_length: 255,
    max_file_kb: 1024,
    minimum: null,
    maximum: null,
    order: 0,
  };
}
export function RecruitFormBuilder({
  form,
  tools,
  onClose,
}: {
  form: HRRecruitForm | null;
  tools: HRLookups;
  onClose(): void;
}) {
  const online = useConnection((s) => s.status === "online");
  const [title, setTitle] = useState(form?.title ?? "");
  const [description, setDescription] = useState(form?.description ?? "");
  const [branch, setBranch] = useState(String(form?.branch_id ?? tools.branches[0]?.id ?? ""));
  const [fields, setFields] = useState<HRRecruitField[]>(form?.fields ?? [freshField()]);
  const save = useHRCommand(onClose);
  const patch = (index: number, values: Partial<HRRecruitField>) =>
    setFields((current) => current.map((f, i) => (i === index ? { ...f, ...values } : f)));
  const move = (index: number, direction: number) =>
    setFields((current) => {
      const next = [...current],
        target = index + direction;
      const currentField = next[index],
        targetField = next[target];
      if (currentField && targetField) {
        next[index] = targetField;
        next[target] = currentField;
      }
      return next;
    });
  return (
    <SupplierModal
      title={form ? "تعديل استمارة التوظيف" : "إنشاء استمارة توظيف"}
      onClose={onClose}
      busy={save.isPending}
      wide
    >
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate({
            action: "recruitment.form",
            payload: {
              title,
              description,
              branch_id: Number(branch),
              fields,
              ...(form ? { form_id: form.id, version: form.version } : {}),
            },
          });
        }}
      >
        <fieldset disabled={save.isPending || !online} className="space-y-4">
          <label className="block space-y-2 text-xs">
            عنوان الاستمارة
            <input
              className={hrInput}
              value={title}
              required
              maxLength={160}
              onChange={(e) => setTitle(e.target.value)}
            />
          </label>
          <label className="block space-y-2 text-xs">
            الفرع
            <select
              className={hrInput}
              value={branch}
              required
              disabled={!!form}
              onChange={(e) => setBranch(e.target.value)}
            >
              {tools.branches.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                </option>
              ))}
            </select>
          </label>
          <label className="block space-y-2 text-xs">
            وصف الاستمارة
            <textarea
              className={`${hrInput} h-20 py-3`}
              value={description}
              maxLength={2000}
              onChange={(e) => setDescription(e.target.value)}
            />
          </label>
          <p className="text-xs leading-6 text-ink-faint">
            اختَر المعلومات المطلوبة ورتّب الحقول. الروابط السابقة تحتفظ بنسخة الاستمارة المنشورة وقت إنشائها.
          </p>
          {fields.map((field, index) => (
            <section
              key={field.key}
              className="space-y-3 rounded-panel border border-line bg-violet-soft/15 p-4"
            >
              <div className="flex items-center gap-2">
                <strong className="text-xs">الحقل {index + 1}</strong>
                <div className="ms-auto flex gap-2">
                  <button
                    type="button"
                    aria-label={`رفع الحقل ${index + 1}`}
                    disabled={index === 0}
                    onClick={() => move(index, -1)}
                  >
                    <ArrowUp size={15} />
                  </button>
                  <button
                    type="button"
                    aria-label={`خفض الحقل ${index + 1}`}
                    disabled={index === fields.length - 1}
                    onClick={() => move(index, 1)}
                  >
                    <ArrowDown size={15} />
                  </button>
                  <button
                    type="button"
                    aria-label={`حذف الحقل ${index + 1}`}
                    disabled={fields.length === 1}
                    onClick={() => setFields((f) => f.filter((_, i) => i !== index))}
                  >
                    <Trash2 size={15} />
                  </button>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <label className="space-y-2 text-xs">
                  اسم الحقل
                  <input
                    className={hrInput}
                    value={field.label}
                    required
                    maxLength={150}
                    onChange={(e) => patch(index, { label: e.target.value })}
                  />
                </label>
                <label className="space-y-2 text-xs">
                  النوع
                  <select
                    className={hrInput}
                    value={field.type}
                    onChange={(e) => patch(index, { type: e.target.value })}
                  >
                    {Object.entries(types).map(([key, label]) => (
                      <option key={key} value={key}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <label className="block space-y-2 text-xs">
                وصف ومساعدة
                <input
                  className={hrInput}
                  value={field.description}
                  maxLength={1000}
                  onChange={(e) => patch(index, { description: e.target.value })}
                />
              </label>
              <label className="flex gap-2 text-xs">
                <input
                  type="checkbox"
                  checked={field.required}
                  onChange={(e) => patch(index, { required: e.target.checked })}
                />
                إلزامي
              </label>
              {["single", "multiple", "dropdown"].includes(field.type) && (
                <label className="block space-y-2 text-xs">
                  الخيارات، خيار في كل سطر
                  <textarea
                    className={`${hrInput} h-24 py-3`}
                    value={field.options.join("\n")}
                    required
                    onChange={(e) => patch(index, { options: e.target.value.split("\n") })}
                  />
                </label>
              )}
              {["file", "image"].includes(field.type) ? (
                <label className="block space-y-2 text-xs">
                  الحد الأقصى بالكيلوبايت
                  <input
                    className={hrInput}
                    type="number"
                    min={1}
                    max={4096}
                    value={field.max_file_kb}
                    onChange={(e) => patch(index, { max_file_kb: Number(e.target.value) })}
                  />
                </label>
              ) : field.type === "number" ? (
                <div className="grid grid-cols-2 gap-3">
                  {(["minimum", "maximum"] as const).map((key) => (
                    <label key={key} className="space-y-2 text-xs">
                      {key === "minimum" ? "أقل قيمة" : "أعلى قيمة"}
                      <input
                        className={hrInput}
                        type="number"
                        min={0}
                        value={field[key] ?? ""}
                        onChange={(e) =>
                          patch(index, { [key]: e.target.value === "" ? null : Number(e.target.value) })
                        }
                      />
                    </label>
                  ))}
                </div>
              ) : (
                <label className="block space-y-2 text-xs">
                  أقصى طول للنص
                  <input
                    className={hrInput}
                    type="number"
                    min={1}
                    max={4000}
                    value={field.max_length}
                    onChange={(e) => patch(index, { max_length: Number(e.target.value) })}
                  />
                </label>
              )}
            </section>
          ))}
          <button
            type="button"
            className={hrSecondary}
            disabled={fields.length >= 40}
            onClick={() => setFields((f) => [...f, freshField()])}
          >
            <Plus size={15} />
            إضافة حقل
          </button>
        </fieldset>
        {save.error && (
          <p role="alert" className="text-sm text-danger">
            {toFinoraError(save.error).message}
          </p>
        )}
        {!online && <p className="text-xs text-warning">نشر استمارات التوظيف يحتاج اتصالاً بالسيرفر.</p>}
        <div className="flex justify-end gap-2">
          <button type="button" className={hrSecondary} onClick={onClose}>
            إلغاء
          </button>
          <button className={hrPrimary} disabled={!online || save.isPending}>
            حفظ الاستمارة
          </button>
        </div>
      </form>
    </SupplierModal>
  );
}
