import { AnimatePresence, motion } from "framer-motion";
import { Copy, KeyRound, ShieldAlert } from "lucide-react";
import { useEffect, useRef } from "react";
import { create } from "zustand";
import { transitions } from "../design/motion";
import type { Credentials } from "../data/schemas";
import { FinoraButton } from "../ui/primitives";
import { toast } from "../ui/toast";

/**
 * One-time display of trial-account credentials to the approving operator.
 * Held only in memory while the dialog is open; never persisted, logged or sent to the customer chat.
 */
const useCredentials = create<{ value: Credentials | null; set: (v: Credentials | null) => void }>((set) => ({
  value: null,
  set: (value) => set({ value }),
}));

export function showCredentials(value: Credentials) {
  useCredentials.getState().set(value);
}

async function copy(text: string) {
  try {
    await navigator.clipboard.writeText(text);
    toast.success("تم النسخ");
  } catch (err) {
    console.warn("[finora-core] clipboard unavailable", err);
    toast.error("تعذر النسخ — انسخها يدوياً");
  }
}

export function CredentialsDialog() {
  const value = useCredentials((s) => s.value);
  const close = () => useCredentials.getState().set(null);
  const ref = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (value) ref.current?.focus();
  }, [value]);

  const all = value
    ? [
        `FINORA: ${value.tenantSlug}`,
        `Username: ${value.username}`,
        `Password: ${value.password}`,
        value.loginUrl ? `Login: ${value.loginUrl}` : "",
      ]
        .filter(Boolean)
        .join("\n")
    : "";

  return (
    <AnimatePresence>
      {value && (
        <>
          <motion.div
            key="cred-scrim"
            className="scrim"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          />
          <motion.div
            key="cred"
            className="cred-dialog"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="cred-title"
            initial={{ opacity: 0, scale: 0.97, y: 8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.98 }}
            transition={transitions.normal}
          >
            <header className="cred-head">
              <span className="cred-icon">
                <KeyRound size={18} />
              </span>
              <h2 id="cred-title">تم إنشاء الحساب التجريبي</h2>
            </header>
            <p className="cred-warn">
              <ShieldAlert size={15} /> هذه البيانات تظهر مرة واحدة فقط ولا تُحفظ. سلّمها للعميل بطريقة آمنة
              (اتصال أو رسالة خاصة)، ولا ترسلها في محادثة عامة.
            </p>
            <dl className="cred-grid" dir="ltr">
              <dt>Account</dt>
              <dd>{value.tenantSlug}</dd>
              <dt>Username</dt>
              <dd>{value.username}</dd>
              <dt>Password</dt>
              <dd className="cred-secret">{value.password}</dd>
              {value.loginUrl && (
                <>
                  <dt>Login</dt>
                  <dd>{value.loginUrl}</dd>
                </>
              )}
            </dl>
            <footer className="cred-actions">
              <FinoraButton variant="soft" onClick={() => void copy(all)}>
                <Copy size={15} /> نسخ البيانات
              </FinoraButton>
              <FinoraButton ref={ref} variant="primary" onClick={close}>
                تم — إخفاء نهائياً
              </FinoraButton>
            </footer>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
