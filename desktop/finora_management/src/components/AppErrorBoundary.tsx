import { Component, type ErrorInfo, type ReactNode } from "react";
import { desktopBridge } from "@/services/bridge";

export class AppErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  override state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  override componentDidCatch(_error: Error, info: ErrorInfo) {
    // Log the component path only; form values and server payloads stay private.
    console.error("[renderer] unexpected component failure", info.componentStack);
  }
  override render() {
    if (!this.state.failed) return this.props.children;
    return (
      <main dir="rtl" role="alert" className="grid h-full place-content-center gap-4 p-8 text-center">
        <h1 className="text-xl font-bold">تعذّر عرض هذه الشاشة</h1>
        <p className="max-w-lg text-sm text-ink-soft">
          العمليات المحفوظة محلياً تبقى في سجل المزامنة. أعد فتح الواجهة؛ راجع نتيجة أي عملية جارية قبل
          تكرارها.
        </p>
        <button
          className="rounded-control bg-violet px-5 py-3 text-white"
          onClick={() => {
            const recovery = desktopBridge().lifecycle;
            if (recovery) void recovery.reload();
            else window.location.reload();
          }}
        >
          إعادة فتح الواجهة
        </button>
      </main>
    );
  }
}
