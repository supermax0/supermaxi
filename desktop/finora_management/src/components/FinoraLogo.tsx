export function FinoraLogo() {
  return (
    <div className="flex items-center gap-3" dir="ltr" aria-label="FINORA">
      <svg width="40" height="40" viewBox="0 0 40 40" aria-hidden>
        <defs>
          <linearGradient id="finora-mark" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="rgb(var(--maroon))" />
            <stop offset="1" stopColor="rgb(var(--violet-deep))" />
          </linearGradient>
        </defs>
        <rect x="1" y="1" width="38" height="38" rx="11" fill="url(#finora-mark)" />
        <path
          d="M14 29V12.5h13.5"
          fill="none"
          stroke="#fff"
          strokeWidth="4.2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <path
          d="M14 20.5h9.5"
          fill="none"
          stroke="#fff"
          strokeWidth="4.2"
          strokeLinecap="round"
          opacity="0.82"
        />
      </svg>
      <div className="leading-none">
        <div className="font-num text-[21px] font-semibold tracking-[0.2em] text-maroon">FINORA</div>
        <div className="mt-1 text-[11px] text-ink-faint" dir="rtl">
          نظام الإدارة المتكاملة
        </div>
      </div>
    </div>
  );
}
