import { AnimatePresence, motion } from "framer-motion";
import { Check, Search, SlidersHorizontal, Sparkles, X } from "lucide-react";
import { memo, useDeferredValue, useEffect, useRef, useState } from "react";
import { transitions } from "../design/motion";
import { useConversations } from "../data/hooks";
import { LEAD_STAGE_META } from "../data/leadStages";
import type { Conversation } from "../data/schemas";
import type { ConversationFilter } from "../data/source";
import { useUi } from "../state/ui";
import {
  Avatar,
  Badge,
  CHANNEL_LABEL,
  ChannelIcon,
  EmptyState,
  ErrorState,
  Skeleton,
  Time,
  cx,
} from "../ui/primitives";

const WORKING = new Set(["message_received", "reading", "thinking", "searching", "replying", "executing"]);

const FILTERS: { key: ConversationFilter; label: string }[] = [
  { key: "all", label: "الكل" },
  { key: "unread", label: "غير مقروءة" },
  { key: "ai_active", label: "FINORA CORE نشط" },
  { key: "human", label: "بإدارة بشرية" },
  { key: "qualified", label: "مؤهلون" },
  { key: "needs_approval", label: "تحتاج موافقة" },
  { key: "onboarding", label: "تهيئة" },
];

function StateChip({ c }: { c: Conversation }) {
  if (WORKING.has(c.agentState))
    return (
      <Badge tone="green" icon={<Sparkles size={12} />}>
        جارٍ الرد بالذكاء الاصطناعي
      </Badge>
    );
  if (c.pendingApprovals > 0) return <Badge tone="amber">بانتظار موافقة</Badge>;
  if (c.control === "human") return <Badge tone="violet">بإدارة {c.assignedTo ?? "بشرية"}</Badge>;
  if (c.leadStage === "needs_human") return <Badge tone="red">يحتاج متابعة</Badge>;
  if (c.agentState === "waiting_customer") return <Badge tone="amber">في انتظار الرد</Badge>;
  const m = LEAD_STAGE_META[c.leadStage];
  return <Badge tone={m.tone}>{m.label}</Badge>;
}

const Row = memo(function Row({
  c,
  selected,
  onSelect,
}: {
  c: Conversation;
  selected: boolean;
  onSelect: (id: string) => void;
}) {
  return (
    <li className="cl-item">
      <button
        type="button"
        className={cx("cl-row", selected && "is-selected", c.unreadCount > 0 && "is-unread")}
        onClick={() => onSelect(c.id)}
        aria-current={selected ? "true" : undefined}
      >
        <Avatar name={c.customerName} url={c.avatarUrl} size={48} />
        <span className="cl-body">
          <span className="cl-top">
            <bdi className="cl-name">{c.customerName}</bdi>
            <Time iso={c.lastActivityAt} className="cl-time" />
          </span>
          <span className="cl-channel">
            <ChannelIcon channel={c.channel} size={15} />
            {CHANNEL_LABEL[c.channel]}
          </span>
          <span className="cl-last-line">
            <bdi className="cl-last" dir="auto">
              {c.lastMessageText}
            </bdi>
            {c.unreadCount > 0 && (
              <span className="cl-unread" aria-label={`${c.unreadCount} غير مقروءة`}>
                {c.unreadCount}
              </span>
            )}
          </span>
          <span className="cl-chip">
            <StateChip c={c} />
          </span>
        </span>
      </button>
    </li>
  );
});

function ListSkeleton() {
  return (
    <ul className="cl-list" aria-busy="true" aria-label="جارٍ تحميل المحادثات">
      {Array.from({ length: 6 }, (_, i) => (
        <li key={i} className="cl-skel">
          <Skeleton w={48} h={48} r={24} />
          <span className="cl-skel-lines">
            <Skeleton w="55%" h={13} />
            <Skeleton w="30%" h={10} />
            <Skeleton w="80%" h={10} />
          </span>
        </li>
      ))}
    </ul>
  );
}

