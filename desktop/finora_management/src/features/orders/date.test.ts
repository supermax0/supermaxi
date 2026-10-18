import { formatOrderDate } from "./status";

it("shows stored UTC order timestamps on Baghdad's accounting day", () => {
  expect(formatOrderDate("2026-07-31 20:59:59")).toBe("31/07 23:59");
  expect(formatOrderDate("2026-07-31 21:00:00")).toBe("01/08 00:00");
  expect(formatOrderDate("2026-07-31T21:00:00Z")).toBe("01/08 00:00");
});

it("honors explicit offsets without shifting twice and preserves date-only values", () => {
  expect(formatOrderDate("2026-08-01T00:00:00+03:00")).toBe("01/08 00:00");
  expect(formatOrderDate("2026-07-31")).toBe("31/07");
  expect(formatOrderDate("—")).toBe("—");
  expect(formatOrderDate("2026-99-99 10:00:00")).toBe("2026-99-99 10:00:00");
});
