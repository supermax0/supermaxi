import { AnimatePresence, motion } from "framer-motion";
import {
  AlertCircle,
  ArrowDown,
  Check,
  CheckCheck,
  Clock3,
  FileQuestion,
  FileText,
  Film,
  ImageIcon,
  Mic,
  Smile,
  Hand,
  PanelRightClose,
  PanelRightOpen,
  Play,
  Search,
  SendHorizontal,
  Sparkles,
  X,
} from "lucide-react";
import {
  memo,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import { transitions } from "../design/motion";
import { useCan } from "../data/can";
import {
  useConversations,
  useMessages,
  useSendMessage,
  useSetControl,
  useShadow,
  useSource,
  useStatus,
} from "../data/hooks";
import type { Attachment, Conversation, DeliveryState, Message, ShadowProposal } from "../data/schemas";
import { useUi } from "../state/ui";
import { toast } from "../ui/toast";
import { MediaComposer } from "./MediaComposer";
import { MediaMessage } from "./MediaMessage";
import {
  Avatar,
  CHANNEL_LABEL,
  ChannelIcon,
  EmptyState,
  ErrorState,
  FinoraButton,
  IconButton,
  MiniOrb,
  Skeleton,
  Time,
  cx,
  errorText,
} from "../ui/primitives";

const WORKING = new Set(["message_received", "reading", "thinking", "searching", "replying", "executing"]);
/** Render at most this many messages; older ones load on demand (spec §42: no thousands of DOM nodes). */
const PAGE = 60;
const ALL_QUERY = { channel: "all", filter: "all", search: "" } as const;

function DeliveryIcon({ state }: { state: DeliveryState }) {
  switch (state) {
    case "sending":
      return <Clock3 size={13} aria-label="قيد الإرسال" />;
    case "sent":
      return <Check size={14} aria-label="أُرسلت" />;
    case "delivered":
      return <CheckCheck size={14} aria-label="وصلت" />;
    case "read":
      return <CheckCheck size={14} className="is-read" aria-label="قُرئت" />;
    case "failed":
      return <AlertCircle size={14} className="is-failed" aria-label="فشل الإرسال" />;
  }
}

function highlight(text: string, needle: string) {
  if (!needle) return text;
  const i = text.toLowerCase().indexOf(needle.toLowerCase());
  if (i === -1) return text;
  return (
    <>
      {text.slice(0, i)}
      <mark>{text.slice(i, i + needle.length)}</mark>
      {text.slice(i + needle.length)}
    </>
  );
}

const ATTACHMENT_ICON = {
  image: ImageIcon,
  audio: Mic,
  video: Film,
  document: FileText,
  sticker: Smile,
  unsupported: FileQuestion,
};
const ATTACHMENT_LABEL = {
  image: "صورة",
  audio: "رسالة صوتية",
  video: "فيديو",
  document: "ملف",
  sticker: "ملصق",
  unsupported: "مرفق غير مدعوم",
};
const ATTACHMENT_STATUS = {
  pending: "قيد الحفظ",
  stored: null,
  failed: "تعذر الحفظ",
  unsupported: "غير مدعوم",
  not_downloadable: null,
};

function formatSize(bytes: number | null): string | null {
  if (bytes === null) return null;
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function AttachmentList({
  items,
  conversationId,
  messageId,
}: {
  items: Attachment[];
  conversationId: string;
  messageId: string;
}) {
  return (
    <ul className="msg-attachments" aria-label="المرفقات">
      {items.map((a) => {
        if (a.status === "stored" && ["image", "video", "audio"].includes(a.kind)) {
          return <MediaMessage key={a.id} item={a} conversationId={conversationId} messageId={messageId} />;
        }
        const Icon = ATTACHMENT_ICON[a.kind];
        const status = ATTACHMENT_STATUS[a.status];
        const size = formatSize(a.sizeBytes);
        return (
          <li key={a.id} className={cx("msg-attachment", `is-${a.status}`)}>
            <Icon size={16} aria-hidden="true" />
            <span className="ma-name" dir="auto">
              {a.name ?? ATTACHMENT_LABEL[a.kind]}
            </span>
            {size && (
              <span className="ma-meta" dir="ltr">
                {size}
              </span>
            )}
            {status && <span className="ma-meta">{status}</span>}
          </li>
        );
      })}
    </ul>
  );
}

const Bubble = memo(function Bubble({
  m,
  conv,
  first,
  needle,
}: {
  m: Message;
  conv: Conversation;
  first: boolean;
  needle: string;
}) {
  if (m.sender === "system") {
    return (
      <li className="msg-system" role="note">
        <span>{m.text}</span>
        <Time iso={m.at} />
      </li>
    );
  }
  const inbound = m.sender === "customer";
  return (
    <li className={cx("msg", inbound ? "is-in" : "is-out", `from-${m.sender}`, first && "is-first")}>
      <span className="msg-avatar">
        {first &&
          (inbound ? (
            <Avatar name={conv.customerName} url={conv.avatarUrl} size={40} />
          ) : m.sender === "core" ? (
            <MiniOrb size={40} />
          ) : (
            <span className="human-avatar" aria-hidden="true">
              SA
            </span>
          ))}
      </span>
      <div className="msg-bubble">
        {first && !inbound && (
          <span className="msg-author">
            {m.sender === "core" ? "Finora Core" : (m.authorName ?? "Admin")}
          </span>
        )}
        <p className="msg-text" dir="auto">
          {highlight(m.text, needle)}
        </p>
        {m.attachments && m.attachments.length > 0 && (
          <AttachmentList items={m.attachments} conversationId={conv.id} messageId={m.id} />
        )}
        <span className="msg-meta">
          <Time iso={m.at} />
          {m.delivery && <DeliveryIcon state={m.delivery} />}
        </span>
      </div>
    </li>
  );
});

function Typing() {
  return (
    <motion.li
      className="msg is-out from-core is-first typing"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 4 }}
      transition={transitions.normal}
      aria-label="FINORA CORE يكتب"
    >
      <span className="msg-avatar">
        <MiniOrb size={40} active />
      </span>
      <div className="msg-bubble typing-bubble">
        <i />
        <i />
        <i />
      </div>
    </motion.li>
  );
}

