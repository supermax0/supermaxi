const timeFormatter = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit" });
const numberFormatter = new Intl.NumberFormat("en-US");

/** 12,450,000 — FINORA amounts are whole Iraqi dinars, shown with Latin digits like the web app. */
export function formatNumber(value: number): string {
  return numberFormatter.format(value);
}

export function formatTime(epochMs: number): string {
  return timeFormatter.format(new Date(epochMs));
}
