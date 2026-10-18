import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AnimatePresence, LayoutGroup, MotionConfig, motion, useReducedMotion } from "framer-motion";
import { X } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ActivityPanel } from "../activity/ActivityPanel";
import { CredentialsDialog } from "../approvals/CredentialsDialog";
import { reducedTransition, transitions } from "../design/motion";
import { DataSourceContext, useOnline, useRealtimeBridge } from "../data/hooks";
import { resolveDataSource } from "../data/index";
import type { CoreEvent } from "../data/schemas";
import { CoreError, type DataSource } from "../data/source";
import { HttpDataSource, type AuthSession } from "../data/http";
import { loadSession, saveSession } from "../data/session";
import { hasWebGL, OrbStage } from "../orb/OrbStage";
import { SettingsPanel } from "../settings/SettingsPanel";
import { useNotificationVoice } from "../notifications/useNotifications";
import { useUi } from "../state/ui";
import { FinoraButton, IconButton } from "../ui/primitives";
import { toast, Toaster } from "../ui/toast";
import { Workspace } from "../workspace/Workspace";
import { GateShell, Login, ServerSetup, loadServerUrl, saveServerUrl } from "./Gate";
import { TitleBar } from "./TitleBar";

function makeClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 15_000,
        refetchOnWindowFocus: false,
        // Bounded retries; never retry non-retryable classified errors (spec §36).
        retry: (count, err) => (err instanceof CoreError ? err.retryable && count < 2 : count < 2),
        retryDelay: (n) => Math.min(4000, 400 * 2 ** n) + Math.random() * 250,
      },
      mutations: { retry: false },
    },
  });
}

function useEffectiveReducedMotion(): boolean {
  const system = useReducedMotion() ?? false;
  const pref = useUi((s) => s.appearance.reducedMotion);
  return pref === "on" || (pref === "system" && system);
}

const OVERLAY_TITLE = { activity: "النشاط", settings: "الإعدادات" } as const;

