import { useDisplayTime } from "@/stores/displayTime";

const timeFormatters = {
  "12": new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Baghdad",
    hour: "2-digit",
    minute: "2-digit",
    hour12: true,
  }),
  "24": new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Baghdad",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }),
};
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

export function formatTime(value: number | string | Date): string {
  const mode = useDisplayTime.getState().format;
  const date = parseTimestamp(value);
  if (!date) return String(value);
  const parts = timeFormatters[mode].formatToParts(date);
  const part = (type: Intl.DateTimeFormatPartTypes) => parts.find((item) => item.type === type)?.value ?? "";
  return `${part("hour")}:${part("minute")}${mode === "24" ? "" : ` ${part("dayPeriod").toLowerCase() === "am" ? "ص" : "م"}`}`;
}

function parseTimestamp(value: string | number | Date): Date | null {
  let input: string | number | Date = value;
  if (typeof value === "string") {
    const iso = value.replace(" ", "T");
    input = /[zZ]$|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : `${iso}Z`;
  }
  const date = input instanceof Date ? input : new Date(input);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** Stored timestamps are UTC; plain calendar dates keep their existing meaning. */
export function formatDateTime(value: string | number | Date | null | undefined): string {
  if (value == null || value === "") return "—";
  if (typeof value === "string" && !/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/.test(value)) return value;
  const date = parseTimestamp(value);
  if (!date) return String(value);
  return `${dateFormatter.format(date)} ${formatTime(date.getTime())}`;
}

/** A scheduled wall clock is already local and must keep the entered hour. */
export function formatClockTime(value: string): string {
  const match = /^(\d{2}):(\d{2})(?::\d{2})?$/.exec(value);
  if (!match) return value;
  const hour = Number(match[1]);
  if (hour > 23 || Number(match[2]) > 59) return value;
  if (useDisplayTime.getState().format === "24") return `${match[1]}:${match[2]}`;
  return `${String(hour % 12 || 12).padStart(2, "0")}:${match[2]} ${hour < 12 ? "ص" : "م"}`;
}