const VERDICT: Record<string, string> = {
  execute: "ينفذ",
  approval: "يطلب موافقة",
  ask: "يسأل أولاً",
  reject: "مرفوض",
};

/** Shadow Mode: FINORA CORE's proposal for the open conversation, next to the human's own reply. Never sent. */
function ShadowStrip({ proposal, onUse }: { proposal: ShadowProposal; onUse: (p: ShadowProposal) => void }) {
  const confidence = proposal.confidence != null ? Math.round(proposal.confidence * 100) : null;
  const human = proposal.human;
  return (
    <section
      className={cx("shadow-strip", human && "is-answered")}
      aria-label="اقتراح FINORA CORE (وضع الظل)"
    >
      <header>
        <Sparkles size={14} />
        <strong>اقتراح FINORA CORE</strong>
        <span className="shadow-tag">وضع الظل — لا يُرسل</span>
        {confidence !== null && <span className="shadow-conf">ثقة {confidence}%</span>}
        {proposal.escalation.proposed && <span className="shadow-esc">يقترح التحويل لموظف</span>}
      </header>
      <p className="shadow-text" dir="auto">
        {proposal.proposedReply}
      </p>
      {proposal.actions.length > 0 && (
        <div className="shadow-actions">
          {proposal.actions.map((a, i) => (
            <span key={i} className={cx("shadow-chip", `is-${a.verdict}`)}>
              {a.tool ?? a.action ?? "—"} · {VERDICT[a.verdict] ?? a.verdict}
            </span>
          ))}
        </div>
      )}
      {human ? (
        <p className="shadow-human">
          رد الموظف: {human.accepted ? "استخدم الاقتراح كما هو" : human.edited ? "عدّل الاقتراح" : "رد مختلف"}
          {human.similarity != null && ` · تشابه ${Math.round(human.similarity * 100)}%`}
        </p>
      ) : (
        <FinoraButton variant="soft" size="sm" onClick={() => onUse(proposal)}>
          استخدام الاقتراح
        </FinoraButton>
      )}
    </section>
  );
}