function Overlay({ reducedMotion }: { reducedMotion: boolean }) {
  const overlay = useUi((s) => s.overlay);
  const setOverlay = useUi((s) => s.setOverlay);
  const side = overlay === "activity" ? "left" : "right";
  const t = reducedMotion ? reducedTransition : transitions.slow;
  return (
    <AnimatePresence>
      {overlay !== "none" && (
        <>
          <motion.div
            key="scrim"
            className="scrim"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={transitions.normal}
            onClick={() => setOverlay("none")}
          />
          <motion.aside
            key={overlay}
            className={`sheet is-${side}`}
            role="dialog"
            aria-modal="true"
            aria-label={OVERLAY_TITLE[overlay]}
            initial={{ opacity: 0, x: reducedMotion ? 0 : side === "left" ? -32 : 32 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{
              opacity: 0,
              x: reducedMotion ? 0 : side === "left" ? -24 : 24,
              transition: transitions.normal,
            }}
            transition={t}
          >
            <header className="sheet-head">
              <h2>{OVERLAY_TITLE[overlay]}</h2>
              <IconButton label="إغلاق" onClick={() => setOverlay("none")} autoFocus>
                <X size={18} />
              </IconButton>
            </header>
            <div className="sheet-body">{overlay === "activity" ? <ActivityPanel /> : <SettingsPanel />}</div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}

function Shell({ devData }: { devData: boolean }) {
  const view = useUi((s) => s.view);
  const reducedMotion = useEffectiveReducedMotion();
  const online = useOnline();
  const webgl = useMemo(
    () => new URLSearchParams(window.location.search).get("gl") !== "0" && hasWebGL(),
    [],
  );

  const announce = useNotificationVoice();
  const onEvent = useCallback(
    (e: CoreEvent) => {
      if (e.type === "approval.required") toast.info(`طلب موافقة: ${e.approval.action}`);
      announce(e);
    },
    [announce],
  );
  useRealtimeBridge(onEvent);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || e.defaultPrevented) return;
      const ui = useUi.getState();
      if (ui.overlay !== "none") return ui.setOverlay("none");
      const el = e.target;
      if (el instanceof HTMLTextAreaElement || el instanceof HTMLInputElement) {
        if (el.value) return; // never discard typed text with Esc
      }
      if (ui.view === "workspace" && ui.customerPanelOpen) return ui.toggleCustomerPanel(false);
      if (ui.view === "workspace") ui.closeWorkspace();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <MotionConfig reducedMotion={reducedMotion ? "always" : "never"}>
      <div className="app" data-view={view} data-reduced={reducedMotion}>
        <TitleBar devData={devData} />
        {!online && (
          <div className="offline-bar" role="alert">
            Offline — لا يوجد اتصال بالإنترنت. يتم عرض آخر بيانات محفوظة ولن تُرسل أي رسالة.
          </div>
        )}
        <main className="app-body">
          <LayoutGroup>
            <OrbStage reducedMotion={reducedMotion} webgl={webgl} />
            <Workspace open={view === "workspace"} reducedMotion={reducedMotion} />
          </LayoutGroup>
        </main>
        <Overlay reducedMotion={reducedMotion} />
        <Toaster />
        <CredentialsDialog />
      </div>
    </MotionConfig>
  );
}

type Connection =
  | { stage: "dev"; source: DataSource }
  | { stage: "server" }
  | { stage: "restoring"; serverUrl: string; error?: string }
  | { stage: "login"; serverUrl: string }
  | { stage: "ready"; source: HttpDataSource };

function initialConnection(): Connection {
  const dev = resolveDataSource();
  if (dev) return { stage: "dev", source: dev };
  const serverUrl = loadServerUrl();
  if (!serverUrl) return { stage: "server" };
  return { stage: "restoring", serverUrl };
}

let onSignedOut: (() => void) | null = null;

function makeHttp(serverUrl: string, session: AuthSession): HttpDataSource {
  return new HttpDataSource(serverUrl, session, async (next) => {
    try {
      await saveSession(serverUrl, next);
    } finally {
      if (!next) onSignedOut?.();
    }
  });
}

export function App() {
  const [client] = useState(makeClient);
  const [conn, setConn] = useState<Connection>(initialConnection);

  useEffect(() => {
    onSignedOut = () => {
      client.clear();
      const serverUrl = loadServerUrl();
      setConn(serverUrl ? { stage: "login", serverUrl } : { stage: "server" });
    };
    return () => {
      onSignedOut = null;
    };
  }, [client]);

  const restoringUrl = conn.stage === "restoring" && !conn.error ? conn.serverUrl : null;
  useEffect(() => {
    if (!restoringUrl) return;
    let cancelled = false;
    void loadSession(restoringUrl).then(
      (session) => {
        if (!cancelled)
          setConn(
            session
              ? { stage: "ready", source: makeHttp(restoringUrl, session) }
              : { stage: "login", serverUrl: restoringUrl },
          );
      },
      (err: unknown) => {
        if (!cancelled)
          setConn({
            stage: "restoring",
            serverUrl: restoringUrl,
            error: err instanceof CoreError ? err.message : "تعذّر استعادة جلسة الدخول",
          });
      },
    );
    return () => {
      cancelled = true;
    };
  }, [restoringUrl]);

  if (conn.stage === "restoring")
    return (
      <GateShell>
        <p role={conn.error ? "alert" : "status"}>{conn.error ?? "جارٍ استعادة جلسة الدخول…"}</p>
        {conn.error && (
          <>
            <FinoraButton onClick={() => setConn({ stage: "restoring", serverUrl: conn.serverUrl })}>
              إعادة المحاولة
            </FinoraButton>
            <FinoraButton
              onClick={() => {
                void saveSession(conn.serverUrl, null)
                  .then(() => setConn({ stage: "login", serverUrl: conn.serverUrl }))
                  .catch(() => setConn({ ...conn, error: "تعذّر حذف الجلسة المحفوظة. حاول مرة ثانية." }));
              }}
            >
              تسجيل الدخول مجدداً
            </FinoraButton>
          </>
        )}
      </GateShell>
    );

  if (conn.stage === "server")
    return <ServerSetup onDone={(serverUrl) => setConn({ stage: "login", serverUrl })} />;
  if (conn.stage === "login")
    return (
      <Login
        serverUrl={conn.serverUrl}
        onChangeServer={() => {
          void saveSession(conn.serverUrl, null)
            .then(() => {
              saveServerUrl(null);
              setConn({ stage: "server" });
            })
            .catch(() => toast.error("تعذّر حذف الجلسة المحفوظة"));
        }}
        onSignedIn={async (t) => {
          const session = { accessToken: t.accessToken, refreshToken: t.refreshToken, operator: t.operator };
          await saveSession(conn.serverUrl, session);
          setConn({
            stage: "ready",
            source: makeHttp(conn.serverUrl, session),
          });
        }}
      />
    );
  return (
    <QueryClientProvider client={client}>
      <DataSourceContext.Provider value={conn.source}>
        <Shell devData={conn.stage === "dev"} />
      </DataSourceContext.Provider>
    </QueryClientProvider>
  );
}
