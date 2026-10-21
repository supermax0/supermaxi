import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Bot, CheckCircle2, Copy, RefreshCw, ShieldCheck } from "lucide-react";
import {
  DEFAULT_LOCAL_ASSISTANT,
  localAssistantSettingsSchema,
  type LocalAssistantSettings,
} from "@shared/localAssistant";
import { desktopBridge } from "@/services/bridge";
import { toast } from "@/stores/toasts";
import { cancelAssistant } from "@/features/assistant/engine";
import { useAssistant } from "@/features/assistant/state";
import { SectionCard, SettingRow, Switch } from "./primitives";

const input =
  "h-10 w-full rounded-control border border-line bg-white px-3 text-sm text-ink outline-none focus:border-violet";
const errorText = (error: unknown) => (error instanceof Error ? error.message : "تعذر إكمال الإعداد");
export function AssistantSettingsSection() {
  const bridge = desktopBridge().assistant;
  const query = useQuery({
    queryKey: ["local-assistant", "settings"],
    queryFn: async () =>
      bridge ? bridge.settings() : { settings: DEFAULT_LOCAL_ASSISTANT, hasToken: false },
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });
  const [draft, setDraft] = useState<LocalAssistantSettings>({ ...DEFAULT_LOCAL_ASSISTANT });
  const [token, setToken] = useState("");
  const [clearToken, setClearToken] = useState(false);
  const [models, setModels] = useState<string[]>([]);
  const savedEndpoint =
    query.data?.settings.provider === draft.provider &&
    query.data?.settings.host === draft.host &&
    query.data?.settings.port === draft.port;
  useEffect(() => {
    if (query.data) setDraft(query.data.settings);
  }, [query.data]);
  const patch = (value: Partial<LocalAssistantSettings>) => setDraft((s) => ({ ...s, ...value }));
  const probe = useMutation({
    mutationKey: ["workspace", "assistant-read"],
    mutationFn: async () => {
      if (!bridge) throw Error("حدّث نسخة الدسكتوب لتفعيل الربط المحلي");
      const result = await bridge.probe({
        settings: localAssistantSettingsSchema.parse(draft),
        ...(token ? { token } : {}),
      });
      setModels(result.models);
      if (!draft.model && result.models[0]) patch({ model: result.models[0] });
      return result;
    },
  });
  const save = useMutation({
    mutationKey: ["workspace", "assistant-read"],
    mutationFn: async () => {
      if (!bridge) throw Error("حدّث نسخة الدسكتوب لتفعيل الربط المحلي");
      const parsed = localAssistantSettingsSchema.parse(draft);
      if (parsed.enabled && !parsed.model) throw Error("اختر النموذج المثبّت أو اكتب معرّفه الصحيح");
      await cancelAssistant();
      return bridge.configure({ settings: parsed, ...(token ? { token } : {}), clearToken });
    },
    onSuccess: (data) => {
      useAssistant.setState({ settings: data.settings, hasToken: data.hasToken });
      setToken("");
      setClearToken(false);
      void query.refetch();
      toast.success("تم حفظ إعدادات المساعد المحلي");
    },
  });
  const trial = useMutation({
    mutationKey: ["workspace", "assistant-read"],
    mutationFn: async () => {
      if (!bridge) throw Error("الربط غير متاح");
      const response = await bridge.chat({
        messages: [{ role: "user", content: "اختبار ربط فقط: أجب بكلمة جاهز." }],
        tools: [],
      });
      if (!response.message.content.trim()) throw Error("لم يرجع النموذج نصاً. تحقق من تحميله وإعداداته.");
      return response;
    },
  });
  const copy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      toast.success("تم النسخ");
    } catch {
      toast.error("تعذر النسخ؛ النص معروض للنسخ اليدوي");
    }
  };
  const busy = save.isPending || probe.isPending || trial.isPending;
  return (
    <div className="space-y-4" data-nontransactional>
      <SectionCard title="مساعد فينورا المحلي" icon={Bot}>
        <SettingRow
          title="تفعيل النموذج المحلي"
          hint="التعليم والدليل متاحان دائماً. الأسئلة المفتوحة تعمل بالنموذج الذي تشغله على جهازك أو شبكتك الداخلية."
        >
          <Switch
            label="تفعيل المساعد المحلي"
            checked={draft.enabled}
            disabled={busy || !bridge}
            onChange={(enabled) => patch({ enabled })}
          />
        </SettingRow>
        {query.isError && (
          <p role="alert" className="text-sm text-danger">
            {errorText(query.error)} — يمكنك إعادة حفظ الإعدادات أدناه.
          </p>
        )}
        <div className="mt-3 grid grid-cols-2 gap-3">
          <label className="text-xs">
            الخدمة
            <select
              aria-label="خدمة الذكاء المحلي"
              className={input}
              value={draft.provider}
              disabled={busy}
              onChange={(e) => {
                patch({
                  provider: e.target.value as LocalAssistantSettings["provider"],
                  port: e.target.value === "ollama" ? 11434 : 1234,
                  model: "",
                });
                setModels([]);
                setToken("");
              }}
            >
              <option value="ollama">Ollama</option>
              <option value="lmstudio">LM Studio</option>
            </select>
          </label>
          <label className="text-xs">
            المنفذ
            <input
              aria-label="منفذ الذكاء المحلي"
              className={input}
              type="number"
              min={1024}
              max={65535}
              value={draft.port}
              onChange={(e) => patch({ port: Number(e.target.value) })}
            />
          </label>
          <label className="col-span-2 text-xs">
            عنوان جهاز الخدمة
            <input
              aria-label="عنوان الذكاء المحلي"
              className={`${input} ltr-isolate`}
              value={draft.host}
              maxLength={30}
              onChange={(e) => patch({ host: e.target.value })}
            />
            <small className="text-ink-faint">
              127.0.0.1 للجهاز نفسه، أو IPv4 خاص لجهاز داخل الشبكة. عنوان الخدمة الحالية: {draft.host}:
              {draft.port}
            </small>
          </label>
          <label className="col-span-2 text-xs">
            النموذج
            <input
              aria-label="معرف النموذج المحلي"
              list="finora-local-models"
              className={`${input} ltr-isolate`}
              value={draft.model}
              maxLength={200}
              onChange={(e) => patch({ model: e.target.value })}
            />
            <datalist id="finora-local-models">
              {models.map((m) => (
                <option key={m} value={m} />
              ))}
            </datalist>
          </label>
          <label className="col-span-2 text-xs">
            رمز وصول الخدمة المحلية — اختياري
            <input
              aria-label="رمز وصول الخدمة المحلية"
              type="password"
              autoComplete="off"
              className={input}
              value={token}
              maxLength={512}
              placeholder={
                savedEndpoint && query.data?.hasToken
                  ? "رمز محفوظ مشفّراً؛ اتركه فارغاً للاحتفاظ به"
                  : "فقط إذا فعّلت التوثيق في الخدمة المحلية"
              }
              onChange={(e) => setToken(e.target.value)}
            />
          </label>
          {(query.isError || (savedEndpoint && query.data?.hasToken)) && (
            <label className="col-span-2 flex items-center gap-2 text-xs">
              <input type="checkbox" checked={clearToken} onChange={(e) => setClearToken(e.target.checked)} />
              حذف رمز الوصول المحفوظ لهذا العنوان
            </label>
          )}
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            type="button"
            className="workspace-button"
            disabled={busy || !bridge}
            onClick={() => probe.mutate()}
          >
            <RefreshCw size={15} />
            {probe.isPending ? "أفحص الخدمة…" : "فحص الاتصال وجلب النماذج"}
          </button>
          <button
            type="button"
            className="workspace-button"
            disabled={busy || !query.data?.settings.enabled || !query.data.settings.model}
            onClick={() => trial.mutate()}
          >
            اختبار استجابة النموذج المحفوظ
          </button>
        </div>
        {probe.isSuccess && (
          <p role="status" className="mt-2 text-xs text-success">
            الخدمة متاحة · {probe.data.models.length} نموذج محلي.{" "}
            {probe.data.models.length
              ? "اختر النموذج ثم احفظ الإعدادات."
              : "حمّل نموذجاً داخل الخدمة ثم أعد الفحص."}
          </p>
        )}
        {trial.isSuccess && (
          <p role="status" className="mt-2 text-xs text-success">
            استجاب النموذج المحلي خلال {Math.round(trial.data.durationMs / 1000)} ثانية.
          </p>
        )}
        {[probe.error, trial.error, save.error].filter(Boolean).map((e, i) => (
          <p key={i} role="alert" className="mt-2 text-xs text-danger">
            {errorText(e)}
          </p>
        ))}
      </SectionCard>
      <SectionCard title="قدرات النموذج والذاكرة" icon={ShieldCheck}>
        <SettingRow
          title="استخدام أدوات فينورا"
          hint="قراءة بيانات مصرح بها، وإظهار مصادر النتائج، وتجهيز مقترحات للمراجعة. يتطلب نموذجاً يدعم الأدوات وصلاحية المساعد بالشركة."
        >
          <Switch label="أدوات المساعد المحلي" checked={draft.tools} onChange={(tools) => patch({ tools })} />
        </SettingRow>
        <SettingRow title="قراءة الصور" hint="فعّلها لنموذج رؤية محلي فقط. الصور تُرسل للخدمة المحددة أعلاه.">
          <Switch label="دعم صور المساعد" checked={draft.vision} onChange={(vision) => patch({ vision })} />
        </SettingRow>
        <SettingRow
          title="مساعد الخادم عند تعذر النموذج المحلي"
          hint="إذا كان النموذج المحلي متوقفاً أو غير متصل يُرسل السؤال النصي لمساعد فينورا على الخادم، بنفس صلاحياتك، ويعمل فقط إذا فعّله مدير الشركة. قد يستخدم الخادم مزوّد ذكاء خارجياً حسب إعدادات الشركة. الصور لا تُرسل."
        >
          <Switch
            label="استخدام مساعد الخادم احتياطياً"
            checked={draft.serverFallback}
            onChange={(serverFallback) => patch({ serverFallback })}
          />
        </SettingRow>
        <SettingRow
          title="حفظ المحادثة على هذا الجهاز"
          hint="تُحفظ مشفّرة، ومعزولة حسب الحساب والشركة والفرع والصلاحيات. الوصول للمحفوظ يحتاج جلسة موثقة. عند إيقافه تبقى المحادثة الحالية بذاكرة التطبيق."
        >
          <Switch
            label="حفظ محادثة المساعد"
            checked={draft.remember}
            onChange={(remember) => patch({ remember })}
          />
        </SettingRow>
        <div className="mt-3 grid grid-cols-2 gap-3 text-xs">
          <label>
            سياق النموذج
            <select
              aria-label="سياق النموذج المحلي"
              className={input}
              value={draft.contextTokens}
              onChange={(e) => patch({ contextTokens: Number(e.target.value) })}
            >
              {[2048, 4096, 8192, 16384, 32768].map((v) => (
                <option key={v} value={v}>
                  {v.toLocaleString("en")}
                </option>
              ))}
            </select>
          </label>
          <label>
            المهلة بالثواني
            <input
              aria-label="مهلة النموذج المحلي"
              className={input}
              type="number"
              min={30}
              max={300}
              value={draft.timeoutSeconds}
              onChange={(e) => patch({ timeoutSeconds: Number(e.target.value) })}
            />
          </label>
          <label>
            أقصى جولات الأدوات
            <input
              aria-label="جولات أدوات المساعد"
              className={input}
              type="number"
              min={1}
              max={8}
              value={draft.maxRounds}
              onChange={(e) => patch({ maxRounds: Number(e.target.value) })}
            />
          </label>
        </div>
        <label className="mt-3 block text-xs">
          تعليمات أسلوب المساعد
          <textarea
            aria-label="تعليمات المساعد المحلي"
            className={`${input} mt-1 h-28 py-2`}
            value={draft.instructions}
            maxLength={6000}
            placeholder="مثال: جاوب باللهجة العراقية، وضّح مصدر الأرقام، واختصر إلا إذا طلبت شرحاً."
            onChange={(e) => patch({ instructions: e.target.value })}
          />
        </label>
        <p className="mt-1 text-xs text-ink-faint">
          هذه تفضيلات للشرح؛ صلاحيات فينورا وحواجز الحفظ والمراجعة يفرضها النظام.
        </p>
      </SectionCard>
      <SectionCard title="التفعيل خطوة بخطوة" icon={CheckCircle2}>
        <ol className="list-inside list-decimal space-y-2 text-sm leading-7">
          {draft.provider === "ollama" ? (
            <>
              <li>
                نزّل Ollama على جهاز يدعمه من <code dir="ltr">ollama.com/download</code> ثم شغّله.
              </li>
              <li>
                نزّل نموذج Instruct محلياً يدعم العربية والأدوات، واختر حجماً يناسب ذاكرة جهازك. نماذج الصور
                تحتاج دعم رؤية أيضاً.
              </li>
              <li>
                تأكد من ظهور نماذجك بأمر <code dir="ltr">ollama list</code>. لتشغيل الخدمة عند الحاجة استخدم{" "}
                <code dir="ltr">ollama serve</code>.
              </li>
            </>
          ) : (
            <>
              <li>
                نزّل LM Studio على جهاز يدعمه من <code dir="ltr">lmstudio.ai</code>، ثم نزّل نموذجاً مناسباً
                وحمّله.
              </li>
              <li>افتح Developer، وشغّل Local Server على المنفذ 1234 أو منفذك المختار.</li>
              <li>
                استخدم معرّف النموذج الظاهر في الخادم. إذا فعّلت Authentication، أدخل رمزه في حقل رمز الوصول.
              </li>
            </>
          )}
          <li>
            اختر الخدمة والعنوان والمنفذ في فينورا، واضغط فحص الاتصال، ثم اختر النموذج وفعّل المساعد واحفظ.
          </li>
          <li>
            اختبر استجابة النموذج. إذا فشلت الأدوات أو الصور، تحقق أن النموذج يدعمها. سياق 8192 نقطة بداية
            مناسبة للبحث؛ النماذج الأثقل تحتاج ذاكرة أكبر.
          </li>
          <li>
            للأجهزة القديمة يمكن تشغيل النموذج على جهاز متوافق داخل الشبكة، وتفعيل وصول الشبكة في الخدمة
            واستخدام عنوانه الداخلي هنا.
          </li>
        </ol>
        <button
          type="button"
          className="workspace-button mt-3"
          onClick={() =>
            void copy(
              draft.provider === "ollama" ? "ollama list\nollama serve" : "lms server start --port 1234",
            )
          }
        >
          <Copy size={14} />
          نسخ أوامر الفحص والتشغيل
        </button>
      </SectionCard>
      <SectionCard title="الإملاء الصوتي المحلي — اختياري" icon={Bot}>
        <SettingRow
          title="التفريغ الصوتي المحلي"
          hint="يستخدم whisper.cpp server داخل جهاز الخدمة؛ تسجيل الصوت وحده لا يرسل أو يحفظ عملية مالية."
        >
          <Switch
            label="تفعيل صوت المساعد المحلي"
            checked={draft.speech}
            onChange={(speech) => patch({ speech })}
          />
        </SettingRow>
        <label className="mt-2 block text-xs">
          منفذ whisper.cpp
          <input
            aria-label="منفذ تفريغ الصوت"
            className={input}
            type="number"
            min={1024}
            max={65535}
            value={draft.speechPort}
            onChange={(e) => patch({ speechPort: Number(e.target.value) })}
          />
        </label>
        <p className="mt-2 text-xs leading-6 text-ink-soft">
          شغّل whisper.cpp server مع نموذج متعدد اللغات وواجهة /inference. مثال بعد تنزيله ونموذجه:{" "}
          <code dir="ltr">whisper-server -m models/ggml-small.bin -l ar --host 127.0.0.1 --port 8080</code>.
          للتشغيل على الشبكة استخدم عنوان الخدمة الخاص واضبط وصول الشبكة. فينورا يحوّل التسجيل إلى WAV محلياً
          قبل التفريغ.
        </p>
      </SectionCard>
      <button
        type="button"
        className="workspace-button workspace-primary w-full"
        disabled={busy || !bridge}
        onClick={() => save.mutate()}
      >
        {save.isPending ? "جارٍ حفظ الإعدادات…" : "حفظ إعدادات المساعد المحلي"}
      </button>
    </div>
  );
}
