import { useEffect, useRef, useState } from "react";
import { AuditSheet } from "./AuditSheet";
import { FeatureHelp } from "@/components/FeatureHelp";
import { hasDesktopBridge } from "@/services/bridge";

type DetectorConstructor = {
  new (options: { formats: string[] }): { detect(source: HTMLVideoElement): Promise<{ rawValue: string }[]> };
  getSupportedFormats(): Promise<string[]>;
};
export function cameraAuditAvailable() {
  return (
    !hasDesktopBridge() &&
    window.isSecureContext &&
    !!navigator.mediaDevices?.getUserMedia &&
    !!(window as Window & { BarcodeDetector?: DetectorConstructor }).BarcodeDetector
  );
}
export function AuditCamera({
  open,
  onClose,
  onRead,
  caption,
}: {
  open: boolean;
  onClose(): void;
  onRead(code: string): void;
  caption: string;
}) {
  const video = useRef<HTMLVideoElement>(null),
    read = useRef(onRead);
  read.current = onRead;
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!open) return;
    setError(null);
    let cancelled = false,
      stream: MediaStream | null = null,
      frame = 0,
      last = "",
      lastSeen = 0,
      timer: number | undefined;
    const stop = () => {
      cancelled = true;
      stream?.getTracks().forEach((track) => track.stop());
      cancelAnimationFrame(frame);
      if (timer) window.clearTimeout(timer);
    };
    const hidden = () => {
      if (document.hidden) {
        stop();
        setError("توقف المسح عند مغادرة الصفحة؛ أغلق الكاميرا وأعد فتحها عند الرجوع");
      }
    };
    document.addEventListener("visibilitychange", hidden);
    void (async () => {
      if (!cameraAuditAvailable()) {
        setError("المسح بالكاميرا غير متاح هنا؛ استخدم قارئ الباركود أو البحث");
        return;
      }
      try {
        const Constructor = (window as Window & { BarcodeDetector?: DetectorConstructor }).BarcodeDetector;
        if (!Constructor) throw Error("unsupported");
        const formats = (await Constructor.getSupportedFormats()).filter((format) =>
          ["ean_13", "ean_8", "code_128", "code_39", "upc_a", "upc_e", "qr_code"].includes(format),
        );
        if (!formats.length) throw Error("unsupported");
        stream = await navigator.mediaDevices.getUserMedia({
          audio: false,
          video: { facingMode: { ideal: "environment" } },
        });
        if (cancelled) {
          stream.getTracks().forEach((track) => track.stop());
          return;
        }
        if (!video.current) return;
        video.current.srcObject = stream;
        await video.current.play();
        const detector = new Constructor({ formats });
        const scan = async () => {
          if (cancelled) return;
          if (video.current && video.current.readyState >= 2) {
            const codes = await detector.detect(video.current);
            const code = codes[0]?.rawValue;
            const now = performance.now();
            if (code) {
              if (last !== code || now - lastSeen > 1200) {
                last = code;
                read.current(code);
              }
              lastSeen = now;
            } else if (now - lastSeen > 1200) last = "";
          }
          if (!cancelled)
            timer = window.setTimeout(() => {
              frame = requestAnimationFrame(() => {
                void scan().catch(() => {
                  stop();
                  setError("تعذر قراءة الكاميرا؛ أعد فتح المسح أو استخدم البحث");
                });
              });
            }, 250);
        };
        await scan();
      } catch (problem) {
        stop();
        setError(
          problem instanceof DOMException && problem.name === "NotAllowedError"
            ? "إذن الكاميرا مرفوض؛ فعّله من المتصفح أو استخدم قارئ الباركود"
            : "تعذر تشغيل مسح الكاميرا على هذا الجهاز؛ استخدم قارئ الباركود أو البحث",
        );
      }
    })();
    return () => {
      stop();
      document.removeEventListener("visibilitychange", hidden);
    };
  }, [open]);
  return (
    <AuditSheet open={open} title="مسح باركود الجرد" onClose={onClose}>
      <video
        ref={video}
        muted
        playsInline
        aria-label="معاينة مسح الباركود"
        className="aspect-[4/3] w-full rounded-panel bg-ink/90 object-cover"
      />
      <p role="status" className="mt-3 text-sm">
        {caption}
      </p>
      {error && (
        <p role="alert" className="mt-3 rounded-control bg-red-50 p-3 text-sm text-red-700">
          {error}
        </p>
      )}
      <div className="mt-3 flex items-center gap-2 text-xs text-ink-soft">
        حرّك القطعة خارج الإطار بين القراءات.
        <FeatureHelp text="تمنع الكاميرا تكرار قراءة نفس الكود المتواصل. وضع التحديد يفتح بطاقة العدد، ووضع العد يضيف قطعة واحدة لكل قراءة جديدة. البيانات تحفظ كعد؛ لا تعدل المخزون حتى الترحيل." />
      </div>
    </AuditSheet>
  );
}
