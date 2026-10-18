/** Dependency-free SVG charts for the reports (line + grouped bars), RTL-aware, theme colours. */
import { useId, useMemo, useState } from "react";
import { formatNumber } from "@/utils/format";

export function compactNumber(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 1_000_000_000) return `${(value / 1_000_000_000).toFixed(abs >= 10_000_000_000 ? 0 : 1)}B`;
  if (abs >= 1_000_000) return `${(value / 1_000_000).toFixed(abs >= 10_000_000 ? 0 : 1)}M`;
  if (abs >= 1_000) return `${Math.round(value / 1_000)}K`;
  return String(value);
}

/** Round axis maximum (1, 2, 2.5, 5 × 10ⁿ) above the data. */
function niceMax(value: number): number {
  if (value <= 0) return 1;
  const exp = 10 ** Math.floor(Math.log10(value));
  for (const step of [1, 2, 2.5, 5, 10]) if (value <= step * exp) return step * exp;
  return 10 * exp;
}

const W = 640;
const PAD = { top: 14, right: 16, bottom: 26, left: 52 };

export interface LinePoint {
  key: string;
  label: string;
  value: number;
}

export function LineChart({
  points,
  label,
  height = 210,
}: {
  points: LinePoint[];
  label: string;
  height?: number;
}) {
  const gradient = useId();
  const [hover, setHover] = useState<number | null>(null);
  const max = niceMax(Math.max(0, ...points.map((p) => p.value)));
  const innerW = W - PAD.left - PAD.right;
  const innerH = height - PAD.top - PAD.bottom;
  // RTL: time runs right → left, as in the reference design.
  const x = (i: number) =>
    PAD.left + (points.length <= 1 ? innerW / 2 : innerW - (i / (points.length - 1)) * innerW);
  const y = (v: number) => PAD.top + innerH - (v / max) * innerH;
  const path = points
    .map((p, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`)
    .join(" ");
  const area = points.length
    ? `${path} L${x(points.length - 1).toFixed(1)},${PAD.top + innerH} L${x(0).toFixed(1)},${PAD.top + innerH} Z`
    : "";
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((t) => t * max);
  const labelEvery = Math.max(1, Math.ceil(points.length / 7));
  const active = hover !== null ? points[hover] : undefined;

  return (
    <div className="relative" dir="ltr">
      <svg
        viewBox={`0 0 ${W} ${height}`}
        className="h-auto w-full"
        role="img"
        aria-label={label}
        onPointerLeave={() => setHover(null)}
        onPointerMove={(event) => {
          const box = event.currentTarget.getBoundingClientRect();
          const px = ((event.clientX - box.left) / box.width) * W;
          if (points.length === 0) return;
          let best = 0;
          for (let i = 1; i < points.length; i++) if (Math.abs(x(i) - px) < Math.abs(x(best) - px)) best = i;
          setHover(best);
        }}
      >
        <defs>
          <linearGradient id={gradient} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="rgb(var(--violet))" stopOpacity="0.22" />
            <stop offset="100%" stopColor="rgb(var(--violet))" stopOpacity="0.02" />
          </linearGradient>
        </defs>
        {ticks.map((t) => (
          <g key={t}>
            <line
              x1={PAD.left}
              x2={W - PAD.right}
              y1={y(t)}
              y2={y(t)}
              stroke="rgb(var(--line))"
              strokeWidth="1"
            />
            <text x={PAD.left - 8} y={y(t) + 4} textAnchor="end" className="fill-ink-faint text-[10px]">
              {compactNumber(t)}
            </text>
          </g>
        ))}
        {area && <path d={area} fill={`url(#${gradient})`} />}
        {path && (
          <path d={path} fill="none" stroke="rgb(var(--violet))" strokeWidth="2.2" strokeLinejoin="round" />
        )}
        {points.map((p, i) =>
          i % labelEvery === 0 || i === points.length - 1 ? (
            <text
              key={p.key}
              x={x(i)}
              y={height - 6}
              textAnchor="middle"
              className="fill-ink-faint text-[10px]"
            >
              {p.label}
            </text>
          ) : null,
        )}
        {points.length <= 40 &&
          points.map((p, i) => (
            <circle
              key={p.key}
              cx={x(i)}
              cy={y(p.value)}
              r={hover === i ? 4.5 : 2.6}
              fill="white"
              stroke="rgb(var(--violet))"
              strokeWidth="2"
            />
          ))}
        {active && hover !== null && (
          <line
            x1={x(hover)}
            x2={x(hover)}
            y1={PAD.top}
            y2={PAD.top + innerH}
            stroke="rgb(var(--violet))"
            strokeDasharray="3 3"
          />
        )}
      </svg>
      {active && hover !== null && (
        <div
          className="pointer-events-none absolute top-1 -translate-x-1/2 rounded-[10px] bg-ink px-2.5 py-1.5 text-xs text-white shadow-float"
          style={{ left: `${(x(hover) / W) * 100}%` }}
          dir="rtl"
        >
          <p className="opacity-75">{active.label}</p>
          <p className="ltr-isolate font-semibold">{formatNumber(active.value)} د.ع</p>
        </div>
      )}
    </div>
  );
}

export interface BarGroup {
  key: string;
  label: string;
  values: number[];
}

export const SERIES_COLORS = ["rgb(var(--violet))", "rgb(var(--azure) / 0.65)", "rgb(var(--violet) / 0.35)"];

export function BarChart({
  groups,
  series,
  label,
  height = 210,
}: {
  groups: BarGroup[];
  series: string[];
  label: string;
  height?: number;
}) {
  const [hover, setHover] = useState<{ g: number; s: number } | null>(null);
  const all = groups.flatMap((g) => g.values);
  const max = niceMax(Math.max(0, ...all));
  const min = Math.min(0, ...all);
  const range = max - (min < 0 ? niceMax(-min) * -1 : 0);
  const floor = min < 0 ? -niceMax(-min) : 0;
  const innerW = W - PAD.left - PAD.right;
  const innerH = height - PAD.top - PAD.bottom;
  const y = (v: number) => PAD.top + innerH - ((v - floor) / range) * innerH;
  const slot = innerW / Math.max(1, groups.length);
  const barW = Math.min(30, (slot * 0.7) / Math.max(1, series.length));
  const ticks = useMemo(() => [0, 0.25, 0.5, 0.75, 1].map((t) => floor + t * range), [floor, range]);
  const tip = hover ? { group: groups[hover.g], value: groups[hover.g]?.values[hover.s] ?? 0 } : null;

  return (
    <div className="relative" dir="ltr">
      <svg
        viewBox={`0 0 ${W} ${height}`}
        className="h-auto w-full"
        role="img"
        aria-label={label}
        onPointerLeave={() => setHover(null)}
      >
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} stroke="rgb(var(--line))" />
            <text x={PAD.left - 8} y={y(t) + 4} textAnchor="end" className="fill-ink-faint text-[10px]">
              {compactNumber(t)}
            </text>
          </g>
        ))}
        {groups.map((g, gi) => {
          // RTL: first group on the right
          const center = PAD.left + innerW - slot * gi - slot / 2;
          const start = center - (barW * series.length) / 2;
          return (
            <g key={g.key}>
              {g.values.map((v, si) => {
                const top = y(Math.max(v, 0));
                const bottom = y(Math.min(v, 0));
                return (
                  <rect
                    key={si}
                    x={start + si * barW + 2}
                    y={top}
                    width={barW - 4}
                    height={Math.max(1, bottom - top)}
                    rx="4"
                    fill={SERIES_COLORS[si % SERIES_COLORS.length]}
                    opacity={hover && (hover.g !== gi || hover.s !== si) ? 0.55 : 1}
                    onPointerEnter={() => setHover({ g: gi, s: si })}
                  />
                );
              })}
              <text x={center} y={height - 6} textAnchor="middle" className="fill-ink-soft text-[11px]">
                {g.label}
              </text>
            </g>
          );
        })}
      </svg>
      {tip && hover && (
        <div
          className="pointer-events-none absolute left-1/2 top-1 -translate-x-1/2 rounded-[10px] bg-ink px-2.5 py-1.5 text-xs text-white shadow-float"
          dir="rtl"
        >
          {tip.group?.label} · {series[hover.s]}:{" "}
          <span className="ltr-isolate font-semibold">{formatNumber(tip.value)}</span>
        </div>
      )}
    </div>
  );
}
