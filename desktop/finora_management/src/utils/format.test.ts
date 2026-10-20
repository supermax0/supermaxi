import { formatClockTime, formatDateTime, formatTime } from "./format";

it("shows midnight, noon and evening in Baghdad with Arabic day periods", () => {
  expect(formatDateTime("2026-10-19 21:00:00")).toBe("2026-10-20 12:00 ص");
  expect(formatDateTime("2026-10-20T09:00:00Z")).toBe("2026-10-20 12:00 م");
  expect(formatDateTime("2026-10-20T19:30:00+03:00")).toBe("2026-10-20 07:30 م");
  expect(formatTime(Date.parse("2026-10-20T16:30:00Z"))).toBe("07:30 م");
  expect(formatClockTime("22:00")).toBe("10:00 م");
  expect(formatClockTime("00:00")).toBe("12:00 ص");
  expect(formatClockTime("12:30:00")).toBe("12:30 م");
});

it("preserves date-only values and handles missing or invalid timestamps", () => {
  expect(formatDateTime("2026-10-20")).toBe("2026-10-20");
  expect(formatDateTime(null)).toBe("—");
  expect(formatDateTime("2026-99-99 10:30:00")).toBe("2026-99-99 10:30:00");
});