function Composer({ conv }: { conv: Conversation }) {
  const [mediaBusy, setMediaBusy] = useState(false);
  const [text, setText] = useState("");
  const [usedProposal, setUsedProposal] = useState<string | null>(null);
  const ref = useRef<HTMLTextAreaElement>(null);
  const send = useSendMessage(conv.id);
  const setControl = useSetControl();
  const status = useStatus();
  const shadowMode = status.data?.shadowMode === true;
  const shadow = useShadow(conv.id, shadowMode);
  const latest = shadow.data?.items[0];
  const pending = latest?.status === "pending" ? latest : undefined;
  // In Shadow Mode the agent never sends, so humans answer every conversation.
  const locked = conv.control === "ai" && !shadowMode;
  const canTakeOver = useCan("ai.takeover");
  const canSend = useCan("messages.send");

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "0px";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [text]);

  const submit = () => {
    const body = text.trim();
    if (!body || send.isPending || mediaBusy) return;
    const link = pending ? { proposalId: pending.id, usedProposal: usedProposal === pending.id } : undefined;
    send.mutate(
      { text: body, key: crypto.randomUUID(), shadow: link },
      {
        onSuccess: () => {
          setText("");
          setUsedProposal(null);
        },
        onError: (err) => toast.error(errorText(err)),
      },
    );
  };

  const applyProposal = (p: ShadowProposal) => {
    setText(p.proposedReply);
    setUsedProposal(p.id);
    ref.current?.focus();
  };

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  };

  if (locked) {
    return (
      <div className="composer is-locked">
        <MiniOrb size={26} active />
        <span className="composer-lock-text">
          <strong>FINORA CORE — Active</strong>
          <span>يرد تلقائياً على هذه المحادثة</span>
        </span>
        {canTakeOver && (
          <FinoraButton
            variant="soft"
            size="sm"
            loading={setControl.isPending}
            onClick={() =>
              setControl.mutate(
                { conversationId: conv.id, control: "human" },
                { onError: (err) => toast.error(errorText(err)), onSuccess: () => ref.current?.focus() },
              )
            }
          >
            <Hand size={15} /> استلام المحادثة
          </FinoraButton>
        )}
      </div>
    );
  }

  if (!canSend) {
    return (
      <div className="composer is-locked">
        <span className="composer-lock-text">
          <strong>عرض فقط</strong>
          <span>لا تملك صلاحية إرسال الرسائل</span>
        </span>
      </div>
    );
  }

  return (
    <>
      {shadowMode && latest && latest.status !== "superseded" && (
        <ShadowStrip proposal={latest} onUse={applyProposal} />
      )}
      <div className="composer has-media">
        <div className="composer-text-row">
          <textarea
            ref={ref}
            rows={1}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={onKey}
            placeholder="اكتب رسالتك هنا..."
            aria-label="نص الرسالة"
            dir="auto"
            maxLength={2000}
          />
          <button
            type="button"
            className="send-btn"
            onClick={submit}
            disabled={!text.trim() || send.isPending || mediaBusy}
            aria-label="إرسال"
            aria-busy={send.isPending || undefined}
          >
            {send.isPending ? <span className="spinner is-light" /> : <SendHorizontal size={20} />}
          </button>
        </div>
        <MediaComposer conversationId={conv.id} textSending={send.isPending} onBusyChange={setMediaBusy} />
      </div>
    </>
  );
}

