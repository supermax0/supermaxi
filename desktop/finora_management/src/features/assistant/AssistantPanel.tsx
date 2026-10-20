import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  Bot,
  GraduationCap,
  Search,
  Settings2,
  X,
  Send,
  Square,
  Mic,
  ImagePlus,
  Trash2,
  ExternalLink,
  FileText,
  RefreshCw,
  HelpCircle,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { ConfirmDialog } from "@/components/Dialog";
import { desktopBridge } from "@/services/bridge";
import { useSession } from "@/stores/session";
import { overlayOpen, useUi } from "@/stores/ui";
import { useWorkspace, sessionScope } from "@/features/workspace/state";
import { openWorkspaceTarget } from "@/features/workspace/navigation";
import { useWindowManager } from "@/stores/windowManager";
import { toast } from "@/stores/toasts";
import { useAssistant, type AssistantSource, type AssistantProposal } from "./state";
import {
  cancelAssistant,
  currentAssistantScope,
  currentPageContext,
  getAssistantTools,
  readAssistantTool,
  rowsFromData,
  rowTarget,
  sendAssistant,
  sourceLabel,
} from "./engine";
import { GUIDES, availableGuides, searchGuides } from "./catalog";
import { startTraining, trainingProgress, TrainingOverlay } from "./Training";
import { prepareAssistantImage, recordingToWav } from "./media";
import { useAssistantDraft } from "./draftQueue";
import { PreparedDraftCard } from "./drafts";
import "./assistant.css";

