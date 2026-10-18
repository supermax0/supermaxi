import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { createRoot } from "react-dom/client";
import { useEffect } from "react";
import { sessionEnvelopeSchema } from "./api/finora/schemas";
import { AuditWorkspace } from "./windows/products/audit/AuditWorkspace";
import { useSession } from "./stores/session";
import { Toaster } from "./components/Toaster";
import "@fontsource/ibm-plex-sans-arabic/400.css";
import "@fontsource/ibm-plex-sans-arabic/500.css";
import "@fontsource/ibm-plex-sans-arabic/600.css";
import "@fontsource/ibm-plex-sans-arabic/700.css";
import "@fontsource-variable/inter";
import "./theme/index.css";

const client = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: true } } });
const linkedSession = new URLSearchParams(window.location.search).get("session") ?? "";
const initialSessionId = /^[1-9]\d{0,14}$/.test(linkedSession) ? Number(linkedSession) : null;
function AuditApp() {
  const auth = useQuery({
    queryKey: ["audit-web-session"],
    queryFn: async () => {
      const response = await fetch("/api/v1/desktop/auth/session", { credentials: "same-origin" });
      if (!response.ok) throw Error("سجّل الدخول إلى FINORA ثم افتح الجرد");
      return sessionEnvelopeSchema.parse(await response.json());
    },
  });
  const session = useSession((state) => state.session);
  const scope = JSON.stringify([
    window.location.origin,
    session?.tenant.id,
    session?.tenant.slug,
    session?.user.id,
    session?.branch?.id,
    session?.branch_scope,
    session?.permissions.slice().sort(),
  ]);
  useEffect(() => {
    if (auth.data) useSession.getState().signedIn(auth.data);
  }, [auth.data]);
  return (
    <main className="flex h-[100dvh] min-h-0 flex-col bg-canvas p-3 text-ink sm:p-5" dir="rtl">
      <header className="mb-3 flex shrink-0 items-center justify-between gap-2">
        <span className="font-semibold tracking-[.16em] text-maroon" dir="ltr">
          FINORA
        </span>
        <span className="text-xs text-ink-soft">{session?.tenant.name ?? "جرد المخزون"}</span>
      </header>
      {auth.error ? (
        <p role="alert" className="rounded-panel border border-line bg-white p-4 text-sm">
          {auth.error.message}
        </p>
      ) : session?.permissions.includes("inventory.audit.view") ? (
        <AuditWorkspace
          key={scope}
          scope={scope}
          serverUrl={window.location.origin}
          initialSessionId={initialSessionId}
        />
      ) : (
        <p className="p-4 text-sm">{auth.isLoading ? "جارٍ التحقق من الجلسة…" : "تحتاج صلاحية عرض الجرد"}</p>
      )}
      <Toaster />
    </main>
  );
}
const auditRoot = document.getElementById("root");
if (!auditRoot) throw Error("Missing inventory audit root");
createRoot(auditRoot).render(
  <QueryClientProvider client={client}>
    <AuditApp />
  </QueryClientProvider>,
);
