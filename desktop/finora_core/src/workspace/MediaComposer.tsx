import { Film, ImageIcon, Mic, Paperclip, SendHorizontal, Square, Trash2, X } from "lucide-react";
import { useEffect, useRef, useState, type ChangeEvent } from "react";
import { useSendMedia } from "../data/hooks";
import { FinoraButton, IconButton, errorText } from "../ui/primitives";
import { toast } from "../ui/toast";
import { AudioPlayer } from "./MediaMessage";

const MIME = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/mp4"];
const ACCEPT =
  "image/jpeg,image/png,image/webp,image/gif,video/mp4,video/quicktime,video/webm,audio/mpeg,audio/mp4,audio/ogg,audio/webm,audio/wav,audio/aac";
export function clockTime(seconds: number) {
  return `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;
}

export function MediaComposer({
  conversationId,
  textSending,
  onBusyChange,
}: {
  conversationId: string;
  textSending: boolean;
  onBusyChange: (busy: boolean) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState("");
  const [recording, setRecording] = useState(false);
  const [starting, setStarting] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [draftDuration, setDraftDuration] = useState(0);
  const recordingStarted = useRef(0);
  const input = useRef<HTMLInputElement>(null);
  const key = useRef("");
  const recorder = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const discard = useRef(false);
  const mounted = useRef(true);
  const media = useSendMedia(conversationId);
  const busy = textSending || media.isPending || starting;

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      discard.current = true;
      if (recorder.current?.state === "recording") recorder.current.stop();
      stream.current?.getTracks().forEach((track) => track.stop());
    };
  }, []);
  useEffect(() => {
    onBusyChange(media.isPending || recording || starting);
    return () => onBusyChange(false);
  }, [media.isPending, recording, starting, onBusyChange]);
  useEffect(() => {
    if (!file) {
      setPreview("");
      return;
    }
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);
  useEffect(() => {
    if (!recording) return;
    const timer = window.setInterval(() => setSeconds((value) => value + 1), 1000);
    return () => window.clearInterval(timer);
  }, [recording]);
  useEffect(() => {
    if (recording && seconds >= 180 && recorder.current?.state === "recording") recorder.current.stop();
  }, [seconds, recording]);

  const choose = (value: File) => {
    if (busy || recording) return;
    if (!ACCEPT.split(",").includes(value.type)) {
      toast.error("صيغة الملف غير مدعومة؛ اختَر صورة أو فيديو أو صوتاً");
      return;
    }
    const maximum = (value.type.startsWith("image/") ? 10 : 25) * 1024 * 1024;
    if (!value.size || value.size > maximum) {
      toast.error(`الملف فارغ أو يتجاوز ${maximum / (1024 * 1024)} MB`);
      return;
    }
    key.current = crypto.randomUUID();
    setDraftDuration(0);
    setFile(value);
  };
  const picked = (event: ChangeEvent<HTMLInputElement>) => {
    if (event.target.files?.[0]) choose(event.target.files[0]);
    event.target.value = "";
  };
  const start = async () => {
    if (busy || recording || file) return;
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      toast.error("التسجيل غير متاح؛ تقدر ترفق ملفاً صوتياً من جهازك");
      return;
    }
    setStarting(true);
    try {
      const captured = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true },
        video: false,
      });
      if (!mounted.current) {
        captured.getTracks().forEach((track) => track.stop());
        return;
      }
      stream.current = captured;
      const mime = MIME.find((type) => MediaRecorder.isTypeSupported(type));
      if (!mime) throw new Error("صيغة تسجيل مناسبة غير متاحة؛ ارفق ملفاً صوتياً من جهازك");
      const active = new MediaRecorder(captured, { mimeType: mime, audioBitsPerSecond: 96_000 });
      recorder.current = active;
      discard.current = false;
      const chunks: BlobPart[] = [];
      active.ondataavailable = (event) => {
        if (event.data.size) chunks.push(event.data);
      };
      active.onstop = () => {
        captured.getTracks().forEach((track) => track.stop());
        stream.current = null;
        if (!mounted.current) return;
        setRecording(false);
        if (!discard.current && chunks.length) {
          const type = mime.split(";")[0];
          const extension = type === "audio/ogg" ? "ogg" : type === "audio/mp4" ? "m4a" : "webm";
          const voice = new File(chunks, `finora-voice-${Date.now()}.${extension}`, { type });
          if (voice.size > 25 * 1024 * 1024) {
            toast.error("التسجيل كبير جداً؛ جرّب تسجيلاً أقصر");
            return;
          }
          key.current = crypto.randomUUID();
          setDraftDuration((performance.now() - recordingStarted.current) / 1000);
          setFile(voice);
        }
      };
      active.onerror = () => {
        discard.current = true;
        captured.getTracks().forEach((track) => track.stop());
        if (!mounted.current) return;
        setRecording(false);
        toast.error("توقف تسجيل الصوت؛ جرّب مرة ثانية");
      };
      setSeconds(0);
      setRecording(true);
      recordingStarted.current = performance.now();
      active.start(250);
    } catch (error) {
      stream.current?.getTracks().forEach((track) => track.stop());
      stream.current = null;
      if (mounted.current)
        toast.error(
          error instanceof DOMException && error.name === "NotAllowedError"
            ? "اسمح بالمايكروفون من إعدادات الجهاز حتى تسجل فويز"
            : errorText(error),
        );
    } finally {
      if (mounted.current) setStarting(false);
    }
  };
  const stop = (cancel: boolean) => {
    discard.current = cancel;
    if (recorder.current?.state === "recording") recorder.current.stop();
  };
  const send = () => {
    if (!file || busy || recording) return;
    media.mutate(
      { file, key: key.current },
      {
        onSuccess: (message) => {
          setFile(null);
          toast.success(
            message.delivery === "sending" ? "المرفق قيد الإرسال؛ تابع حالته بالمحادثة" : "تم إرسال المرفق",
          );
        },
        onError: (error) => toast.error(errorText(error)),
      },
    );
  };
  const FileIcon = file?.type.startsWith("image/") ? ImageIcon : file?.type.startsWith("video/") ? Film : Mic;
  return (
    <div
      className="media-composer"
      onDragOver={(event) => event.preventDefault()}
      onDrop={(event) => {
        event.preventDefault();
        if (event.dataTransfer.files[0]) choose(event.dataTransfer.files[0]);
      }}
      onPaste={(event) => {
        if (event.clipboardData.files[0]) {
          event.preventDefault();
          choose(event.clipboardData.files[0]);
        }
      }}
    >
      <input
        ref={input}
        className="media-file-input"
        type="file"
        accept={ACCEPT}
        onChange={picked}
        aria-label="اختيار صورة أو فيديو أو صوت"
      />
      {recording ? (
        <div className="voice-recording" role="status">
          <span className="voice-live-dot" />
          <Mic size={17} />
          <strong>نسجل الفويز…</strong>
          <time dir="ltr">{clockTime(seconds)} / 3:00</time>
          <IconButton label="إلغاء التسجيل" onClick={() => stop(true)}>
            <X size={17} />
          </IconButton>
          <FinoraButton size="sm" variant="soft" onClick={() => stop(false)}>
            <Square size={14} /> إيقاف ومعاينة
          </FinoraButton>
        </div>
      ) : (
        <div className="media-toolbar">
          <IconButton
            label="إرفاق صورة أو فيديو أو صوت"
            onClick={() => input.current?.click()}
            disabled={busy}
          >
            <Paperclip size={18} />
          </IconButton>
          <IconButton
            label="تسجيل فويز"
            onClick={() => void start()}
            disabled={busy || !!file}
            aria-busy={starting || undefined}
          >
            <Mic size={18} />
          </IconButton>
          <span>{media.isPending ? "جارٍ تجهيز المرفق وإرساله…" : "صورة، فيديو أو فويز"}</span>
          <small>اسحب المرفق هنا</small>
        </div>
      )}
      {file && (
        <div className="media-draft" aria-label="معاينة المرفق قبل الإرسال">
          {preview &&
            (file.type.startsWith("image/") ? (
              <img src={preview} alt="الصورة المختارة" />
            ) : file.type.startsWith("video/") ? (
              <video src={preview} controls preload="metadata" />
            ) : (
              <AudioPlayer src={preview} duration={draftDuration} />
            ))}
          <div className="media-draft-info">
            <FileIcon size={17} />
            <span dir="auto">{file.name}</span>
            <small dir="ltr">{(file.size / (1024 * 1024)).toFixed(1)} MB</small>
            <IconButton
              label="حذف المرفق قبل الإرسال"
              disabled={media.isPending}
              onClick={() => setFile(null)}
            >
              <Trash2 size={15} />
            </IconButton>
          </div>
          <div className="media-draft-actions">
            <small>المرفق يُرسل وحده؛ نصك يبقى جاهزاً للإرسال.</small>
            <FinoraButton
              size="sm"
              variant="primary"
              loading={media.isPending}
              disabled={busy}
              onClick={send}
            >
              <SendHorizontal size={15} /> إرسال المرفق
            </FinoraButton>
          </div>
        </div>
      )}
    </div>
  );
}
