import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type { HttpDataSource } from "../data/http";
import { Badge, ErrorState, FinoraButton, Skeleton, TelegramIcon, errorText } from "../ui/primitives";

const KEY = ["core-telegram-settings"];
const LABEL: Record<string, string> = {
  connected: "متصل",
  disconnected: "غير متصل",
  token_invalid: "رمز البوت غير صالح",
  token_expired: "رمز البوت غير صالح",
  webhook_invalid: "استقبال الرسائل يحتاج فحص",
  unknown: "تعذر التحقق",
};

export function TelegramSettings({ src }: { src: HttpDataSource }) {
  const qc = useQueryClient();
  const query = useQuery({ queryKey: KEY, queryFn: () => src.getTelegramSettings() });
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const run = async (name: string, action: () => Promise<void>) => {
    setBusy(name);
    setNotice("");
    setError("");
    try {
      await action();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy("");
    }
  };
  const update = async (action: ReturnType<HttpDataSource["getTelegramSettings"]>) => {
    const result = await action;
    qc.setQueryData(KEY, result);
    await qc.invalidateQueries({ queryKey: ["status"] });
    return result;
  };
  const data = query.data;
  return (
    <div className="integration-card telegram-settings">
      <h4 className="telegram-title">
        <TelegramIcon size={20} /> بوت تلگرام
      </h4>
      <p className="kill-text">
        خلّي عملاءك يحچون ويا FINORA من تلگرام. البوت يستخدم نفس معرفة النظام وإعدادات الردود، وتجهيز الحساب
        والصلاحيات يبقى بعد مراجعة المشرف.
      </p>
      {query.isPending && <Skeleton w="100%" h={70} />}
      {query.isError && <ErrorState error={query.error} onRetry={() => void query.refetch()} />}
      {data && (
        <>
          <ul className="set-rows">
            <li>
              <span className="set-label">حالة الاتصال</span>
              <Badge tone={data.status === "connected" ? "green" : "neutral"}>
                {LABEL[data.status] ?? "يحتاج فحص"}
              </Badge>
            </li>
            {data.username && (
              <li>
                <span className="set-label">البوت المرتبط</span>
                <a href={data.botUrl} target="_blank" rel="noreferrer" dir="ltr">
                  @{data.username}
                </a>
              </li>
            )}
          </ul>
          {!data.houseConfigured && (
            <FinoraButton
              size="sm"
              disabled={!!busy}
              loading={busy === "provision"}
              onClick={() =>
                void run("provision", async () => {
                  await src.provisionMetaHouse();
                  await query.refetch();
                  await qc.invalidateQueries({ queryKey: ["status"] });
                  setNotice("تم تجهيز حساب FINORA الداخلي؛ تگدر تربط البوت هسه");
                })
              }
            >
              تهيئة قنوات FINORA على الخادم
            </FinoraButton>
          )}
          <p className="kill-text">
            سوّي بوت من{" "}
            <a href="https://t.me/BotFather" target="_blank" rel="noreferrer" dir="ltr">
              @BotFather
            </a>{" "}
            بالأمر <b dir="ltr">/newbot</b>، وانسخ رمزه هنا. الربط يضبط استقبال الرسائل تلقائياً.
          </p>
          <label className="integration-field">
            <span>رمز بوت تلگرام</span>
            <input
              className="input"
              type="password"
              dir="ltr"
              autoComplete="new-password"
              value={token}
              maxLength={256}
              placeholder={
                data.tokenConfigured ? "محفوظ بأمان؛ أدخله فقط لإعادة الربط" : "أدخل Bot Token من BotFather"
              }
              onChange={(e) => setToken(e.target.value)}
            />
          </label>
          <div className="integration-actions">
            <FinoraButton
              size="sm"
              variant="primary"
              disabled={!!busy || !data.houseConfigured || !token.trim()}
              loading={busy === "connect"}
              onClick={() =>
                void run("connect", async () => {
                  await update(src.connectTelegram(token.trim()));
                  setToken("");
                  setNotice("تم ربط البوت. افتح رابطه من حساب العميل واضغط بدء لإرسال أول رسالة.");
                })
              }
            >
              ربط البوت
            </FinoraButton>
            <FinoraButton
              size="sm"
              disabled={!!busy || !data.active}
              loading={busy === "health"}
              onClick={() =>
                void run("health", async () => {
                  const result = await update(src.checkTelegramHealth());
                  setNotice(
                    result.status === "connected"
                      ? "رمز البوت واستقبال الرسائل يعملان"
                      : "فحص الاتصال اكتمل؛ راجع حالة القناة",
                  );
                })
              }
            >
              فحص اتصال تلگرام
            </FinoraButton>
            <FinoraButton
              size="sm"
              variant="danger"
              disabled={!!busy || !data.active}
              loading={busy === "disconnect"}
              onClick={() =>
                void run("disconnect", async () => {
                  await update(src.disconnectTelegram());
                  setNotice("تم فصل البوت؛ المحادثات محفوظة");
                })
              }
            >
              فصل البوت
            </FinoraButton>
          </div>
          {data.lastError && (
            <p className="integration-error" role="note">
              {data.lastError}
            </p>
          )}
          <p className="kill-text">
            يستقبل الرسائل الخاصة والصور والفيديو والفويز والملفات حتى 20 MB. طريقة الرد تختارها من «ردود
            العملاء»؛ وضع المراجعة يجهّز الرد للمشرف.
          </p>
          {data.webhookUrl && (
            <details className="integration-help">
              <summary>تفاصيل استقبال الرسائل</summary>
              <label className="integration-field">
                <span>عنوان استقبال تلگرام</span>
                <input className="input" dir="ltr" readOnly value={data.webhookUrl} />
              </label>
              <p className="kill-text">
                الخادم يحتاج عنوان HTTPS متاح للعامة. مجموعات تلگرام غير مفعّلة لقناة خدمة العملاء.
              </p>
            </details>
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
