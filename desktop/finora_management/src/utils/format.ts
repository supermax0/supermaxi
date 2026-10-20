const timeFormatter = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Asia/Baghdad",
  hour: "2-digit",
  minute: "2-digit",
  hour12: true,
});
const dateFormatter = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Baghdad",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});
const numberFormatter = new Intl.NumberFormat("en-US");

/** 12,450,000 — FINORA amounts are whole Iraqi dinars, shown with Latin digits like the web app. */
export function formatNumber(value: number): string {
  return numberFormatter.format(value);
}

export function formatTime(epochMs: number): string {
  const parts = timeFormatter.formatToParts(new Date(epochMs));
  const part = (type: Intl.DateTimeFormatPartTypes) => parts.find((item) => item.type === type)?.value ?? "";
  return `${part("hour")}:${part("minute")} ${part("dayPeriod").toLowerCase() === "am" ? "ص" : "م"}`;
}

/** Stored timestamps are UTC; plain calendar dates keep their existing meaning. */
export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  if (!/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/.test(value)) return value;
  const iso = value.replace(" ", "T");
  const date = new Date(/[zZ]$|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : `${iso}Z`);
  if (Number.isNaN(date.getTime())) return value;
  return `${dateFormatter.format(date)} ${formatTime(date.getTime())}`;
}

/** A scheduled wall clock is already local and must keep the entered hour. */
export function formatClockTime(value: string): string {
  const match = /^(\d{2}):(\d{2})(?::\d{2})?$/.exec(value);
  if (!match) return value;
  const hour = Number(match[1]);
  if (hour > 23 || Number(match[2]) > 59) return value;
  return `${String(hour % 12 || 12).padStart(2, "0")}:${match[2]} ${hour < 12 ? "ص" : "م"}`;
}
