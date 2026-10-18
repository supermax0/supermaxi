import { QueryClient } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "@/app/App";
import { usePosPreferences } from "@/features/pos/posPreferences";
import { useSession } from "@/stores/session";
import { useUi } from "@/stores/ui";
import { createFinoraFixture } from "@/test/fixtures";
import { installMockBridge, removeMockBridge } from "@/test/mockBridge";

afterEach(() => {
  removeMockBridge();
  usePosPreferences.getState().reset();
  useUi.setState({ panel: null, paletteOpen: false });
  useSession.setState({ status: "unknown", session: null, reason: null });
});

describe("Settings dialog", () => {
  it("opens from the gear, edits POS preferences and closes with Escape", async () => {
    installMockBridge(createFinoraFixture().handler);
    render(<App queryClient={new QueryClient({ defaultOptions: { queries: { retry: false } } })} />);
    const user = userEvent.setup();
    await screen.findByRole("navigation", { name: "النوافذ" });

    await user.click(screen.getByRole("button", { name: "الإعدادات" }));
    const dialog = await screen.findByRole("dialog", { name: "الإعدادات" });
    await user.click(within(dialog).getByRole("button", { name: "نقطة البيع" }));
    await user.click(await within(dialog).findByRole("radio", { name: "48" }));
    await user.click(within(dialog).getByRole("radio", { name: /أجل/ }));
    expect(usePosPreferences.getState()).toMatchObject({ pageSize: 48, defaultSaleType: "credit" });

    await user.keyboard("{Escape}");
    expect(useUi.getState().panel).toBeNull();
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "الإعدادات" })).not.toBeInTheDocument());
  });

  it("turns «start with Windows» on and off through the desktop bridge", async () => {
    const bridge = installMockBridge(createFinoraFixture().handler);
    render(<App queryClient={new QueryClient({ defaultOptions: { queries: { retry: false } } })} />);
    const user = userEvent.setup();
    await screen.findByRole("navigation", { name: "النوافذ" });
    await user.click(screen.getByRole("button", { name: "الإعدادات" }));
    const dialog = await screen.findByRole("dialog", { name: "الإعدادات" });
    await user.click(within(dialog).getByRole("button", { name: "المظهر والاختصارات" }));
    const toggle = await within(dialog).findByRole("switch", { name: "تشغيل النظام مع بدء Windows" });
    await waitFor(() => expect(toggle).not.toBeDisabled());
    expect(toggle).toHaveAttribute("aria-checked", "false");
    await user.click(toggle);
    await waitFor(() => expect(toggle).toHaveAttribute("aria-checked", "true"));
    expect(bridge.app.setAutoStart).toHaveBeenCalledWith(true);
    await user.click(toggle);
    await waitFor(() => expect(toggle).toHaveAttribute("aria-checked", "false"));
    expect(bridge.app.setAutoStart).toHaveBeenLastCalledWith(false);
  });
});
