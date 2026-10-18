import { AnimatePresence, motion } from "framer-motion";
import { RefreshCw, WifiOff } from "lucide-react";
import { useState } from "react";
import { finora } from "@/api/finora";
import { useConnection } from "@/stores/connection";
import { useOffline } from "@/stores/offline";

/** Shown under the top bar while FINORA cannot be reached; data stays read-only until it returns. */
export function OfflineBanner() {
  const status = useConnection((s) => s.status);
  const offline = useOffline((s) => s.status);
  const [checking, setChecking] = useState(false);

  const retry = () => {
    setChecking(true);
    finora.auth
      .session()
      .catch((error: unknown) => {
        if (import.meta.env.DEV) console.debug("[connection] manual retry", error);
      })
      .finally(() => setChecking(false));
  };

  return (
    <AnimatePresence>
      {status !== "online" && (
        <motion.div
          role="status"
          className="pointer-events-none absolute inset-x-0 top-[calc(var(--nav-height)-6px)] z-40 flex justify-center"
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -8 }}
        >
          <div className="pointer-events-auto flex items-center gap-3 rounded-full bg-ink px-4 py-2 text-sm text-white shadow-float">
            <WifiOff size={16} aria-hidden />
            <span>لا يوجد اتصال بـ FINORA</span>
            <span className="text-white/60">
              ·{" "}
              {offline.available
                ? offline.pending > 0
                  ? `آخر بيانات محفوظة · ${offline.pending} عملية تنتظر المزامنة`
                  : "آخر بيانات محفوظة"
                : "البيانات للقراءة فقط"}
            </span>
            <button
              type="button"
              onClick={retry}
              disabled={checking}
              className="no-drag flex items-center gap-1.5 rounded-full bg-white/15 px-2.5 py-1 text-xs hover:bg-white/25 disabled:opacity-60"
            >
              <RefreshCw size={13} className={checking ? "animate-spin" : undefined} aria-hidden />
              إعادة المحاولة
            </button>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
