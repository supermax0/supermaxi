import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useSession } from "@/stores/session";
import { useDisplayTime, useTimeFormat } from "@/stores/displayTime";
import { useDisplayPreferences } from "@/hooks/useDisplayPreferences";
import { createFinoraFixture, ADMIN_SESSION } from "@/test/fixtures";
import { installMockBridge, removeMockBridge } from "@/test/mockBridge";
import { formatDateTime } from "@/utils/format";
import { sessionSchema } from "@/api/finora/schemas";
import { SettingsDialog } from "./SettingsDialog";

function Draft() {
  useDisplayPreferences(true);
  useTimeFormat();
  return (
    <>
      <input aria-label="مسودة" defaultValue="طلب غير محفوظ" />
      <output>{formatDateTime("2026-10-21T16:30:00Z")}</output>
    </>
  );
}

afterEach(() => {
  useSession.getState().signedOut("signed_out");
  removeMockBridge();
});

it("saves the company clock and updates open views without clearing a draft", async () => {
  const fixture = createFinoraFixture();
  installMockBridge(fixture.handler);
  useSession.getState().signedIn(sessionSchema.parse(ADMIN_SESSION));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <Draft />
      <SettingsDialog open onClose={vi.fn()} />
    </QueryClientProvider>,
  );
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: /المظهر والاختصارات/ }));
  await user.click(await screen.findByRole("radio", { name: /24 ساعة/ }));
  await waitFor(() => expect(useDisplayTime.getState().format).toBe("24"));
  expect(screen.getByText("2026-10-21 19:30")).toBeInTheDocument();
  expect(screen.getByLabelText("مسودة")).toHaveValue("طلب غير محفوظ");
  await waitFor(() => expect(useSession.getState().session?.display_time_format).toBe("24"));
  expect(
    fixture.calls.some(
      (r) =>
        r.path.endsWith("display-preferences") &&
        r.method === "POST" &&
        JSON.stringify(r.body) === '{"time_format":"24"}',
    ),
  ).toBe(true);
  client.clear();
});

it("does not allow staff without settings permission to change the clock", async () => {
  const fixture = createFinoraFixture();
  installMockBridge(fixture.handler);
  useSession.getState().signedIn({ ...ADMIN_SESSION, permissions: [] });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <SettingsDialog open onClose={vi.fn()} />
    </QueryClientProvider>,
  );
  await userEvent.setup().click(screen.getByRole("button", { name: /المظهر والاختصارات/ }));
  expect(await screen.findByRole("radio", { name: /24 ساعة/ })).toBeDisabled();
  expect(
    fixture.calls.filter((r) => r.path.endsWith("display-preferences") && r.method === "POST"),
  ).toHaveLength(0);
  client.clear();
});
