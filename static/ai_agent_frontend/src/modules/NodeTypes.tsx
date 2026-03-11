import React from "react";
import { Handle, Position, type NodeProps } from "reactflow";

type BasicNodeData = {
  label?: string;
  subtitle?: string;
  task?: string;
  prompt?: string;
};

const baseNodeClasses =
  "rounded-[12px] border-2 p-3 text-xs bg-[#0f172a] relative min-w-[160px] transition-all duration-150";
const baseNodeShadow = { boxShadow: "0 4px 20px rgba(0,0,0,0.25)" };

const titleClasses = "font-semibold text-[#e5e7eb]";
const subtitleClasses = "mt-1.5 text-[10px] text-slate-400";

const handleClass =
  "!w-3 !h-3 !border-2 !border-[#334155] !bg-[#111827] hover:!border-[#38bdf8] hover:!bg-[#1e293b]";

const StartNode: React.FC<NodeProps<BasicNodeData>> = ({ data }) => {
  const topic = (data as any).topic as string | undefined;
  const subtitle =
    data.subtitle || (topic && topic.trim() ? `الموضوع: ${topic.trim().length > 20 ? `${topic.trim().slice(0, 20)}…` : topic.trim()}` : "بداية الوورك فلو");

  return (
    <div className={`${baseNodeClasses} border-[#22c55e]`} style={baseNodeShadow}>
      <Handle type="source" position={Position.Bottom} id="out" className={handleClass} />
      <div className={titleClasses}>⏵ {data.label || "Start"}</div>
      {subtitle && <div className={subtitleClasses}>{subtitle}</div>}
    </div>
  );
};

const AINode: React.FC<NodeProps<BasicNodeData>> = ({ data }) => {
  const task = data.task || "generate_post";
  const promptPreview =
    data.prompt && data.prompt.length > 40 ? `${data.prompt.slice(0, 40)}…` : data.prompt;

  const subtitle =
    promptPreview ||
    data.subtitle ||
    (task === "reply_comment"
      ? "AI Comment Reply"
      : task === "write_caption"
      ? "Generate Caption"
      : "Generate AI content");

  return (
    <div className={`${baseNodeClasses} border-[#8b5cf6]`} style={baseNodeShadow}>
      <Handle type="target" position={Position.Top} id="in" className={handleClass} />
      <Handle type="source" position={Position.Bottom} id="out" className={handleClass} />
      <div className={titleClasses}>🤖 {data.label || "AI Agent"}</div>
      {subtitle && <div className={subtitleClasses}>{subtitle}</div>}
    </div>
  );
};

const ImageNode: React.FC<NodeProps<BasicNodeData>> = ({ data }) => {
  const promptPreview =
    data.prompt && data.prompt.length > 40 ? `${data.prompt.slice(0, 40)}…` : data.prompt;
  const subtitle = promptPreview || data.subtitle || "Generate marketing image";

  return (
    <div className={`${baseNodeClasses} border-[#ec4899]`} style={baseNodeShadow}>
      <Handle type="target" position={Position.Top} id="in" className={handleClass} />
      <Handle type="source" position={Position.Bottom} id="out" className={handleClass} />
      <div className={titleClasses}>🖼 {data.label || "Image Generator"}</div>
      {subtitle && <div className={subtitleClasses}>{subtitle}</div>}
    </div>
  );
};

const CaptionNode: React.FC<NodeProps<BasicNodeData>> = ({ data }) => {
  const subtitle =
    data.subtitle ||
    (data as any).style ||
    ((data as any).source === "{{topic}}"
      ? "From topic"
      : (data as any).source === "{{text}}"
      ? "From text"
      : undefined);

  return (
    <div className={`${baseNodeClasses} border-[#3b82f6]`} style={baseNodeShadow}>
      <Handle type="target" position={Position.Top} id="in" className={handleClass} />
      <Handle type="source" position={Position.Bottom} id="out" className={handleClass} />
      <div className={titleClasses}>✏️ {data.label || "Caption Generator"}</div>
      {subtitle && <div className={subtitleClasses}>{subtitle}</div>}
    </div>
  );
};

