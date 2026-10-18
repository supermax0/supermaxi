import { Download, Eye, Film, ImageIcon, Mic, Pause, Play, Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useAnalyzeMedia, useSource } from "../data/hooks";
import { useCan } from "../data/can";
import type { Attachment } from "../data/schemas";
import { FinoraButton, IconButton, errorText } from "../ui/primitives";
import { toast } from "../ui/toast";

function time(seconds: number) {
  return Number.isFinite(seconds)
    ? `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`
    : "0:00";
}

export function AudioPlayer({ src, duration: initial = 0 }: { src: string; duration?: number }) {
  const audio = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const [position, setPosition] = useState(0);
  const [duration, setDuration] = useState(initial);
  const [speed, setSpeed] = useState(1);
  useEffect(() => {
    const element = audio.current;
    setPlaying(false);
    setPosition(0);
    setDuration(initial);
    setSpeed(1);
    if (element) element.playbackRate = 1;
    return () => element?.pause();
  }, [src, initial]);
  return (
    <div className="voice-player" aria-label="مشغل الفويز">
      <audio
        ref={audio}
        src={src}
        preload="metadata"
        onLoadedMetadata={() => {
          if (audio.current && Number.isFinite(audio.current.duration)) setDuration(audio.current.duration);
        }}
        onTimeUpdate={() => setPosition(audio.current?.currentTime ?? 0)}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)}
        onError={() => toast.error("تعذر تشغيل هذا التسجيل؛ تقدر تحمّله وتفتحه على جهازك")}
      />
      <IconButton
        label={playing ? "إيقاف الفويز مؤقتاً" : "تشغيل الفويز"}
        className="voice-play"
        onClick={() => {
          if (playing) audio.current?.pause();
          else void audio.current?.play().catch(() => toast.error("تعذر تشغيل الفويز"));
        }}
      >
        {playing ? <Pause size={18} /> : <Play size={18} />}
      </IconButton>
      <div className="voice-track">
        <span className="voice-caption">
          <Mic size={13} /> رسالة صوتية
        </span>
        <input
          type="range"
          min={0}
          max={Math.max(duration, position, 1)}
          step={0.1}
          value={position}
          aria-label="موضع تشغيل الفويز"
          dir="ltr"
          onChange={(event) => {
            const value = Number(event.target.value);
            if (audio.current) audio.current.currentTime = value;
            setPosition(value);
          }}
        />
        <span className="voice-time" dir="ltr">
          {time(position)} / {time(duration)}
        </span>
      </div>
      <button
        className="voice-speed"
        type="button"
        aria-label={`سرعة الفويز ${speed}`}
        onClick={() => {
          const next = speed === 1 ? 1.5 : speed === 1.5 ? 2 : 1;
          setSpeed(next);
          if (audio.current) audio.current.playbackRate = next;
        }}
        dir="ltr"
      >
        {speed}×
      </button>
    </div>
  );
}

export function MediaMessage({
  item,
  conversationId,
  messageId,
}: {
  item: Attachment;
  conversationId: string;
  messageId: string;
}) {
  const src = useSource();
  const canAnalyze = useCan("messages.send");
  const analysis = useAnalyzeMedia(conversationId);
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [expanded, setExpanded] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const objectUrl = useRef("");
  const mounted = useRef(true);
  const isVisual = item.kind === "image" || item.kind === "video";
  const Icon = item.kind === "video" ? Film : item.kind === "audio" ? Mic : ImageIcon;
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      controller.current?.abort();
      if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
    };
  }, []);
  const load = async () => {
    if (busy || url) return;
    setBusy(true);
    setError("");
    controller.current = new AbortController();
    try {
      const blob = await src.getAttachment(conversationId, messageId, item.id, controller.current.signal);
      if (!mounted.current) return;
      objectUrl.current = URL.createObjectURL(blob);
      setUrl(objectUrl.current);
    } catch (err) {
      if (mounted.current) setError(errorText(err));
    } finally {
      if (mounted.current) setBusy(false);
    }
  };
  const result = item.analysis;
  return (
    <li
      className="message-media"
      aria-label={item.kind === "audio" ? "مرفق صوتي" : item.kind === "video" ? "مرفق فيديو" : "مرفق صورة"}
    >
      <div className="message-media-head">
        <Icon size={17} />
        <span dir="auto">
          {item.name || (item.kind === "audio" ? "فويز" : item.kind === "video" ? "فيديو" : "صورة")}
        </span>
        {item.sizeBytes != null && <small dir="ltr">{(item.sizeBytes / (1024 * 1024)).toFixed(1)} MB</small>}
      </div>
      {url ? (
        <div className="message-media-preview">
          {item.kind === "image" ? (
            <button
              type="button"
              className={expanded ? "media-image is-expanded" : "media-image"}
              onClick={() => setExpanded((value) => !value)}
              aria-label={expanded ? "تصغير الصورة" : "تكبير الصورة"}
            >
              <img src={url} alt={item.name || "صورة من المحادثة"} />
            </button>
          ) : item.kind === "video" ? (
            <video src={url} controls preload="metadata" aria-label="مشغل الفيديو" />
          ) : (
            <AudioPlayer src={url} duration={item.durationSeconds ?? 0} />
          )}
        </div>
      ) : (
        <FinoraButton size="sm" variant="ghost" loading={busy} onClick={() => void load()}>
          <Eye size={15} />{" "}
          {item.kind === "audio"
            ? "تحميل وتشغيل الفويز"
            : item.kind === "video"
              ? "عرض الفيديو"
              : "عرض الصورة"}
        </FinoraButton>
      )}
      {error && (
        <p className="media-error" role="alert">
          {error}
        </p>
      )}
      <div className="message-media-actions">
        {canAnalyze && (
          <FinoraButton
            size="sm"
            variant="ghost"
            disabled={analysis.isPending || result?.status === "completed"}
            loading={analysis.isPending}
            onClick={() =>
              analysis.mutate(
                { messageId, attachmentId: item.id },
                { onError: (err) => toast.error(errorText(err)) },
              )
            }
          >
            <Sparkles size={14} />{" "}
            {result?.status === "processing"
              ? "جارٍ التحليل…"
              : isVisual
                ? "تحليل بالذكاء"
                : "تحويل الفويز لنص"}
          </FinoraButton>
        )}
        {url && (
          <a href={url} download={item.name || "finora-media"} className="media-download">
            <Download size={14} /> تنزيل
          </a>
        )}
      </div>
      {result?.status === "completed" && (
        <div className="media-insight" aria-label="نتيجة تحليل المرفق">
          <span className="media-insight-title">
            <Sparkles size={14} /> {result.summary}
          </span>
          <p dir="auto">{result.details}</p>
          {!!result.frameTimes?.length && (
            <small>اعتمد على {result.frameTimes.length} لقطات من الفيديو، بدون تحليل الصوت.</small>
          )}
          {result.needsHuman && <small>التفاصيل غير واضحة بالكامل؛ تحتاج مراجعة الفريق.</small>}
          <small>
            {result.provider === "local"
              ? "تحليل محلي"
              : result.provider === "cloud"
                ? "تحليل سحابي"
                : "تحليل بالذكاء"}{" "}
            · <span dir="ltr">{result.model}</span>
          </small>
        </div>
      )}
      {result?.status === "failed" && (
        <p className="media-error" role="alert">
          {result.error || "تعذر تحليل المرفق؛ جرّب مرة ثانية"}
        </p>
      )}
    </li>
  );
}
