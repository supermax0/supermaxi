import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import type { AgentConfig, AgentSettings, ReplyPreview } from "../data/coreSettings";
import type { HttpDataSource } from "../data/http";
import { Badge, ErrorState, FinoraButton, Skeleton, errorText } from "../ui/primitives";
import { TelegramSettings } from "./TelegramSettings";

const AGENT_KEY = ["core-agent-settings"];
const META_KEY = ["core-meta-settings"];

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="integration-field">
      <span>{label}</span>
      {children}
    </label>
  );
}

export type IntegrationSection = "ai" | "replies" | "meta" | "telegram" | "knowledge";

function AgentForm({
  src,
  settings,
  section,
}: {
  src: HttpDataSource;
  settings: AgentSettings;
  section: "ai" | "replies";
}) {
  const qc = useQueryClient();
  const [config, setConfig] = useState(settings.config);
  const [apiKey, setApiKey] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [sample, setSample] = useState("هلا، عندي عيادة أسنان وأريد أعرف شلون فينورا يساعدني؟");
  const [preview, setPreview] = useState<ReplyPreview | null>(null);
  const dirty = JSON.stringify(config) !== JSON.stringify(settings.config);
  const edit = <K extends keyof AgentConfig>(key: K, value: AgentConfig[K]) => {
    setConfig((old) => ({ ...old, [key]: value }));
    setNotice("");
    setPreview(null);
  };
  const run = async (name: string, action: () => Promise<void>) => {
    setBusy(name);
    setError("");
    setNotice("");
    try {
      await action();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy("");
    }
  };
  const save = () =>
    run("save", async () => {
      const result = await src.saveAgentSettings(config);
      await qc.cancelQueries({ queryKey: AGENT_KEY });
      qc.setQueryData(AGENT_KEY, result);
      setConfig(result.config);
      await qc.invalidateQueries({ queryKey: ["status"] });
      setPreview(null);
      setNotice("تم حفظ إعدادات الذكاء والردود");
    });

  return (
    <div className="integration-card">
      <div className="integration-group" hidden={section !== "ai"}>
        <h4>الذكاء الاصطناعي</h4>
        <p className="kill-text">
          اختر النموذج واضبط اتصاله؛ أسلوب الحديث مع العملاء موجود بقسم ردود العملاء.
        </p>
        <Field label="مصدر الذكاء">
          <select
            className="input"
            value={config.provider}
            onChange={(e) => edit("provider", e.target.value as AgentConfig["provider"])}
          >
            <option value="cloud">سحابي — OpenAI</option>
            <option value="local">محلي — Ollama</option>
            <option value="hybrid">محلي أولاً، ثم سحابي عند التعذر</option>
            <option value="off">قواعد آمنة بدون نموذج ذكاء</option>
          </select>
        </Field>
        {(config.provider === "cloud" || config.provider === "hybrid") && (
          <>
            <p className="kill-text">
              مفتاح السحابة: {settings.cloudKeyConfigured ? "مضبوط" : "غير مضبوط"} (
              {settings.cloudKeySource === "core" ? "خاص بـ Core" : "مفتاح الخادم"}). لا يظهر المفتاح بعد
              حفظه.
            </p>
            <Field label="اسم النموذج السحابي">
              <input
                className="input"
                dir="ltr"
                value={config.cloudModel}
                maxLength={120}
                placeholder={settings.resolvedCloudModel}
                onChange={(e) => edit("cloudModel", e.target.value)}
              />
            </Field>
            <p className="kill-text">اترك اسم النموذج فارغاً لاستخدام نموذج الخادم الحالي.</p>
            <details className="integration-details">
              <summary>إضافة أو استبدال مفتاح OpenAI</summary>
              <Field label="مفتاح OpenAI جديد">
                <input
                  className="input"
                  type="password"
                  dir="ltr"
                  autoComplete="new-password"
                  value={apiKey}
                  maxLength={512}
                  placeholder="sk-…"
                  onChange={(e) => setApiKey(e.target.value)}
                />
              </Field>
              <div className="integration-actions">
                <FinoraButton
                  size="sm"
                  disabled={!!busy || !apiKey.trim()}
                  loading={busy === "key"}
                  onClick={() =>
                    void run("key", async () => {
                      const result = await src.saveCloudKey(apiKey.trim());
                      setApiKey("");
                      qc.setQueryData(AGENT_KEY, result);
                      setNotice("تم حفظ المفتاح مشفراً على الخادم");
                    })
                  }
                >
                  حفظ المفتاح
                </FinoraButton>
                <FinoraButton
                  size="sm"
                  variant="ghost"
                  disabled={!!busy || settings.cloudKeySource !== "core"}
                  onClick={() =>
                    void run("key", async () => {
                      qc.setQueryData(AGENT_KEY, await src.saveCloudKey(""));
                      setApiKey("");
                      setNotice("تم اعتماد مفتاح الخادم");
                    })
                  }
                >
                  استخدام مفتاح الخادم
                </FinoraButton>
              </div>
            </details>
          </>
        )}
        {(config.provider === "local" || config.provider === "hybrid") && (
          <>
            <Field label="عنوان Ollama على خادم FINORA">
              <input
                className="input"
                dir="ltr"
                value={config.localUrl}
                maxLength={300}
                onChange={(e) => edit("localUrl", e.target.value)}
              />
            </Field>
            <Field label="اسم النموذج المحلي المثبت">
              <input
                className="input"
                dir="ltr"
                value={config.localModel}
                maxLength={120}
                placeholder="اسم النموذج كما يظهر في Ollama"
                onChange={(e) => edit("localModel", e.target.value)}
              />
            </Field>
            <p className="set-warn">
              المحلي يعمل على جهاز خادم FINORA. إذا التطبيق متصل بـ www.finora.company، فعنوان 127.0.0.1 يشير
              للخادم، وليس حاسوبك. لاختيار نموذج على حاسوبك، اتصل بخادم FINORA يعمل عليه.
            </p>
            {config.provider === "hybrid" && (
              <p className="kill-text">
                بهذا الخيار توافق على إرسال سياق المحادثة إلى OpenAI عند فشل النموذج المحلي.
              </p>
            )}
          </>
        )}
        <Field label="مهلة اتصال النموذج (ثوانٍ)">
          <input
            className="input"
            type="number"
            min={3}
            max={20}
            value={config.timeoutSeconds}
            onChange={(e) => edit("timeoutSeconds", Number(e.target.value))}
          />
        </Field>
      </div>
      <div className="integration-group" hidden={section !== "replies"}>
        <h4>الرد على عملاء فينورا</h4>
        <Field label="طريقة الرد">
          <select
            className="input"
            value={config.replyMode}
            onChange={(e) => edit("replyMode", e.target.value as AgentConfig["replyMode"])}
          >
            <option value="review">اقتراح الرد للموظف — بدون إرسال تلقائي</option>
            <option value="automatic">رد تلقائي</option>
            <option value="manual">رد يدوي فقط</option>
          </select>
        </Field>
        <Field label="لغة الرد">
          <select
            className="input"
            value={config.language}
            onChange={(e) => edit("language", e.target.value as AgentConfig["language"])}
          >
            <option value="auto">حسب لغة العميل</option>
            <option value="ar-iq">عربي عراقي</option>
            <option value="ar">عربي فصيح</option>
            <option value="en">English</option>
          </select>
        </Field>
        <Field label="نبرة الرد">
          <select
            className="input"
            value={config.tone}
            onChange={(e) => edit("tone", e.target.value as AgentConfig["tone"])}
          >
            <option value="friendly">ودود ومهني</option>
            <option value="professional">رسمي ومهني</option>
          </select>
        </Field>
        <Field label="طول الرد">
          <select
            className="input"
            value={config.replyLength}
            onChange={(e) => edit("replyLength", e.target.value as AgentConfig["replyLength"])}
          >
            <option value="short">مختصر — سطران إلى ثلاثة</option>
            <option value="balanced">متوازن — حتى خمسة أسطر</option>
          </select>
        </Field>
        <Field label="أقل ثقة للرد الآلي (%)">
          <input
            className="input"
            type="number"
            min={0}
            max={100}
            value={Math.round(config.minimumConfidence * 100)}
            onChange={(e) => edit("minimumConfidence", Number(e.target.value) / 100)}
          />
        </Field>
        <Field label="تعليمات إضافية لأسلوب الرد">
          <textarea
            className="input"
            rows={4}
            maxLength={2000}
            value={config.instructions}
            onChange={(e) => edit("instructions", e.target.value)}
            placeholder="عرّف بنفسك كمساعد فينورا، اسأل سؤالاً واحداً، وتجنب الضغط على العميل."
          />
        </Field>
        <p className="kill-text">
          الأسعار والمميزات تأتي من معرفة فينورا المنشورة. الشكاوى وطلبات الموظف والمعلومات غير المؤكدة تتحول
          للفريق. إنشاء الحساب والخصومات تبقى بموافقة المسؤول.
        </p>
        <div className="integration-actions">
          <FinoraButton
            size="sm"
            variant="ghost"
            disabled={!!busy}
            onClick={() => {
              setConfig((old) => ({
                ...old,
                replyMode: "review",
                language: "auto",
                tone: "friendly",
                replyLength: "short",
                minimumConfidence: 0.7,
                instructions:
                  "قدّم نفسك كمساعد فينورا. افهم نوع نشاط العميل واسأل سؤالاً واحداً كل مرة. اشرح الفائدة العملية باختصار، واطلب مساعدة الفريق عند غياب معلومة مؤكدة.",
              }));
              setPreview(null);
              setNotice("تم اختيار إعدادات فينورا المقترحة؛ احفظها لتطبيقها");
            }}
          >
            إعدادات فينورا المقترحة
          </FinoraButton>
        </div>
      </div>
      <div className="integration-save">
        {dirty && (
          <p className="set-warn" role="status">
            عندك تغييرات غير محفوظة؛ تبقى أثناء التنقل حتى تغلق الإعدادات. الحفظ يطبّق تغييرات الذكاء والردود
            معاً.
          </p>
        )}
        <div className="integration-actions">
          <FinoraButton
            size="sm"
            variant="primary"
            disabled={!!busy || !dirty}
            loading={busy === "save"}
            onClick={() => void save()}
          >
            {section === "ai" ? "حفظ إعدادات الذكاء" : "حفظ إعدادات الرد"}
          </FinoraButton>
          {section === "ai" && (
            <FinoraButton
              size="sm"
              disabled={!!busy || dirty}
              loading={busy === "test"}
              onClick={() =>
                void run("test", async () => {
                  const result = await src.testAgentProvider();
                  if (!result.ok) setError(result.message);
                  else setNotice(`${result.message} — ${result.model}`);
                })
              }
            >
              اختبار اتصال الذكاء
            </FinoraButton>
          )}
        </div>
      </div>
      <details className="integration-details integration-group" hidden={section !== "replies"}>
        <summary>تجربة الرد قبل الإرسال</summary>
        <p className="kill-text">
          التجربة تستخدم الإعدادات المحفوظة، ولا ترسل رسالة لأي عميل ولا تنفذ إجراءات.
        </p>
        <Field label="رسالة عميل تجريبية">
          <textarea
            className="input"
            rows={3}
            maxLength={2000}
            value={sample}
            onChange={(e) => {
              setSample(e.target.value);
              setPreview(null);
            }}
          />
        </Field>
        <div className="integration-actions">
          <FinoraButton
            size="sm"
            disabled={!!busy || dirty || !sample.trim()}
            loading={busy === "preview"}
            onClick={() =>
              void run("preview", async () => {
                setPreview(null);
                setPreview(await src.previewAgentReply(sample));
              })
            }
          >
            تجربة الرد
          </FinoraButton>
        </div>
        {dirty && <p className="set-warn">عندك تغييرات غير محفوظة؛ احفظها قبل التجربة.</p>}
        {preview && (
          <div className="integration-preview" aria-label="نتيجة تجربة الرد">
            <Badge tone={preview.needsHuman ? "amber" : "green"}>
              {preview.needsHuman ? "يحتاج موظفاً" : "رد مقترح"}
            </Badge>
            <p>{preview.text}</p>
            {!!preview.knowledgeSources?.length && (
              <small>اعتمد على: {preview.knowledgeSources.map((item) => item.title).join("، ")}</small>
            )}
            <small>
              {preview.source === "rules" ? "رد بالقواعد الآمنة" : `النموذج: ${preview.model}`}
              {preview.fallback ? " — لم يُستخدم نموذج الذكاء المختار" : ""}
            </small>
          </div>
        )}
      </details>
      {notice && (
        <p className="integration-notice" role="status">
          {notice}
        </p>
      )}
      {error && (
        <p className="integration-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

function MetaForm({ src }: { src: HttpDataSource }) {
  const qc = useQueryClient();
  const query = useQuery({ queryKey: META_KEY, queryFn: () => src.getMetaSettings() });
  const [appId, setAppId] = useState<string | null>(null);
  const [appSecret, setAppSecret] = useState("");
  const [userToken, setUserToken] = useState("");
  const [verifyToken, setVerifyToken] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const run = async (name: string, action: () => Promise<void>) => {
    setBusy(name);
    setError("");
    setNotice("");
    try {
      await action();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy("");
    }
  };
  return (
    <div className="integration-card">
      <h4>ربط Meta — Instagram وFacebook</h4>
      <p className="kill-text">
        الربط الحالي يستخدم Facebook Login: تطبيق Meta وصفحة Facebook مرتبطة بحساب Instagram احترافي. يتم
        استيراد كل الصفحات المتاحة للرمز؛ استخدم حساباً وصلاحيات مخصصة لصفحات FINORA.
      </p>
      {query.isPending && <Skeleton w="100%" h={60} />}
      {query.isError && <ErrorState error={query.error} onRetry={() => void query.refetch()} />}
      {!query.data?.houseConfigured && !query.isPending && (
        <FinoraButton
          size="sm"
          disabled={!!busy}
          loading={busy === "provision"}
          onClick={() =>
            void run("provision", async () => {
              qc.setQueryData(META_KEY, await src.provisionMetaHouse());
              await qc.invalidateQueries({ queryKey: ["status"] });
              await qc.invalidateQueries({ queryKey: AGENT_KEY });
              setNotice("تم تجهيز حساب FINORA الداخلي");
            })
          }
        >
          تهيئة قنوات FINORA على الخادم
        </FinoraButton>
      )}
      <Field label="Meta App ID">
        <input
          className="input"
          dir="ltr"
          value={appId ?? query.data?.appId ?? ""}
          maxLength={30}
          onChange={(e) => setAppId(e.target.value)}
        />
      </Field>
      <Field label="Meta App Secret">
        <input
          className="input"
          type="password"
          dir="ltr"
          autoComplete="new-password"
          value={appSecret}
          maxLength={32}
          placeholder={
            query.data?.secretConfigured ? "محفوظ؛ اتركه فارغاً للاحتفاظ به" : "أدخل سر تطبيق Meta"
          }
          onChange={(e) => setAppSecret(e.target.value)}
        />
      </Field>
      <Field label="Meta User Access Token">
        <input
          className="input"
          type="password"
          dir="ltr"
          autoComplete="new-password"
          value={userToken}
          maxLength={8192}
          onChange={(e) => setUserToken(e.target.value)}
        />
      </Field>
      <p className="kill-text">
        الرمز يحتاج صلاحيات الصفحات والرسائل: pages_show_list، pages_manage_metadata، pages_messaging،
        instagram_basic وinstagram_manage_messages. الوصول للعملاء الفعليين يعتمد على مراجعة التطبيق
        والصلاحيات في Meta.
      </p>
      <div className="integration-actions">
        <FinoraButton
          size="sm"
          variant="primary"
          disabled={
            !!busy || !query.data?.houseConfigured || !userToken.trim() || !(appId ?? query.data.appId)
          }
          loading={busy === "connect"}
          onClick={() =>
            void run("connect", async () => {
              try {
                const result = await src.connectMeta({
                  appId: appId ?? query.data?.appId ?? "",
                  appSecret,
                  userToken,
                });
                setNotice(
                  `${result.message} — الصفحات: ${result.pagesFound}${result.warningsCount ? `، تنبيهات: ${result.warningsCount}` : ""}`,
                );
                setVerifyToken("");
                await qc.invalidateQueries({ queryKey: META_KEY });
                await qc.invalidateQueries({ queryKey: ["status"] });
              } finally {
                setUserToken("");
                setAppSecret("");
              }
            })
          }
        >
          ربط ومزامنة الصفحات
        </FinoraButton>
        <FinoraButton
          size="sm"
          disabled={!!busy || !query.data?.houseConfigured}
          loading={busy === "health"}
          onClick={() =>
            void run("health", async () => {
              await src.checkMetaHealth();
              await qc.invalidateQueries({ queryKey: META_KEY });
              await qc.invalidateQueries({ queryKey: ["status"] });
              setNotice("تم تحديث حالة القنوات");
            })
          }
        >
          فحص صحة القنوات
        </FinoraButton>
      </div>
      {query.data?.channels.map((c) => (
        <div className="integration-channel" key={`${c.type}:${c.accountId}`}>
          <span>
            {c.name}
            <small dir="ltr">
              {c.type} · {c.accountId}
            </small>
          </span>
          <Badge tone={c.status === "connected" ? "green" : "amber"}>{c.status}</Badge>
        </div>
      ))}
      {query.data?.webhookUrl && (
        <>
          <Field label="رابط Webhook — Callback URL">
            <input className="input" dir="ltr" readOnly value={query.data.webhookUrl} />
          </Field>
          <p className="kill-text">
            استخدم رابط HTTPS عاماً في إعدادات Webhooks داخل Meta. يتم تسجيل الاشتراكات أثناء الربط.
          </p>
          <FinoraButton
            size="sm"
            variant="ghost"
            disabled={!!busy}
            onClick={() =>
              void run("verify", async () => {
                if (verifyToken) setVerifyToken("");
                else setVerifyToken((await src.getMetaVerification()).verifyToken);
              })
            }
          >
            {verifyToken ? "إخفاء رمز التحقق" : "عرض Verify Token لإعداد Webhook"}
          </FinoraButton>
          {verifyToken && (
            <Field label="Verify Token">
              <input className="input" dir="ltr" readOnly value={verifyToken} />
            </Field>
          )}
        </>
      )}
      {notice && (
        <p className="integration-notice" role="status">
          {notice}
        </p>
      )}
      {error && (
        <p className="integration-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

function KnowledgePanel({ src }: { src: HttpDataSource }) {
  const [text, setText] = useState("");
  const [search, setSearch] = useState("");
  const [businessType, setBusinessType] = useState("");
  const query = useQuery({
    queryKey: ["core-knowledge", search, businessType],
    queryFn: () => src.getProductKnowledge(search, businessType),
  });
  return (
    <div className="integration-card" aria-label="معرفة فينورا">
      <h4>معرفة النظام ودليل الاستخدام</h4>
      <p className="set-note">
        الردود تعتمد على ميزات فينورا وأدلة الاستخدام. الأسعار تؤخذ من الباقات الحالية.
      </p>
      {query.data && (
        <p role="status">
          {query.data.featureCount} ميزة · {query.data.guideCount} دليل استخدام · {query.data.publishedCount}{" "}
          وثيقة منشورة
        </p>
      )}
      <Field label="نوع النشاط للشرح">
        <select
          className="input"
          value={businessType}
          onChange={(event) => setBusinessType(event.target.value)}
        >
          <option value="">كل الأنشطة</option>
          <option value="general">شركة عامة / تجارة</option>
          <option value="starter_business">إدارة أعمال مبسّطة</option>
          <option value="clinics">عيادات</option>
          <option value="beauty_center">مركز تجميل</option>
          <option value="wholesale">تجارة الجملة</option>
          <option value="food_wholesale_retail">مواد غذائية</option>
          <option value="hr_management">موارد بشرية</option>
        </select>
      </Field>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          setSearch(text.trim());
        }}
      >
        <Field label="ابحث عن ميزة أو طريقة استخدامها">
          <input
            className="input"
            value={text}
            maxLength={200}
            placeholder="مثلاً: شلون أضيف منتج؟"
            onChange={(event) => setText(event.target.value)}
          />
        </Field>
        <FinoraButton size="sm" type="submit" loading={query.isFetching}>
          بحث في معرفة النظام
        </FinoraButton>
      </form>
      {query.isPending && <Skeleton w="100%" h={80} />}
      {query.isError && <ErrorState error={query.error} onRetry={() => void query.refetch()} />}
      {query.data && <p className="set-note">{query.data.note}</p>}
      {query.data?.results.map((item) => (
        <article className="integration-preview" key={item.id}>
          <h4>{item.title}</h4>
          <Badge tone={item.kind === "feature" ? "amber" : "green"}>
            {item.kind === "feature" ? "تعريف بالميزة" : "شرح موثق"}
          </Badge>
          <p style={{ whiteSpace: "pre-line" }}>{item.text}</p>
        </article>
      ))}
      {search && query.data && !query.data.results.length && (
        <p>ماكو شرح موثق لهذا السؤال حالياً؛ يحوّله الذكاء لفريق فينورا حتى يتأكد.</p>
      )}
    </div>
  );
}

export function IntegrationSettings({
  src,
  section,
}: {
  src: HttpDataSource;
  section: IntegrationSection | null;
}) {
  const agentVisible = section === "ai" || section === "replies";
  const query = useQuery({
    queryKey: AGENT_KEY,
    queryFn: () => src.getAgentSettings(),
    enabled: agentVisible,
    staleTime: 30_000,
  });
  return (
    <>
      <div hidden={!agentVisible}>
        {query.data ? (
          <AgentForm src={src} settings={query.data} section={section === "replies" ? "replies" : "ai"} />
        ) : query.isPending ? (
          <Skeleton w="100%" h={120} />
        ) : query.isError ? (
          <ErrorState error={query.error} onRetry={() => void query.refetch()} />
        ) : null}
      </div>
      {section === "knowledge" && <KnowledgePanel src={src} />}
      {section === "meta" && <MetaForm src={src} />}
      {section === "telegram" && <TelegramSettings src={src} />}
    </>
  );
}
