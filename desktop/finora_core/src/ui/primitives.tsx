import { AlertCircle, RotateCw } from "lucide-react";
import { forwardRef, memo, useState, type ButtonHTMLAttributes, type ReactNode } from "react";
import type { Channel, LeadStage } from "../data/schemas";
import { LEAD_STAGE_META, type Tone } from "../data/leadStages";
import { CoreError } from "../data/source";

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

// ───────────────────────────── brand marks ─────────────────────────────

export function InstagramIcon({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" className="brand-icon">
      <defs>
        <radialGradient id="ig-g" cx="30%" cy="107%" r="150%">
          <stop offset="0" stopColor="#fdf497" />
          <stop offset="0.05" stopColor="#fdf497" />
          <stop offset="0.45" stopColor="#fd5949" />
          <stop offset="0.6" stopColor="#d6249f" />
          <stop offset="0.9" stopColor="#285AEB" />
        </radialGradient>
      </defs>
      <rect x="2" y="2" width="20" height="20" rx="6" fill="url(#ig-g)" />
      <rect x="6.5" y="6.5" width="11" height="11" rx="3.5" fill="none" stroke="#fff" strokeWidth="1.8" />
      <circle cx="12" cy="12" r="2.6" fill="none" stroke="#fff" strokeWidth="1.8" />
      <circle cx="17.1" cy="6.9" r="1.05" fill="#fff" />
    </svg>
  );
}

export function FacebookIcon({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" className="brand-icon">
      <circle cx="12" cy="12" r="10" fill="#1877F2" />
      <path
        d="M13.4 19.9v-5.6h1.9l.3-2.3h-2.2v-1.4c0-.6.2-1.1 1.1-1.1h1.2v-2a15 15 0 0 0-1.7-.1c-1.7 0-2.9 1-2.9 3v1.6H9.2v2.3h1.9v5.6"
        fill="#fff"
      />
    </svg>
  );
}

export function ChannelIcon({ channel, size }: { channel: Channel; size?: number }) {
  if (channel === "telegram") return <TelegramIcon size={size} />;
  return channel === "instagram" ? <InstagramIcon size={size} /> : <FacebookIcon size={size} />;
}

export function TelegramIcon({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" className="brand-icon">
      <circle cx="12" cy="12" r="10" fill="#27A7E7" />
      <path
        d="m5.3 11.7 12.5-4.8c.6-.2 1 .1.8.8l-2.1 10c-.2.7-.6.8-1.2.5l-3.2-2.4-1.5 1.4c-.2.2-.4.4-.7.4l.2-3.3 6.1-5.5c.3-.3-.1-.4-.4-.2l-7.5 4.7-3.2-1c-.7-.2-.7-.5.2-.8Z"
        fill="#fff"
      />
    </svg>
  );
}

export const CHANNEL_LABEL: Record<Channel, string> = {
  instagram: "Instagram",
  facebook: "Facebook",
  telegram: "Telegram",
};

export function FinoraMark({ size = 30 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <defs>
        <linearGradient id="fm-g" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#8a0d33" />
          <stop offset="1" stopColor="#5a0019" />
        </linearGradient>
      </defs>
      <path d="M6 9.5C6 6.5 8.5 4 11.5 4H26l-3 6H12.6c-.9 0-1.6.7-1.6 1.6V28H6Z" fill="url(#fm-g)" />
      <path d="M13 14h10.5l-2.7 5.4H13Z" fill="url(#fm-g)" opacity=".92" />
    </svg>
  );
}

/** Small CSS orb used as the Finora Core avatar in chat. The main orb is WebGL. */
export function MiniOrb({ size = 32, active = false }: { size?: number; active?: boolean }) {
  return (
    <span
      className={cx("mini-orb", active && "is-active")}
      style={{ width: size, height: size }}
      aria-hidden="true"
    />
  );
}

// ───────────────────────────── avatar ─────────────────────────────

const AVATAR_TINTS = ["#E9E3FF", "#FFE3EE", "#DFF0FF", "#E2F7EC", "#FFF0DC", "#EDE7F6"];