export function ChatPanel() {
  const selectedId = useUi((s) => s.selectedConversationId);
  const panelOpen = useUi((s) => s.customerPanelOpen);
  const open = useUi((s) => s.view === "workspace");
  const togglePanel = useUi((s) => s.toggleCustomerPanel);
  // Unfiltered list: the open conversation must stay resolvable even when the sidebar filter hides it.
  const list = useConversations(ALL_QUERY);
  const conv = list.data?.find((c) => c.id === selectedId) ?? null;
  const msgs = useMessages(selectedId);
  const src = useSource();
  const canTakeOver = useCan("ai.takeover");
  const setControl = useSetControl();
  const scrollRef = useRef<HTMLDivElement>(null);
  const [atBottom, setAtBottom] = useState(true);
  const atBottomRef = useRef(true);
  const listRef = useRef<HTMLOListElement>(null);
  const [limit, setLimit] = useState(PAGE);
  const [findOpen, setFindOpen] = useState(false);
  const [needle, setNeedle] = useState("");

  useEffect(() => {
    setLimit(PAGE);
    setFindOpen(false);
    setNeedle("");
    setAtBottom(true);
    atBottomRef.current = true;
  }, [selectedId]);

  // Only mark read while the admin is actually looking at the conversation.
  useEffect(() => {
    if (!open || !conv || conv.unreadCount === 0) return;
    src.markRead(conv.id).catch((err: unknown) => console.warn("[finora-core] markRead failed", err));
  }, [open, conv, src]);

  const all = msgs.data;
  const visible = useMemo(() => {
    if (!all) return [];
    const base = needle ? all.filter((m) => m.text.toLowerCase().includes(needle.toLowerCase())) : all;
    return base.slice(-limit);
  }, [all, limit, needle]);
  const hidden = (all?.length ?? 0) - visible.length;
  const typing = !!conv && WORKING.has(conv.agentState) && conv.agentState !== "message_received";

  const scrollToBottom = useCallback((smooth: boolean) => {
    const el = scrollRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: smooth ? "smooth" : "auto" });
  }, []);

  // Stick to the bottom when content grows (new messages, typing, fonts, images), unless the admin scrolled up.
  const hasList = visible.length > 0;
  useLayoutEffect(() => {
    const list = listRef.current;
    if (!list) return;
    if (atBottomRef.current) scrollToBottom(false);
    const ro = new ResizeObserver(() => {
      if (atBottomRef.current) scrollToBottom(false);
    });
    ro.observe(list);
    return () => ro.disconnect();
  }, [hasList, selectedId, scrollToBottom]);

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const bottom = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
    atBottomRef.current = bottom;
    setAtBottom(bottom);
  };

  if (!selectedId) {
    return (
      <div className="chat chat-empty">
        <EmptyState title="اختر محادثة" hint="ستظهر الرسائل هنا" icon={<MiniOrb size={56} />} />
      </div>
    );
  }

  return (
    <div className="chat">
      <header className="chat-head">
        {conv ? (
          <>
            <Avatar name={conv.customerName} url={conv.avatarUrl} size={56} />
            <div className="chat-id">
              <h2>
                <bdi>{conv.customerName}</bdi>
              </h2>
              <span className="chat-channel">
                <ChannelIcon channel={conv.channel} size={16} />
                {CHANNEL_LABEL[conv.channel]}
              </span>
              <span className={cx("chat-control", `is-${conv.control}`)}>
                {conv.control === "ai"
                  ? "FINORA CORE — Active"
                  : conv.control === "human"
                    ? `بإدارة ${conv.assignedTo ?? "مشرف"}`
                    : "FINORA CORE متوقف"}
              </span>
            </div>
          </>
        ) : (
          <div className="chat-id">
            <Skeleton w={140} h={16} />
            <Skeleton w={80} h={11} />
          </div>
        )}
        <div className="chat-actions">
          {conv?.control === "human" && canTakeOver && (
            <FinoraButton
              variant="soft"
              size="sm"
              loading={setControl.isPending}
              onClick={() =>
                setControl.mutate(
                  { conversationId: conv.id, control: "ai" },
                  {
                    onError: (err) => toast.error(errorText(err)),
                    onSuccess: () => toast.success("تمت إعادة تشغيل FINORA CORE"),
                  },
                )
              }
            >
              <Play size={14} /> إعادة تشغيل FINORA CORE
            </FinoraButton>
          )}
          <IconButton
            label="البحث في المحادثة"
            className={cx(findOpen && "is-active")}
            onClick={() => setFindOpen((o) => !o)}
          >
            <Search size={20} />
          </IconButton>
          <IconButton
            label={panelOpen ? "إخفاء ملف العميل" : "إظهار ملف العميل"}
            onClick={() => togglePanel()}
          >
            {panelOpen ? <PanelRightClose size={20} /> : <PanelRightOpen size={20} />}
          </IconButton>
        </div>
      </header>

      <AnimatePresence initial={false}>
        {findOpen && (
          <motion.div
            className="chat-find"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={transitions.normal}
          >
            <label className="field">
              <Search size={16} aria-hidden="true" />
              <input
                autoFocus
                value={needle}
                onChange={(e) => setNeedle(e.target.value)}
                placeholder="ابحث في هذه المحادثة"
                aria-label="ابحث في هذه المحادثة"
              />
              <button
                type="button"
                className="field-clear"
                aria-label="إغلاق البحث"
                onClick={() => (setNeedle(""), setFindOpen(false))}
              >
                <X size={14} />
              </button>
            </label>
          </motion.div>
        )}
      </AnimatePresence>

      <div className="chat-scroll" ref={scrollRef} onScroll={onScroll}>
        {msgs.isPending ? (
          <div className="chat-skel" aria-busy="true">
            <Skeleton w="46%" h={56} r={18} />
            <Skeleton w="58%" h={120} r={18} />
            <Skeleton w="38%" h={48} r={18} />
          </div>
        ) : msgs.isError ? (
          <ErrorState error={msgs.error} onRetry={() => void msgs.refetch()} />
        ) : visible.length === 0 ? (
          <EmptyState title={needle ? "لا توجد رسائل مطابقة" : "لا توجد رسائل بعد"} />
        ) : (
          <ol className="msg-list" aria-label="الرسائل" ref={listRef}>
            {hidden > 0 && !needle && (
              <li className="msg-more">
                <button type="button" onClick={() => setLimit((l) => l + PAGE)}>
                  عرض رسائل أقدم ({hidden})
                </button>
              </li>
            )}
            {conv &&
              visible.map((m, i) => {
                const prev = visible[i - 1];
                return (
                  <Bubble
                    key={m.id}
                    m={m}
                    conv={conv}
                    first={!prev || prev.sender !== m.sender}
                    needle={needle}
                  />
                );
              })}
            <AnimatePresence>{typing && <Typing key="typing" />}</AnimatePresence>
          </ol>
        )}
      </div>

      <AnimatePresence>
        {!atBottom && (
          <motion.button
            type="button"
            className="jump-bottom"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 8 }}
            transition={transitions.fast}
            onClick={() => {
              atBottomRef.current = true;
              scrollToBottom(true);
            }}
            aria-label="الانتقال إلى آخر رسالة"
          >
            <ArrowDown size={16} />
          </motion.button>
        )}
      </AnimatePresence>

      {conv && <Composer key={conv.id} conv={conv} />}
    </div>
  );
}