function AssistantSources({ sources, expanded = false }: { sources: AssistantSource[]; expanded?: boolean }) {
  return (
    <div className="assistant-sources">
      {sources.map((source, i) => (
        <details key={`${source.name}-${i}`} open={expanded || undefined}>
          <summary>
            <FileText size={14} />
            {source.title}
            <small>
              {new Date(source.at).toLocaleTimeString("ar-IQ", { hour: "2-digit", minute: "2-digit" })}
            </small>
          </summary>
          <p className="assistant-muted">
            مصدر: أدوات فينورا الأصلية · النطاق الحالي · {new Date(source.at).toLocaleDateString("ar-IQ")}
          </p>
          {Object.keys(source.arguments).length > 0 && (
            <p className="assistant-muted" dir="auto">
              الفلاتر: {JSON.stringify(source.arguments)}
            </p>
          )}
          {rowsFromData(source.data)
            .slice(0, 10)
            .map((row, index) => {
              const target = rowTarget(source, row);
              return (
                <div className="assistant-record" key={index}>
                  <span>
                    {String(
                      row.name ??
                        row.customer_name ??
                        row.title ??
                        row.invoice_number ??
                        row.number ??
                        `سجل ${row.id ?? index + 1}`,
                    )}
                  </span>
                  {target && (
                    <button className="workspace-button" onClick={() => openWorkspaceTarget(target)}>
                      <ExternalLink size={13} />
                      فتح
                    </button>
                  )}
                </div>
              );
            })}
          <pre dir="auto">{JSON.stringify(source.data, null, 2).slice(0, 14000)}</pre>
        </details>
      ))}
    </div>
  );
}
function Proposal({ proposal }: { proposal: AssistantProposal }) {
  if (proposal.kind === "prepare") return <PreparedDraftCard proposal={proposal} />;
  return (
    <button
      className="assistant-proposal"
      onClick={() => {
        if (proposal.target) openWorkspaceTarget(proposal.target);
      }}
    >
      <ExternalLink size={16} />
      {proposal.title}
    </button>
  );
}
function GuideBrowser() {
  const [query, setQuery] = useState("");
  const active = useWindowManager((s) => s.active);
  const [expanded, setExpanded] = useState<string | null>(null);
  const progress = trainingProgress();
  return (
    <div className="assistant-learn">
      <label className="assistant-search">
        <Search size={16} />
        <input
          aria-label="بحث دليل فينورا"
          placeholder="شلون أضيف منتج؟ شلون أسوي سند؟"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </label>
      <p className="assistant-muted">
        الدليل مدمج مع نسخة البرنامج، ويعمل بدون تشغيل نموذج. تقدّم التعليم محفوظ لهذا الحساب والنطاق.
      </p>
      {(query
        ? searchGuides(query, active)
        : availableGuides().sort((a, b) => Number(b.window === active) - Number(a.window === active))
      ).map((guide) => (
        <article className="assistant-guide" key={guide.id}>
          <button
            className="assistant-guide-title"
            aria-expanded={expanded === guide.id}
            onClick={() => setExpanded(expanded === guide.id ? null : guide.id)}
          >
            <GraduationCap size={18} />
            <strong>{guide.title}</strong>
            <small>
              {progress[guide.id]
                ? `${Math.min(progress[guide.id] ?? 0, guide.steps.length)}/${guide.steps.length}`
                : `${guide.steps.length} خطوات`}
            </small>
          </button>
          {expanded === guide.id && (
            <ol>
              {guide.steps.map((step, index) => (
                <li key={index}>
                  <b>{step.title}</b>
                  <p>{step.text}</p>
                </li>
              ))}
            </ol>
          )}
          <div className="assistant-guide-actions">
            <button className="workspace-button" onClick={() => startTraining(guide)}>
              علّمني خطوة بخطوة
            </button>
            <button
              className="workspace-button"
              onClick={() => openWorkspaceTarget({ window: guide.window })}
            >
              فتح القسم
            </button>
          </div>
        </article>
      ))}
    </div>
  );
}
function DataSearch() {
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState("search_customer");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [source, setSource] = useState<AssistantSource | null>(null);
  const tools = useQuery({
    queryKey: ["assistant", "catalog", useAssistant((s) => s.scope)],
    queryFn: getAssistantTools,
    staleTime: 30_000,
    retry: false,
  });
  const kinds = [
    "search_customer",
    "search_orders",
    "search_products",
    "search_supplier",
    "search_delivery_agents",
  ].filter((name) => tools.data?.tools.some((t) => t.name === name));
  const selected = kinds.includes(kind) ? kind : (kinds[0] ?? "");
  return (
    <div className="assistant-learn">
      <p className="assistant-muted">بحث مباشر من أدوات فينورا ضمن صلاحيات حسابك. ما يحتاج نموذجاً لغوياً.</p>
      <form
        className="assistant-data-search"
        data-nontransactional
        onSubmit={(e) => {
          e.preventDefault();
          if (!selected || !query.trim() || busy) return;
          setBusy(true);
          setError("");
          setSource(null);
          const scope = currentAssistantScope();
          void readAssistantTool(selected, { query: query.trim(), limit: 10 }, tools.data?.scope ?? "", scope)
            .then(
              (value) => {
                if (scope === currentAssistantScope()) setSource(value);
              },
              (reason: unknown) => {
                if (scope === currentAssistantScope())
                  setError(reason instanceof Error ? reason.message : "تعذر البحث");
              },
            )
            .finally(() => setBusy(false));
        }}
      >
        <select aria-label="نوع بحث المساعد" value={selected} onChange={(e) => setKind(e.target.value)}>
          {kinds.map((name) => (
            <option key={name} value={name}>
              {sourceLabel(name)}
            </option>
          ))}
        </select>
        <input
          aria-label="البحث ببيانات فينورا"
          value={query}
          maxLength={150}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="اسم أو رقم أو باركود…"
        />
        <button className="workspace-button" disabled={busy || !selected || !query.trim()}>
          {busy ? "أبحث…" : "بحث"}
        </button>
      </form>
      {(tools.isError || error) && (
        <p role="alert" className="assistant-error">
          {error || (tools.error instanceof Error ? tools.error.message : "الأدوات غير متاحة")}
          <button className="workspace-button" onClick={() => void tools.refetch()}>
            إعادة المحاولة
          </button>
        </p>
      )}
      {source && (
        <>
          <p className="assistant-muted">حدد السجل الصحيح إذا تشابهت الأسماء.</p>
          <AssistantSources sources={[source]} expanded />
        </>
      )}
    </div>
  );
}
function Composer() {
  const busy = useAssistant((s) => s.busy),
    settings = useAssistant((s) => s.settings),
    prompt = useAssistant((s) => s.prompt);
  const [image, setImage] = useState<string | undefined>();
  const [working, setWorking] = useState(false);
  const [recording, setRecording] = useState(false);
  const file = useRef<HTMLInputElement>(null),
    recorder = useRef<MediaRecorder | null>(null),
    stream = useRef<MediaStream | null>(null),
    timer = useRef<number | undefined>();
  const disposed = useRef(false);
  useEffect(() => {
    disposed.current = false;
    return () => {
      disposed.current = true;
      clearTimeout(timer.current);
      if (recorder.current?.state === "recording") recorder.current.stop();
      stream.current?.getTracks().forEach((t) => t.stop());
    };
  }, []);
  const voice = async () => {
    if (recording) {
      recorder.current?.stop();
      return;
    }
    if (!settings.speech) {
      useUi.getState().openAssistantSettings();
      return;
    }
    try {
      const media = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (disposed.current) {
        media.getTracks().forEach((t) => t.stop());
        return;
      }
      stream.current = media;
      const next = new MediaRecorder(media);
      recorder.current = next;
      const parts: BlobPart[] = [];
      next.ondataavailable = (e) => {
        if (e.data.size) parts.push(e.data);
      };
      next.onstop = () => {
        clearTimeout(timer.current);
        media.getTracks().forEach((t) => t.stop());
        if (disposed.current) return;
        setRecording(false);
        setWorking(true);
        void recordingToWav(new Blob(parts, { type: next.mimeType }))
          .then(async (data) => {
            const text = await desktopBridge().assistant?.transcribe({ data, type: "audio/wav" });
            if (!disposed.current && text)
              useAssistant.setState((s) => ({ prompt: [s.prompt, text].filter(Boolean).join("\n") }));
          })
          .catch((e: unknown) => {
            if (!disposed.current) toast.error(e instanceof Error ? e.message : "تعذر تفريغ الصوت محلياً");
          })
          .finally(() => {
            if (!disposed.current) setWorking(false);
          });
      };
      next.start();
      setRecording(true);
      timer.current = window.setTimeout(() => {
        if (next.state === "recording") next.stop();
      }, 60_000);
    } catch (error) {
      stream.current?.getTracks().forEach((t) => t.stop());
      toast.error(error instanceof Error ? error.message : "تعذر تشغيل الميكروفون");
    }
  };
  const submit = () => {
    if (!prompt.trim() || busy || working || recording) return;
    void sendAssistant(prompt, image);
    setImage(undefined);
  };
  return (
    <form
      className="assistant-composer"
      data-nontransactional
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      {image && (
        <div className="assistant-image-preview">
          <img alt="الصورة المرفقة" src={`data:image/jpeg;base64,${image}`} />
          <button type="button" aria-label="إزالة الصورة" onClick={() => setImage(undefined)}>
            <X size={16} />
          </button>
          <small>تُرسل للخدمة المحلية عند إرسال السؤال.</small>
        </div>
      )}
      <textarea
        aria-label="سؤال مساعد فينورا"
        placeholder={
          recording
            ? "جاري التسجيل… اضغط إيقاف"
            : working
              ? "أجهّز الملف محلياً…"
              : "اسأل، أو اطلب شرحاً أو تجهيز مسودة…"
        }
        value={prompt}
        maxLength={8000}
        disabled={busy || working || recording}
        onChange={(e) => useAssistant.setState({ prompt: e.target.value })}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            submit();
          }
        }}
      />
      <div className="assistant-composer-actions">
        <input
          type="file"
          ref={file}
          className="hidden"
          accept="image/png,image/jpeg,image/webp"
          onChange={(e) => {
            const selected = e.target.files?.[0];
            e.target.value = "";
            if (!selected) return;
            setWorking(true);
            void prepareAssistantImage(selected)
              .then(
                (value) => {
                  if (!disposed.current) setImage(value);
                },
                (error: unknown) => toast.error(error instanceof Error ? error.message : "تعذر تجهيز الصورة"),
              )
              .finally(() => {
                if (!disposed.current) setWorking(false);
              });
          }}
        />
        <button
          type="button"
          aria-label="إرفاق صورة للمساعد"
          title={settings.vision ? "إرفاق صورة للنموذج المحلي" : "فعّل نموذج رؤية من الإعدادات"}
          disabled={busy || working || recording}
          onClick={() => {
            if (settings.vision) file.current?.click();
            else useUi.getState().openAssistantSettings();
          }}
        >
          <ImagePlus size={18} />
        </button>
        <button
          type="button"
          aria-label={recording ? "إيقاف التسجيل" : "تسجيل سؤال صوتي محلي"}
          disabled={busy || working}
          onClick={() => void voice()}
        >
          {recording ? <Square size={18} /> : <Mic size={18} />}
        </button>
        <small>
          {recording
            ? "التسجيل محلي · أقصى مدة دقيقة"
            : settings.enabled
              ? `${settings.provider === "ollama" ? "Ollama" : "LM Studio"} · ${settings.model || "اختر نموذجاً"}`
              : "الدليل جاهز · فعّل نموذجاً للأسئلة المفتوحة"}
        </small>
        {busy ? (
          <button type="button" aria-label="إيقاف إجابة المساعد" onClick={() => void cancelAssistant()}>
            <Square size={18} />
          </button>
        ) : (
          <button aria-label="إرسال سؤال المساعد" disabled={!prompt.trim() || working || recording}>
            <Send size={18} />
          </button>
        )}
      </div>
    </form>
  );
}
export function AssistantShell() {
  const state = useAssistant();
  const session = useSession((s) => s.session);
  const identity = useWorkspace((s) => s.identity);
  const scope = JSON.stringify([identity, sessionScope(session)]);
  const [clear, setClear] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);
  const historyEpoch = useRef(0);
  const settings = useQuery({
    queryKey: ["local-assistant", "settings"],
    queryFn: async () => desktopBridge().assistant?.settings() ?? null,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });
  useEffect(() => {
    if (settings.data)
      useAssistant.setState({ settings: settings.data.settings, hasToken: settings.data.hasToken });
  }, [settings.data]);
  useEffect(() => {
    void cancelAssistant().catch((error: unknown) => console.warn("[assistant] cancel failed", error));
    useAssistantDraft.setState({ pending: null });
    useAssistant.getState().reset(scope);
    return () => {
      void cancelAssistant().catch((error: unknown) => console.warn("[assistant] cancel failed", error));
    };
  }, [scope]);
  useEffect(() => {
    let disposed = false;
    const epoch = ++historyEpoch.current;
    if (useSession.getState().session && identity && settings.data?.settings.remember)
      void desktopBridge()
        .assistant?.historyLoad()
        .then(
          (saved) => {
            if (disposed || epoch !== historyEpoch.current || scope !== currentAssistantScope()) return;
            useAssistant.setState((current) => ({
              vaultScope: saved.scope,
              ...(!current.messages.length
                ? {
                    messages: saved.rows.map((row) => ({
                      id: crypto.randomUUID(),
                      role: row.role,
                      text: row.text,
                      at: row.at,
                      restored: true,
                    })),
                  }
                : {}),
            }));
          },
          () => {
            if (!disposed && epoch === historyEpoch.current)
              useAssistant.setState({
                error: "تعذر فتح المحادثة المشفرة؛ تقدر تكمل بمحادثة الجلسة الحالية.",
              });
          },
        );
    return () => {
      disposed = true;
    };
  }, [scope, session?.user.id, identity, settings.data?.settings.remember]);
  useEffect(() => {
    if (state.open) bottom.current?.scrollIntoView({ block: "end", behavior: "auto" });
  }, [state.messages.length, state.open, state.busy]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const assistant = useAssistant.getState();
      if (e.key === "Escape" && !overlayOpen() && (assistant.open || assistant.training)) {
        e.preventDefault();
        e.stopImmediatePropagation();
        if (assistant.open) assistant.close();
        else useAssistant.setState({ training: null });
        return;
      }
      if (
        assistant.open &&
        (e.ctrlKey || e.metaKey) &&
        ["s", "enter"].includes(e.key.toLowerCase()) &&
        (e.target as Element | null)?.closest?.(".finora-assistant-panel")
      ) {
        e.preventDefault();
        e.stopImmediatePropagation();
        return;
      }
      if (e.ctrlKey && e.shiftKey && e.code === "KeyA") {
        e.preventDefault();
        useAssistant.setState((s) => ({ open: !s.open }));
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, []);
  const diagnose = () => {
    const active = useWindowManager.getState().active;
    const root = active ? document.querySelector(`[data-window="${active}"]`) : null;
    const alert = Array.from(root?.querySelectorAll('[role="alert"]') ?? [])
      .filter((e) => !!e.getClientRects().length)
      .map((e) => e.textContent?.slice(0, 600))
      .filter(Boolean)
      .slice(0, 2)
      .join("\n");
    useAssistant
      .getState()
      .show(
        alert
          ? `اشرح هذا الخطأ في ${currentPageContext().page} واقترح خطوات تحقق. اذكر فقط السبب المؤكد ولا تفترض سبباً بلا دليل:\n${alert}`
          : `اشرح خطوات ${currentPageContext().page} والأخطاء الشائعة فيه من الدليل؛ لا يوجد خطأ ظاهر محدد الآن.`,
      );
  };
  return (
    <>
      <button
        className="finora-assistant-dock"
        aria-label="فتح مساعد فينورا"
        title="مساعد فينورا · Ctrl+Shift+A"
        onClick={() => useAssistant.setState((s) => ({ open: !s.open }))}
      >
        <Bot size={24} />
        <span>المساعد</span>
      </button>
      {state.open &&
        state.scope === scope &&
        createPortal(
          <aside role="complementary" aria-label="مساعد فينورا" className="finora-assistant-panel" dir="rtl">
            <header>
              <span className="assistant-logo">
                <Bot size={23} />
              </span>
              <div>
                <h2>مساعد فينورا</h2>
                <small>
                  {currentPageContext().page} · {state.settings.enabled ? "ذكاء محلي" : "الدليل والتعليم"}
                </small>
              </div>
              <button
                aria-label="إعدادات المساعد المحلي"
                onClick={() => useUi.getState().openAssistantSettings()}
              >
                <Settings2 size={19} />
              </button>
              <button aria-label="إغلاق مساعد فينورا" onClick={() => useAssistant.getState().close()}>
                <X size={20} />
              </button>
            </header>
            <nav aria-label="أقسام المساعد">
              {(
                [
                  ["chat", "المحادثة", Bot],
                  ["learn", "علّمني", GraduationCap],
                  ["search", "بحث البيانات", Search],
                ] as const
              ).map(([tab, label, Icon]) => (
                <button
                  key={tab}
                  aria-pressed={state.tab === tab}
                  onClick={() => useAssistant.setState({ tab })}
                >
                  <Icon size={16} />
                  {label}
                </button>
              ))}
            </nav>
            <div className="assistant-panel-content" key={`${scope}:${state.tab}`}>
              {state.tab === "learn" ? (
                <GuideBrowser />
              ) : state.tab === "search" ? (
                <DataSearch />
              ) : (
                <>
                  {!state.messages.length && (
                    <div className="assistant-welcome">
                      <Bot size={34} />
                      <h3>شلون أساعدك بشغلك؟</h3>
                      <p>أشرح الخطوات، أبحث ضمن صلاحياتك، وأجهّز مقترحات للمراجعة.</p>
                      <div>
                        {[
                          "علّمني أضيف منتج",
                          "اعرض ملخص بداية الدوام",
                          "ابحث عن عميل",
                          "ليش المنتج ما ظاهر بالمتجر؟",
                        ].map((text) => (
                          <button
                            key={text}
                            onClick={() => {
                              if (text.startsWith("علّمني")) useAssistant.setState({ tab: "learn" });
                              else useAssistant.getState().show(text);
                            }}
                          >
                            {text}
                          </button>
                        ))}
                      </div>
                      <button
                        className="workspace-button"
                        onClick={() => useUi.getState().openAssistantSettings()}
                      >
                        <Settings2 size={15} />
                        ربط Ollama أو LM Studio
                      </button>
                    </div>
                  )}
                  {state.messages.map((message) => (
                    <article
                      key={message.id}
                      className={`assistant-message assistant-message-${message.role}`}
                    >
                      <small>
                        {message.role === "user" ? "أنت" : "فينورا"} ·{" "}
                        {new Date(message.at).toLocaleTimeString("ar-IQ", {
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                        {message.restored ? " · محفوظة، حدّث الأرقام قبل الاعتماد عليها" : ""}
                      </small>
                      <div className="assistant-message-text" dir="auto">
                        {message.text}
                      </div>
                      {message.guides?.map((id) => {
                        const guide = GUIDES.find((g) => g.id === id);
                        return guide ? (
                          <button
                            className="assistant-proposal"
                            key={id}
                            onClick={() => startTraining(guide)}
                          >
                            <GraduationCap size={16} />
                            {guide.title}
                          </button>
                        ) : null;
                      })}
                      {message.sources && <AssistantSources sources={message.sources} />}
                      {message.proposals?.map((proposal, i) => (
                        <Proposal key={i} proposal={proposal} />
                      ))}
                    </article>
                  ))}
                  {state.busy && (
                    <p role="status" className="assistant-status">
                      <RefreshCw size={15} className="animate-spin" />
                      {state.status}
                    </p>
                  )}
                  {state.error && (
                    <div role="alert" className="assistant-error">
                      {state.error}
                      <button
                        className="workspace-button"
                        onClick={() => useUi.getState().openAssistantSettings()}
                      >
                        إعدادات الربط
                      </button>
                    </div>
                  )}
                  <div ref={bottom} />
                </>
              )}
            </div>
            {state.tab === "chat" && (
              <>
                <div className="assistant-chat-tools">
                  <button onClick={diagnose}>
                    <HelpCircle size={14} />
                    اشرح الصفحة / الخطأ
                  </button>
                  <button disabled={!state.messages.length || state.busy} onClick={() => setClear(true)}>
                    <Trash2 size={14} />
                    مسح المحادثة
                  </button>
                </div>
                <Composer key={scope} />
              </>
            )}
            <ConfirmDialog
              open={clear}
              title="مسح محادثة المساعد"
              message="يمسح محادثة هذا الحساب ونطاقه من الجلسة، ومن الحفظ المحلي إذا كان متاحاً. تقدم التعليم يبقى محفوظاً."
              onClose={() => setClear(false)}
              confirmLabel="مسح المحادثة"
              onConfirm={() => {
                const vaultScope = state.vaultScope;
                historyEpoch.current++;
                useAssistant.setState({ messages: [], error: "" });
                setClear(false);
                const bridge = desktopBridge().assistant;
                if (bridge)
                  void (async () => {
                    const expectedScope = vaultScope || (await bridge.historyLoad()).scope;
                    if (scope !== currentAssistantScope()) return;
                    await bridge.historySave({ expectedScope, rows: [] });
                  })().catch(() => {
                    if (scope === currentAssistantScope())
                      toast.error(
                        "مُسحت الجلسة، لكن تعذر حذف النسخة المحلية. أعد المحاولة عند اتصال الخادم.",
                      );
                  });
              }}
            />
          </aside>,
          document.body,
        )}
      {state.scope === scope && <TrainingOverlay />}
    </>
  );
}
