import { formatNumber } from "./format";

/** 12,450,000 د.ع */
export function formatIqd(value: number): string {
  return `${formatNumber(Math.round(value))} د.ع`;
}
