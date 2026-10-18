import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { Building2, KeyRound, LogIn, Server, UserRound } from "lucide-react";
import { useEffect, useId, useState, type FormEvent, type ReactNode } from "react";
import { finora, toFinoraError, type FinoraSession } from "@/api/finora";
import { FinoraLogo } from "@/components/FinoraLogo";
import { WindowControls } from "@/components/WindowControls";
import { SESSION_QUERY_KEY } from "@/hooks/useSessionProbe";
import { useSession, type SignedOutReason } from "@/stores/session";
import { toast } from "@/stores/toasts";

const REASON_TEXT: Record<Exclude<SignedOutReason, null>, string> = {
  signed_out: "تم تسجيل الخروج.",
  expired: "انتهت الجلسة، سجّل الدخول من جديد.",
  password_change_required: "كلمة المرور مؤقتة. غيّرها من FINORA على الويب ثم سجّل الدخول.",
};

export const CONFIG_QUERY_KEY = ["desktop", "config"] as const;

class InvalidServerUrlError extends Error {}

interface FieldProps {
  label: string;
  icon: ReactNode;
  children: (id: string) => ReactNode;
}

function Field({ label, icon, children }: FieldProps) {
  const id = useId();
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="text-[13px] font-medium text-ink-soft">
        {label}
      </label>
      <div className="flex h-12 items-center gap-3 rounded-control border border-line bg-white/80 px-4 focus-within:border-violet/50 focus-within:ring-4 focus-within:ring-violet/10">
        <span className="text-ink-faint">{icon}</span>
        {children(id)}
      </div>
    </div>
  );
}

const inputClass =
  "h-full flex-1 bg-transparent text-[15px] text-ink outline-none placeholder:text-ink-faint";

export function LoginScreen() {
  const queryClient = useQueryClient();
  const reason = useSession((s) => s.reason);
  const config = useQuery({
    queryKey: CONFIG_QUERY_KEY,
    queryFn: () => finora.config.get(),
    staleTime: Infinity,
  });

  const [serverUrl, setServerUrl] = useState("");
  const [editingServer, setEditingServer] = useState(false);
  const [tenantSlug, setTenantSlug] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!config.data) return;
    setServerUrl(config.data.serverUrl ?? "");
    setEditingServer(!config.data.serverUrl);
    setTenantSlug((value) => value || config.data.lastTenantSlug || "");
    setUsername((value) => value || config.data.lastUsername || "");
  }, [config.data]);

  const signIn = useMutation({
    mutationFn: async (): Promise<FinoraSession> => {
      const trimmed = serverUrl.trim();
      if (trimmed && trimmed !== config.data?.serverUrl) {
        try {
          queryClient.setQueryData(CONFIG_QUERY_KEY, await finora.config.setServer(trimmed));
        } catch {
          throw new InvalidServerUrlError("عنوان الخادم غير صحيح. مثال: https://finora.company");
        }
      }
      return finora.auth.signIn({
        tenantSlug: tenantSlug.trim().toLowerCase(),
        username: username.trim(),
        password,
      });
    },
    onSuccess: (session) => {
      setPassword("");
      queryClient.setQueryData(SESSION_QUERY_KEY, session);
      useSession.getState().signedIn(session);
      toast.success(`أهلاً ${session.user.name}`);
    },
    onError: (failure) => {
      setPassword("");
      setError(failure instanceof InvalidServerUrlError ? failure.message : toFinoraError(failure).message);
    },
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    if (!serverUrl.trim()) return setError("أدخل عنوان خادم FINORA.");
    if (!tenantSlug.trim() || !username.trim() || !password)
      return setError("أدخل معرف الشركة واسم المستخدم وكلمة المرور.");
    signIn.mutate();
  };

  const notice = error ?? (reason ? REASON_TEXT[reason] : null);

  return (
    <div className="flex h-full flex-col">
      <div dir="ltr" className="drag-region flex h-14 shrink-0 items-center justify-end px-4">
        <div className="no-drag">
          <WindowControls />
        </div>
      </div>
      <main className="grid flex-1 place-items-center pb-14">
        <motion.form
          onSubmit={submit}
          aria-label="تسجيل الدخول إلى FINORA"
          className="glass glass-outline w-[440px] rounded-window px-9 pb-9 pt-8"
          initial={{ opacity: 0, y: 14, scale: 0.985 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
        >
          <div className="mb-7 flex flex-col items-center gap-4">
            <FinoraLogo />
            <p className="text-sm text-ink-soft">
              سجّل الدخول بحساب FINORA لإدارة الطلبات والمشتريات والمنتجات
            </p>
          </div>

          {notice && (
            <p
              role={error ? "alert" : "status"}
              className={
                error
                  ? "mb-5 rounded-control bg-danger-soft px-4 py-3 text-sm text-danger"
                  : "mb-5 rounded-control bg-violet-soft px-4 py-3 text-sm text-violet-deep"
              }
            >
              {notice}
            </p>
          )}

          <div className="space-y-4">
            {editingServer ? (
              <Field label="عنوان خادم FINORA" icon={<Server size={18} />}>
                {(id) => (
                  <input
                    id={id}
                    dir="ltr"
                    value={serverUrl}
                    onChange={(event) => setServerUrl(event.target.value)}
                    placeholder="https://finora.company"
                    autoComplete="url"
                    className={inputClass}
                  />
                )}
              </Field>
            ) : (
              <div className="flex items-center gap-2 text-xs text-ink-faint">
                <Server size={14} aria-hidden />
                <span className="ltr-isolate">{serverUrl}</span>
                <button
                  type="button"
                  onClick={() => setEditingServer(true)}
                  className="ms-auto text-violet-deep hover:underline"
                >
                  تغيير الخادم
                </button>
              </div>
            )}
            <Field label="معرف الشركة" icon={<Building2 size={18} />}>
              {(id) => (
                <input
                  id={id}
                  dir="ltr"
                  value={tenantSlug}
                  onChange={(event) => setTenantSlug(event.target.value)}
                  autoComplete="organization"
                  className={inputClass}
                />
              )}
            </Field>
            <Field label="اسم المستخدم" icon={<UserRound size={18} />}>
              {(id) => (
                <input
                  id={id}
                  dir="ltr"
                  value={username}
                  onChange={(event) => setUsername(event.target.value)}
                  autoComplete="username"
                  className={inputClass}
                />
              )}
            </Field>
            <Field label="كلمة المرور" icon={<KeyRound size={18} />}>
              {(id) => (
                <input
                  id={id}
                  dir="ltr"
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  autoComplete="current-password"
                  className={inputClass}
                />
              )}
            </Field>
          </div>

          <button
            type="submit"
            disabled={signIn.isPending}
            className="mt-7 flex h-12 w-full items-center justify-center gap-2 rounded-control bg-gradient-to-l from-maroon to-violet-deep text-[15px] font-semibold text-white shadow-float transition-opacity hover:opacity-95 disabled:opacity-60"
          >
            <LogIn size={18} aria-hidden />
            {signIn.isPending ? "جارٍ تسجيل الدخول…" : "تسجيل الدخول"}
          </button>
        </motion.form>
      </main>
    </div>
  );
}