const PublisherNode: React.FC<NodeProps<BasicNodeData>> = ({ data }) => {
  const platforms = ((data as any).platforms as string[] | undefined) || [];
  const platformsLabel = platforms.length ? platforms.join(", ") : undefined;
  const subtitle = platformsLabel || data.subtitle || "Select platforms & mode";

  return (
    <div className={`${baseNodeClasses} border-[#f97316]`} style={baseNodeShadow}>
      <Handle type="target" position={Position.Top} id="in" className={handleClass} />
      <Handle type="source" position={Position.Bottom} id="out" className={handleClass} />
      <div className={titleClasses}>📤 {data.label || "Publisher"}</div>
      {subtitle && <div className={subtitleClasses}>{subtitle}</div>}
    </div>
  );
};

const SchedulerNode: React.FC<NodeProps<BasicNodeData>> = ({ data }) => {
  const scheduleType = (data as any).schedule_type || "daily";
  const time = (data as any).time || "20:00";
  const subtitle = data.subtitle || `${scheduleType} @ ${time}`;

  return (
    <div className={`${baseNodeClasses} border-[#06b6d4]`} style={baseNodeShadow}>
      <Handle type="target" position={Position.Top} id="in" className={handleClass} />
      <Handle type="source" position={Position.Bottom} id="out" className={handleClass} />
      <div className={titleClasses}>⏰ {data.label || "Scheduler"}</div>
      {subtitle && <div className={subtitleClasses}>{subtitle}</div>}
    </div>
  );
};

const CommentListenerNode: React.FC<NodeProps<BasicNodeData>> = ({ data }) => {
  const platforms = ((data as any).platforms as string[] | undefined) || [];
  const mode = (data as any).mode || "keywords_only";
  const subtitle =
    data.subtitle ||
    (platforms.length ? `${platforms.join(", ")} • ${mode}` : "Select platforms & mode");

  return (
    <div className={`${baseNodeClasses} border-[#eab308]`} style={baseNodeShadow}>
      <Handle type="target" position={Position.Top} id="in" className={handleClass} />
      <Handle type="source" position={Position.Bottom} id="out" className={handleClass} />
      <div className={titleClasses}>💬 {data.label || "Comment Listener"}</div>
      {subtitle && <div className={subtitleClasses}>{subtitle}</div>}
    </div>
  );
};

const AutoReplyNode: React.FC<NodeProps<BasicNodeData>> = ({ data }) => {
  const mode = (data as any).mode || "template";
  const template = (data as any).template as string | undefined;
  let subtitle = data.subtitle;
  if (!subtitle) {
    if (mode === "ai_generated") subtitle = "رد مُولَّد بالذكاء الاصطناعي";
    else if (template && template.trim()) {
      const short = template.trim().length > 28 ? `${template.trim().slice(0, 28)}…` : template.trim();
      subtitle = short;
    } else subtitle = "قالب ثابت";
  }

  return (
    <div className={`${baseNodeClasses} border-[#ef4444]`} style={baseNodeShadow}>
      <Handle type="target" position={Position.Top} id="in" className={handleClass} />
      <Handle type="source" position={Position.Bottom} id="out" className={handleClass} />
      <div className={titleClasses}>✨ {data.label || "Auto Reply"}</div>
      {subtitle && <div className={subtitleClasses}>{subtitle}</div>}
    </div>
  );
};

const MemoryNode: React.FC<NodeProps<BasicNodeData>> = ({ data }) => {
  const key = (data as any).key as string | undefined;
  const subtitle =
    data.subtitle ||
    (key && key.trim()
      ? `تخزين في المفتاح: ${key.trim().length > 18 ? `${key.trim().slice(0, 18)}…` : key.trim()}`
      : "تخزين قيمة في الـ context");

  return (
    <div className={`${baseNodeClasses} border-[#10b981]`} style={baseNodeShadow}>
      <Handle type="target" position={Position.Top} id="in" className={handleClass} />
      <Handle type="source" position={Position.Bottom} id="out" className={handleClass} />
      <div className={titleClasses}>🧺 {data.label || "Store Data"}</div>
      {subtitle && <div className={subtitleClasses}>{subtitle}</div>}
    </div>
  );
};

const KnowledgeNode: React.FC<NodeProps<BasicNodeData>> = ({ data }) => {
  const mode = (data as any).mode || "replace";
  const subtitle =
    data.subtitle ||
    (mode === "append" ? "إضافة للمعرفة الحالية" : "استبدال قاعدة المعرفة لهذا الوكيل");

  return (
    <div className={`${baseNodeClasses} border-[#6366f1]`} style={baseNodeShadow}>
      <Handle type="target" position={Position.Top} id="in" className={handleClass} />
      <Handle type="source" position={Position.Bottom} id="out" className={handleClass} />
      <div className={titleClasses}>📚 {data.label || "Knowledge / Catalog"}</div>
      {subtitle && <div className={subtitleClasses}>{subtitle}</div>}
    </div>
  );
};