export function ConversationList() {
  const channel = useUi((s) => s.channel);
  const filter = useUi((s) => s.filter);
  const search = useUi((s) => s.search);
  const setChannel = useUi((s) => s.setChannel);
  const setFilter = useUi((s) => s.setFilter);
  const setSearch = useUi((s) => s.setSearch);
  const selectedId = useUi((s) => s.selectedConversationId);
  const select = useUi((s) => s.select);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const deferredSearch = useDeferredValue(search);
  const q = useConversations({ channel, filter, search: deferredSearch });

  // Pre-select the most recent conversation while still closed, so its messages and profile are loaded and
  // rendered before the morph starts (opening then does no data work). Read receipts are gated on `open` elsewhere.
  useEffect(() => {
    if (!selectedId && q.data?.[0]) select(q.data[0].id);
  }, [selectedId, q.data, select]);

  useEffect(() => {
    if (!menuOpen) return;
    const close = (e: MouseEvent) => {
      if (!menuRef.current?.contains(e.target as Node)) setMenuOpen(false);
    };
    window.addEventListener("pointerdown", close);
    return () => window.removeEventListener("pointerdown", close);
  }, [menuOpen]);

  const activeFilter = FILTERS.find((f) => f.key === filter);

  return (
    <div className="cl">
      <div className="cl-tabs" role="tablist" aria-label="القناة">
        {(["all", "instagram", "facebook", "telegram"] as const).map((ch) => (
          <button
            key={ch}
            type="button"
            role="tab"
            aria-selected={channel === ch}
            aria-label={ch === "all" ? "الكل" : CHANNEL_LABEL[ch]}
            title={ch === "all" ? "الكل" : CHANNEL_LABEL[ch]}
            className={cx("cl-tab", channel === ch && "is-active")}
            onClick={() => setChannel(ch)}
          >
            {channel === ch && (
              <motion.span layoutId="cl-tab-pill" className="cl-tab-pill" transition={transitions.normal} />
            )}
            <span className="cl-tab-label">
              {ch === "all" ? "الكل" : <ChannelIcon channel={ch} size={24} />}
            </span>
          </button>
        ))}
      </div>

      <div className="cl-search-row">
        <label className="field cl-search">
          <Search size={17} aria-hidden="true" />
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="البحث في المحادثات..."
            aria-label="البحث في المحادثات"
          />
          {search && (
            <button
              type="button"
              className="field-clear"
              aria-label="مسح البحث"
              onClick={() => setSearch("")}
            >
              <X size={14} />
            </button>
          )}
        </label>
        <div className="cl-filter" ref={menuRef}>
          <button
            type="button"
            className={cx("icon-btn cl-filter-btn", filter !== "all" && "is-active")}
            aria-label="تصفية المحادثات"
            aria-expanded={menuOpen}
            aria-haspopup="menu"
            onClick={() => setMenuOpen((o) => !o)}
          >
            <SlidersHorizontal size={17} />
          </button>
          <AnimatePresence>
            {menuOpen && (
              <motion.div
                className="menu"
                role="menu"
                initial={{ opacity: 0, y: -4, scale: 0.98 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: -4, scale: 0.98 }}
                transition={transitions.fast}
              >
                {FILTERS.map((f) => (
                  <button
                    key={f.key}
                    type="button"
                    role="menuitemradio"
                    aria-checked={filter === f.key}
                    className="menu-item"
                    onClick={() => {
                      setFilter(f.key);
                      setMenuOpen(false);
                    }}
                  >
                    {f.label}
                    {filter === f.key && <Check size={15} />}
                  </button>
                ))}
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
      {filter !== "all" && activeFilter && (
        <div className="cl-active-filter">
          <span>{activeFilter.label}</span>
          <button type="button" onClick={() => setFilter("all")} aria-label="إزالة التصفية">
            <X size={13} />
          </button>
        </div>
      )}

      <div className="cl-scroll">
        {q.isPending ? (
          <ListSkeleton />
        ) : q.isError ? (
          <ErrorState error={q.error} onRetry={() => void q.refetch()} />
        ) : q.data.length === 0 ? (
          <EmptyState
            title={
              search || filter !== "all" || channel !== "all" ? "لا توجد نتائج" : "لا توجد محادثات حالياً"
            }
            hint={search ? "جرّب كلمة بحث أخرى" : undefined}
          />
        ) : (
          <ul className="cl-list" aria-label="المحادثات">
            {q.data.map((c) => (
              <Row key={c.id} c={c} selected={c.id === selectedId} onSelect={select} />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
