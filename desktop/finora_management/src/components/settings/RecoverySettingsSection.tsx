import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ArchiveRestore, Download } from "lucide-react";
import { desktopBridge, hasDesktopBridge } from "@/services/bridge";
import { SectionCard } from "./primitives";

export function RecoverySettingsSection() {
  const client = useQueryClient();
  const [password, setPassword] = useState(""),
    [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState(false),
    [message, setMessage] = useState("");
  const backup = hasDesktopBridge() ? desktopBridge().backup : undefined;
  const run = async (action: "export" | "restore") => {
    if (!backup) return;
    setBusy(true);
    setMessage("");
    try {
      if (action === "export") {
        const result = await backup.export(password);
        setMessage(
          result.saved ? "حُفظت النسخة المشفّرة. احتفظ بكلمة مرورها في مكان آمن." : "أُلغي حفظ النسخة.",
        );
      } else {
        const result = await backup.restore(password);
        if (result.restored) {
          client.clear();
          await client.invalidateQueries();
        }
        setMessage(
          result.restored
            ? "استُعيدت النسخة. افتح المزامنة لمراجعة العمليات وحصة المخزون قبل العمل دون اتصال."
            : "أُلغيت الاستعادة.",
        );
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "تعذّرت العملية؛ لم تُحذف بياناتك.");
    } finally {
      setPassword("");
      setConfirmation("");
      setBusy(false);
    }
  };
  return (
    <SectionCard title="النسخ الاحتياطي المحلي" icon={ArchiveRestore}>
      <div className="space-y-4 py-4 text-sm">
        <p className="leading-6 text-ink-soft">
          نسخة مشفّرة لبيانات الأوفلاين والعمليات المحفوظة للحساب والفرع الحاليين. تحتاج الاستعادة اتصالاً
          للتحقق من الصلاحيات، وتبقى ملفات الجهاز القديمة محفوظة. هذه النسخة لا تشمل قاعدة بيانات السيرفر.
        </p>
        <label className="block">
          كلمة مرور النسخة (12 حرفاً على الأقل)
          <input
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            disabled={busy}
            className="mt-2 w-full rounded-control border border-line p-3"
          />
        </label>
        <label className="block">
          تأكيد كلمة المرور
          <input
            type="password"
            autoComplete="new-password"
            value={confirmation}
            onChange={(e) => setConfirmation(e.target.value)}
            disabled={busy}
            className="mt-2 w-full rounded-control border border-line p-3"
          />
        </label>
        <p className="text-xs text-ink-soft">لا تُحفظ كلمة المرور داخل التطبيق. فقدانها يمنع فتح النسخة.</p>
        <div className="flex flex-wrap gap-3">
          {(
            [
              ["export", "حفظ نسخة مشفّرة"],
              ["restore", "استعادة نسخة"],
            ] as const
          ).map(([action, label]) => (
            <button
              key={action}
              type="button"
              onClick={() => void run(action)}
              disabled={!backup || busy || password.length < 12 || password !== confirmation}
              className="rounded-control bg-violet px-4 py-3 font-semibold text-white disabled:opacity-40"
            >
              {busy ? "جارٍ التنفيذ…" : label}
            </button>
          ))}
        </div>
        <p role="status" className="break-words text-sm text-ink-soft">
          {message}
        </p>
      </div>
    </SectionCard>
  );
}

export function UpdateSettingsSection() {
  const [info, setInfo] = useState<Awaited<
    ReturnType<NonNullable<ReturnType<typeof desktopBridge>["updates"]>["check"]>
  > | null>(null);
  const [ready, setReady] = useState(false),
    [busy, setBusy] = useState(false),
    [message, setMessage] = useState("");
  const updates = hasDesktopBridge() ? desktopBridge().updates : undefined;
  const run = async (action: "check" | "download" | "install") => {
    if (!updates) return;
    setBusy(true);
    setMessage("");
    try {
      if (action === "check") {
        setReady(false);
        const value = await updates.check();
        setInfo(value);
        setMessage(value.available ? "يتوفر إصدار جديد." : "أنت تستخدم أحدث إصدار متاح لهذا الجهاز.");
      } else if (action === "download") {
        setReady((await updates.download()).ready);
        setMessage("اكتمل التنزيل والتحقق من سلامة الملف. احفظ عملك ثم ثبّت التحديث.");
      } else await updates.install();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "تعذّر تحديث التطبيق.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <SectionCard title="تحديث FINORA" icon={Download}>
      <div className="space-y-4 py-4 text-sm">
        <p className="text-ink-soft">
          يُنزّل التحديث من خادمك عبر HTTPS ويُتحقق من حجمه وبصمته قبل تشغيل المثبّت.
        </p>
        {info && (
          <p>
            الإصدار الحالي: <b dir="ltr">{info.current}</b> · المتاح: <b dir="ltr">{info.latest}</b>
          </p>
        )}
        <div className="flex flex-wrap gap-3">
          <button
            type="button"
            disabled={!updates || busy}
            onClick={() => void run("check")}
            className="rounded-control border border-line px-4 py-3 disabled:opacity-40"
          >
            فحص التحديثات
          </button>
          {info?.available && !ready && (
            <button
              type="button"
              disabled={busy}
              onClick={() => void run("download")}
              className="rounded-control bg-violet px-4 py-3 text-white disabled:opacity-40"
            >
              تنزيل التحديث ({Math.ceil(info.size / 1048576)} MB)
            </button>
          )}
          {ready && (
            <button
              type="button"
              disabled={busy}
              onClick={() => void run("install")}
              className="rounded-control bg-violet px-4 py-3 text-white disabled:opacity-40"
            >
              إغلاق آمن وتثبيت التحديث
            </button>
          )}
        </div>
        <p role="status" className="break-words text-ink-soft">
          {busy ? "جارٍ التنفيذ…" : message}
        </p>
      </div>
    </SectionCard>
  );
}