const EndNode: React.FC<NodeProps<BasicNodeData>> = ({ data }) => {
  const note = (data as any).note as string | undefined;
  const subtitle =
    data.subtitle || (note && note.trim() ? (note.trim().length > 24 ? `${note.trim().slice(0, 24)}…` : note.trim()) : "حفظ السياق وإنهاء");

  return (
    <div className={`${baseNodeClasses} border-[#64748b]`} style={baseNodeShadow}>
      <Handle type="target" position={Position.Top} id="in" className={handleClass} />
      <div className={titleClasses}>■ {data.label || "End"}</div>
      {subtitle && <div className={subtitleClasses}>{subtitle}</div>}
    </div>
  );
};

const WhatsAppListenerNode: React.FC<NodeProps<BasicNodeData>> = ({ data }) => {
  const phoneId = (data as any).phone_id as string | undefined;
  const enabled = (data as any).enabled ?? true;
  const subtitle =
    data.subtitle ||
    (phoneId && phoneId.trim()
      ? `Webhook ${enabled ? "مفعل" : "معطّل"} • ${phoneId.trim().length > 18 ? `${phoneId.trim().slice(0, 18)}…` : phoneId.trim()}`
      : enabled
      ? "استقبال رسائل واتساب"
      : "Webhook معطّل");

  return (
    <div className={`${baseNodeClasses} border-[#22c55e]`} style={baseNodeShadow}>
      <Handle type="source" position={Position.Bottom} id="out" className={handleClass} />
      <div className={titleClasses}>📲 {data.label || "WhatsApp Listener"}</div>
      {subtitle && <div className={subtitleClasses}>{subtitle}</div>}
    </div>
  );
};

const WhatsAppSendNode: React.FC<NodeProps<BasicNodeData>> = ({ data }) => {
  const mode = (data as any).mode || "message";
  const to = (data as any).to as string | undefined;
  const subtitle =
    data.subtitle ||
    (to && to.trim()
      ? `${mode === "call" ? "اتصال" : "رسالة"} → ${to.trim().length > 18 ? `${to.trim().slice(0, 18)}…` : to.trim()}`
      : mode === "call"
      ? "اتصال واتساب"
      : "رسالة واتساب");

  return (
    <div className={`${baseNodeClasses} border-[#16a34a]`} style={baseNodeShadow}>
      <Handle type="target" position={Position.Top} id="in" className={handleClass} />
      <Handle type="source" position={Position.Bottom} id="out" className={handleClass} />
      <div className={titleClasses}>📱 {data.label || "WhatsApp Send"}</div>
      {subtitle && <div className={subtitleClasses}>{subtitle}</div>}
    </div>
  );
};

const TelegramListenerNode: React.FC<NodeProps<BasicNodeData>> = ({ data }) => {
  const botToken = (data as any).bot_token as string | undefined;
  const enabled = (data as any).enabled ?? true;
  const subtitle =
    data.subtitle ||
    (botToken && botToken.trim()
      ? `Webhook ${enabled ? "مفعل" : "معطّل"}`
      : enabled
      ? "استقبال رسائل تيليجرام"
      : "Webhook معطّل");

  return (
    <div className={`${baseNodeClasses} border-[#0ea5e9]`} style={baseNodeShadow}>
      <Handle type="source" position={Position.Bottom} id="out" className={handleClass} />
      <div className={titleClasses}>✈️ {data.label || "Telegram Listener"}</div>
      {subtitle && <div className={subtitleClasses}>{subtitle}</div>}
    </div>
  );
};

const TelegramSendNode: React.FC<NodeProps<BasicNodeData>> = ({ data }) => {
  const mode = (data as any).mode || "message";
  const to = (data as any).to as string | undefined;
  const subtitle =
    data.subtitle ||
    (to && to.trim()
      ? `${mode === "call" ? "اتصال" : "رسالة"} → ${to.trim().length > 18 ? `${to.trim().slice(0, 18)}…` : to.trim()}`
      : mode === "call"
      ? "اتصال تيليجرام"
      : "رسالة تيليجرام");

  return (
    <div className={`${baseNodeClasses} border-[#0284c7]`} style={baseNodeShadow}>
      <Handle type="target" position={Position.Top} id="in" className={handleClass} />
      <Handle type="source" position={Position.Bottom} id="out" className={handleClass} />
      <div className={titleClasses}>✈️ {data.label || "Telegram Send"}</div>
      {subtitle && <div className={subtitleClasses}>{subtitle}</div>}
    </div>
  );
};

