import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { HttpDataSource } from "../data/http";
import { CoreError } from "../data/source";
import { renderWithSource } from "../test/render";
import { TelegramSettings } from "./TelegramSettings";

const empty = {
  houseConfigured: true,
  tokenConfigured: false,
  botId: "",
  username: "",
  name: "",
  active: false,
  status: "disconnected",
  webhookUrl: "",
  botUrl: "",
  lastError: null,
};
const connected = {
  ...empty,
  tokenConfigured: true,
  botId: "12345678",
  username: "FINORA_test_bot",
  name: "FINORA",
  active: true,
  status: "connected",
  webhookUrl: "https://finora.test/webhooks/telegram/key",
  botUrl: "https://t.me/FINORA_test_bot",
};
function source() {
  const src = new HttpDataSource(
    "https://finora.test",
    {
      accessToken: "test",
      refreshToken: "test",
      operator: { id: 1, username: "owner", role: "super_admin", permissions: ["settings.manage"] },
    },
    vi.fn(),
  );
  vi.spyOn(src, "getTelegramSettings").mockResolvedValue(empty);
  return src;
}
afterEach(() => vi.restoreAllMocks());

describe("TelegramSettings", () => {
  it("connects, clears the secret, checks health and disconnects without losing messages", async () => {
    const src = source();
    vi.spyOn(src, "connectTelegram").mockResolvedValue(connected);
    vi.spyOn(src, "checkTelegramHealth").mockResolvedValue({
      ...connected,
      status: "webhook_invalid",
      lastError: "استقبال الرسائل يحتاج فحص",
    });
    vi.spyOn(src, "disconnectTelegram").mockResolvedValue({
      ...connected,
      active: false,
      status: "disconnected",
    });
    renderWithSource(<TelegramSettings src={src} />, src);
    const token = await screen.findByLabelText("رمز بوت تلگرام");
    expect(token).toHaveAttribute("type", "password");
    expect(screen.getByRole("button", { name: "ربط البوت" })).toBeDisabled();
    fireEvent.change(token, { target: { value: "fake-bot-token" } });
    fireEvent.click(screen.getByRole("button", { name: "ربط البوت" }));
    await screen.findByText(/تم ربط البوت/);
    expect(src.connectTelegram).toHaveBeenCalledWith("fake-bot-token");
    expect(token).toHaveValue("");
    expect(screen.getByRole("link", { name: "@FINORA_test_bot" })).toHaveAttribute("href", connected.botUrl);
    fireEvent.click(screen.getByRole("button", { name: "فحص اتصال تلگرام" }));
    await screen.findByText(/راجع حالة القناة/);
    expect(screen.queryByText("رمز البوت واستقبال الرسائل يعملان")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "فصل البوت" }));
    await screen.findByText(/تم فصل البوت؛ المحادثات محفوظة/);
    expect(screen.getByRole("button", { name: "فحص اتصال تلگرام" })).toBeDisabled();
  });

  it("surfaces failed connections and keeps the entered token for correction", async () => {
    const src = source();
    vi.spyOn(src, "connectTelegram").mockRejectedValue(
      new CoreError("VALIDATION_ERROR", "رمز البوت غير صالح"),
    );
    renderWithSource(<TelegramSettings src={src} />, src);
    const token = await screen.findByLabelText("رمز بوت تلگرام");
    fireEvent.change(token, { target: { value: "invalid-test-token" } });
    fireEvent.click(screen.getByRole("button", { name: "ربط البوت" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("رمز البوت غير صالح"));
    expect(token).toHaveValue("invalid-test-token");
    expect(screen.queryByText(/تم ربط البوت/)).not.toBeInTheDocument();
  });
});