function initials(name: string): string {
  const parts = name
    .replace(/[.\-_]/g, " ")
    .split(/\s+/)
    .filter(Boolean);
  const first = parts[0]?.[0] ?? "?";
  const second = parts.length > 1 ? (parts[parts.length - 1]?.[0] ?? "") : "";
  return (first + second).toUpperCase();
}

function hash(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return Math.abs(h);
}

export const Avatar = memo(function Avatar({
  name,
  url,
  size = 44,
  channel,
}: {
  name: string;
  url: string | null;
  size?: number;
  channel?: Channel;
}) {
  const [broken, setBroken] = useState(false);
  const tint = AVATAR_TINTS[hash(name) % AVATAR_TINTS.length];
  return (
    <span className="avatar" style={{ width: size, height: size, fontSize: size * 0.36, background: tint }}>
      {url && !broken ? (
        <img src={url} alt="" loading="lazy" decoding="async" onError={() => setBroken(true)} />
      ) : (
        <span aria-hidden="true">{initials(name)}</span>
      )}
      {channel && (
        <span className="avatar-channel">
          <ChannelIcon channel={channel} size={Math.max(12, size * 0.32)} />
        </span>
      )}
    </span>
  );
});

// ───────────────────────────── badges ─────────────────────────────

export function Badge({ tone, children, icon }: { tone: Tone; children: ReactNode; icon?: ReactNode }) {
  return (
    <span className={cx("badge", `tone-${tone}`)}>
      {icon}
      {children}
    </span>
  );
}

export function LeadBadge({ stage }: { stage: LeadStage }) {
  const m = LEAD_STAGE_META[stage];
  return (
    <Badge tone={m.tone} icon={<span className="badge-dot" />}>
      {m.label}
    </Badge>
  );
}

// ───────────────────────────── buttons ─────────────────────────────

type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "ghost" | "soft" | "danger";
  size?: "sm" | "md";
  loading?: boolean;
};

export const FinoraButton = forwardRef<HTMLButtonElement, BtnProps>(function FinoraButton(
  { variant = "soft", size = "md", loading, className, children, disabled, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type="button"
      className={cx("btn", `btn-${variant}`, `btn-${size}`, loading && "is-loading", className)}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading && <span className="spinner" aria-hidden="true" />}
      {children}
    </button>
  );
});

export function IconButton({
  label,
  className,
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
  return (
    <button type="button" className={cx("icon-btn", className)} aria-label={label} title={label} {...rest}>
      {children}
    </button>
  );
}

// ───────────────────────────── states ─────────────────────────────

export function Skeleton({ w, h = 12, r = 8 }: { w: number | string; h?: number; r?: number }) {
  return <span className="skeleton" style={{ width: w, height: h, borderRadius: r }} aria-hidden="true" />;
}

export function EmptyState({ title, hint, icon }: { title: string; hint?: string; icon?: ReactNode }) {
  return (
    <div className="state-block" role="status">
      {icon && <div className="state-icon">{icon}</div>}
      <p className="state-title">{title}</p>
      {hint && <p className="state-hint">{hint}</p>}
    </div>
  );
}

export function errorText(err: unknown): string {
  if (err instanceof CoreError) return err.message;
  return "حدث خطأ غير متوقع";
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const retryable = !(error instanceof CoreError) || error.retryable;
  return (
    <div className="state-block is-error" role="alert">
      <div className="state-icon">
        <AlertCircle size={20} />
      </div>
      <p className="state-title">{errorText(error)}</p>
      {onRetry && retryable && (
        <FinoraButton size="sm" onClick={onRetry}>
          <RotateCw size={14} /> إعادة المحاولة
        </FinoraButton>
      )}
    </div>
  );
}

// ───────────────────────────── time ─────────────────────────────

const timeFmt = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", hour12: false });
const dayFmt = new Intl.DateTimeFormat("ar", { day: "numeric", month: "short" });

export function formatTime(iso: string, now = new Date()): string {
  const d = new Date(iso);
  const sameDay = d.toDateString() === now.toDateString();
  return sameDay ? timeFmt.format(d) : dayFmt.format(d);
}

export function Time({ iso, className }: { iso: string; className?: string }) {
  return (
    <time dateTime={iso} className={cx("time", className)} dir="ltr">
      {formatTime(iso)}
    </time>
  );
}
