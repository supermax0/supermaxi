import React from "react";
import type { NodeProps } from "reactflow";

type BasicNodeData = {
  label?: string;
  subtitle?: string;
};

const baseNodeClasses =
  "rounded-lg border px-3 py-2 text-xs shadow-sm bg-slate-900/80 border-slate-700";

const titleClasses = "font-semibold text-slate-50";
const subtitleClasses = "mt-1 text-[10px] text-slate-400";

const StartNode: React.FC<NodeProps<BasicNodeData>> = ({ data }) => (
  <div className={`${baseNodeClasses} border-emerald-500/70`}>
    <div className={titleClasses}>⏵ {data.label || "Start"}</div>
    {data.subtitle && <div className={subtitleClasses}>{data.subtitle}</div>}
  </div>
);

const AINode: React.FC<NodeProps<BasicNodeData>> = ({ data }) => (
  <div className={`${baseNodeClasses} border-violet-500/70`}>
    <div className={titleClasses}>🤖 {data.label || "AI Agent"}</div>
    {data.subtitle && <div className={subtitleClasses}>{data.subtitle}</div>}
  </div>
);

const ImageNode: React.FC<NodeProps<BasicNodeData>> = ({ data }) => (
  <div className={`${baseNodeClasses} border-sky-500/70`}>
    <div className={titleClasses}>🖼 {data.label || "Image Generator"}</div>
    {data.subtitle && <div className={subtitleClasses}>{data.subtitle}</div>}
  </div>
);

const CaptionNode: React.FC<NodeProps<BasicNodeData>> = ({ data }) => (
  <div className={baseNodeClasses}>
    <div className={titleClasses}>✏️ {data.label || "Caption"}</div>
    {data.subtitle && <div className={subtitleClasses}>{data.subtitle}</div>}
  </div>
);

const PublisherNode: React.FC<NodeProps<BasicNodeData>> = ({ data }) => (
  <div className={`${baseNodeClasses} border-emerald-400/70`}>
    <div className={titleClasses}>📤 {data.label || "Publisher"}</div>
    {data.subtitle && <div className={subtitleClasses}>{data.subtitle}</div>}
  </div>
);

const SchedulerNode: React.FC<NodeProps<BasicNodeData>> = ({ data }) => (
  <div className={`${baseNodeClasses} border-cyan-400/70`}>
    <div className={titleClasses}>⏰ {data.label || "Scheduler"}</div>
    {data.subtitle && <div className={subtitleClasses}>{data.subtitle}</div>}
  </div>
);

const CommentListenerNode: React.FC<NodeProps<BasicNodeData>> = ({ data }) => (
  <div className={`${baseNodeClasses} border-amber-400/70`}>
    <div className={titleClasses}>💬 {data.label || "Comment Listener"}</div>
    {data.subtitle && <div className={subtitleClasses}>{data.subtitle}</div>}
  </div>
);

const AutoReplyNode: React.FC<NodeProps<BasicNodeData>> = ({ data }) => (
  <div className={`${baseNodeClasses} border-indigo-400/70`}>
    <div className={titleClasses}>✨ {data.label || "Auto Reply"}</div>
    {data.subtitle && <div className={subtitleClasses}>{data.subtitle}</div>}
  </div>
);

const EndNode: React.FC<NodeProps<BasicNodeData>> = ({ data }) => (
  <div className={`${baseNodeClasses} border-rose-500/70`}>
    <div className={titleClasses}>■ {data.label || "End"}</div>
    {data.subtitle && <div className={subtitleClasses}>{data.subtitle}</div>}
  </div>
);

export const nodeTypes = {
  start: StartNode,
  ai: AINode,
  image: ImageNode,
  caption: CaptionNode,
  publisher: PublisherNode,
  scheduler: SchedulerNode,
  "comment-listener": CommentListenerNode,
  "auto-reply": AutoReplyNode,
  end: EndNode,
};

