import { z } from "zod";
import { finoraCall } from "./transport";
import type { TimeFormat } from "@/stores/displayTime";

const schema = z.object({
  ok: z.literal(true),
  time_format: z.enum(["12", "24"]),
  timezone: z.literal("Asia/Baghdad"),
});
export const displayPreferences = {
  get: () => finoraCall({ method: "GET", path: "/api/v1/desktop/display-preferences" }, schema),
  set: (time_format: TimeFormat) =>
    finoraCall(
      { method: "POST", path: "/api/v1/desktop/display-preferences", body: { time_format } },
      schema,
    ),
};