const KeywordFilterNode: React.FC<NodeProps<BasicNodeData>> = ({ data }) => {
  const keywords = ((data as any).keywords as string[]) || [];
  const subtitle = data.subtitle || (keywords.length ? `${keywords.length} كلمة` : "أضف كلمات مفتاحية");
  return (
    <div className={`${baseNodeClasses} border-[#a855f7]`} style={baseNodeShadow}>
      <Handle type="target" position={Position.Top} id="in" className={handleClass} />
      <Handle type="source" position={Position.Bottom} id="out" className={handleClass} />
      <div className={titleClasses}>🔍 {data.label || "Keyword Filter"}</div>
      {subtitle && <div className={subtitleClasses}>{subtitle}</div>}
    </div>
  );
};

const PublishReplyNode: React.FC<NodeProps<BasicNodeData>> = ({ data }) => {
  const subtitle = data.subtitle || "نشر الرد على FB/IG/TikTok";
  return (
    <div className={`${baseNodeClasses} border-[#f59e0b]`} style={baseNodeShadow}>
      <Handle type="target" position={Position.Top} id="in" className={handleClass} />
      <Handle type="source" position={Position.Bottom} id="out" className={handleClass} />
      <div className={titleClasses}>📣 {data.label || "Publish Reply"}</div>
      {subtitle && <div className={subtitleClasses}>{subtitle}</div>}
    </div>
  );
};

const RateLimiterNode: React.FC<NodeProps<BasicNodeData>> = ({ data }) => {
  const delay = (data as any).delay_between_replies ?? 5;
  const max = (data as any).max_replies_per_minute ?? 20;
  const subtitle = data.subtitle || `${delay}s تأخير، ${max}/دقيقة`;
  return (
    <div className={`${baseNodeClasses} border-[#14b8a6]`} style={baseNodeShadow}>
      <Handle type="target" position={Position.Top} id="in" className={handleClass} />
      <Handle type="source" position={Position.Bottom} id="out" className={handleClass} />
      <div className={titleClasses}>⏱ {data.label || "Rate Limiter"}</div>
      {subtitle && <div className={subtitleClasses}>{subtitle}</div>}
    </div>
  );
};

const LoggingNode: React.FC<NodeProps<BasicNodeData>> = ({ data }) => {
  const subtitle = data.subtitle || "تسجيل في comment_logs";
  return (
    <div className={`${baseNodeClasses} border-[#78716c]`} style={baseNodeShadow}>
      <Handle type="target" position={Position.Top} id="in" className={handleClass} />
      <Handle type="source" position={Position.Bottom} id="out" className={handleClass} />
      <div className={titleClasses}>📋 {data.label || "Logging"}</div>
      {subtitle && <div className={subtitleClasses}>{subtitle}</div>}
    </div>
  );
};

const DuplicateProtectionNode: React.FC<NodeProps<BasicNodeData>> = ({ data }) => {
  const subtitle = data.subtitle || "عدم الرد مرتين على نفس التعليق";
  return (
    <div className={`${baseNodeClasses} border-[#64748b]`} style={baseNodeShadow}>
      <Handle type="target" position={Position.Top} id="in" className={handleClass} />
      <Handle type="source" position={Position.Bottom} id="out" className={handleClass} />
      <div className={titleClasses}>🛡 {data.label || "Duplicate Protection"}</div>
      {subtitle && <div className={subtitleClasses}>{subtitle}</div>}
    </div>
  );
};

export const nodeTypes = {
  start: StartNode,
  ai: AINode,
  image: ImageNode,
  caption: CaptionNode,
  publisher: PublisherNode,
  scheduler: SchedulerNode,
  "comment-listener": CommentListenerNode,
  "keyword-filter": KeywordFilterNode,
  "auto-reply": AutoReplyNode,
  "publish-reply": PublishReplyNode,
  "rate-limiter": RateLimiterNode,
  logging: LoggingNode,
  "duplicate-protection": DuplicateProtectionNode,
  end: EndNode,
  whatsapp_listener: WhatsAppListenerNode,
  whatsapp_send: WhatsAppSendNode,
  telegram_listener: TelegramListenerNode,
  telegram_send: TelegramSendNode,
  memory_store: MemoryNode,
  knowledge_base: KnowledgeNode,
};

