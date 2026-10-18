import { ArrowLeft, LogIn, ServerCog } from "lucide-react";
import { useState, type FormEvent } from "react";
import { login, normalizeServerUrl } from "../data/http";
import type { TokenResponse } from "../data/schemas";
import { CoreError } from "../data/source";
import { FinoraButton, FinoraMark, MiniOrb, errorText } from "../ui/primitives";
import { WindowControls } from "./TitleBar";

const SERVER_KEY = "finora-core.server";

/** Build-time URL wins; otherwise the URL the admin entered on first run. */
export function loadServerUrl(): string | null {
  const fromBuild = import.meta.env.VITE_FINORA_API_URL as string | undefined;
  if (fromBuild) return normalizeServerUrl(fromBuild);
  try {
    const stored = localStorage.getItem(SERVER_KEY);
    return stored ? normalizeServerUrl(stored) : null;
  } catch (err) {
    console.warn("[finora-core] server URL unreadable", err);
    return null;
  }
}

export function saveServerUrl(url: string | null): void {
  try {
    if (url) localStorage.setItem(SERVER_KEY, url);
    else localStorage.removeItem(SERVER_KEY);
  } catch (err) {
    console.warn("[finora-core] could not persist server URL", err);
  }
}

export function GateShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="gate">
      <div className="gate-bar" data-tauri-drag-region>
        <WindowControls />
      </div>
      <div className="gate-card">
        <div className="gate-brand">
          <MiniOrb size={64} active />
          <div className="gate-word">
            <span>FINORA</span>
            <small>CORE</small>
          </div>
        </div>
        {children}
      </div>
      <div className="gate-foot">
        <FinoraMark size={18} /> FINORA Super Admin
      </div>
    </div>
  );
}

/** First run (spec §84): ask for the FINORA server once. */
export function ServerSetup({ onDone }: { onDone: (url: string) => void }) {
  const [value, setValue] = useState("https://finora.company");
  const [error, setError] = useState<string | null>(null);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const url = normalizeServerUrl(value);
    if (!url) {
      setError("أدخل عنوان https صالح (أو http://localhost للتطوير)");
      return;
    }
    saveServerUrl(url);
    onDone(url);
  };
  return (
    <GateShell>
      <form className="gate-form" onSubmit={submit} noValidate>
        <h1>ربط الخادم</h1>
        <p className="gate-hint">
          <ServerCog size={15} /> عنوان خادم FINORA الذي يشغّل FINORA CORE
        </p>
        <label className="gate-field">
          <span>عنوان الخادم</span>
          <input
            className="input"
            dir="ltr"
            value={value}
            onChange={(e) => (setValue(e.target.value), setError(null))}
            aria-invalid={!!error}
            aria-describedby={error ? "gate-err" : undefined}
            autoFocus
          />
        </label>
        {error && (
          <p className="gate-error" id="gate-err" role="alert">
            {error}
          </p>
        )}
        <FinoraButton type="submit" variant="primary">
          متابعة
        </FinoraButton>
      </form>
    </GateShell>
  );
}

export function Login({
  serverUrl,
  onSignedIn,
  onChangeServer,
}: {
  serverUrl: string;
  onSignedIn: (t: TokenResponse) => void | Promise<void>;
  onChangeServer: () => void;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password) {
      setError("أدخل اسم المستخدم وكلمة المرور");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await onSignedIn(await login(serverUrl, username.trim(), password));
    } catch (err) {
      setError(err instanceof CoreError ? err.message : errorText(err));
      setPassword("");
    } finally {
      setBusy(false);
    }
  };

  return (
    <GateShell>
      <form className="gate-form" onSubmit={(e) => void submit(e)} noValidate>
        <h1>تسجيل الدخول</h1>
        <button type="button" className="gate-server" onClick={onChangeServer} title="تغيير الخادم">
          <span dir="ltr">{new URL(serverUrl).host}</span>
          <ArrowLeft size={13} />
        </button>
        <label className="gate-field">
          <span>اسم المستخدم</span>
          <input
            className="input"
            dir="ltr"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoFocus
          />
        </label>
        <label className="gate-field">
          <span>كلمة المرور</span>
          <input
            className="input"
            dir="ltr"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        {error && (
          <p className="gate-error" role="alert">
            {error}
          </p>
        )}
        <FinoraButton type="submit" variant="primary" loading={busy}>
          <LogIn size={16} /> دخول
        </FinoraButton>
      </form>
    </GateShell>
  );
}
