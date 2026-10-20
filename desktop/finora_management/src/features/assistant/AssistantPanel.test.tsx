import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AssistantShell } from "./AssistantPanel";
import { useAssistant } from "./state";
import { useSession } from "@/stores/session";
import { useWorkspace } from "@/features/workspace/state";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { installMockBridge, removeMockBridge, SESSION_PAYLOAD } from "@/test/mockBridge";
import { DEFAULT_LOCAL_ASSISTANT, type HistoryRow } from "@shared/localAssistant";
import type { FinoraDesktopBridge } from "@shared/ipc";
import { sessionEnvelopeSchema } from "@/api/finora/schemas";

afterEach(() => {
  useAssistant.getState().reset("");
  useAssistant.setState({ open: false, settings: { ...DEFAULT_LOCAL_ASSISTANT } });
  useSession.setState({ session: null });
  useWorkspace.setState({ identity: "" });
  removeMockBridge();
});

it("does not restore a delayed encrypted history after the user clears the conversation", async () => {
  const bridge: FinoraDesktopBridge = installMockBridge(() => {
    throw Error("Unexpected financial request");
  });
  const scope = "a".repeat(64),
    rows: HistoryRow[] = [{ role: "assistant", text: "old saved financial answer", at: 1 }];
  let finish: ((value: { scope: string; rows: HistoryRow[] }) => void) | undefined;
  const delayed = new Promise<{ scope: string; rows: HistoryRow[] }>((resolve) => {
    finish = resolve;
  });
  const historyLoad = vi
    .fn()
    .mockImplementationOnce(() => delayed)
    .mockResolvedValue({ scope, rows });
  const historySave = vi.fn().mockResolvedValue(undefined);
  bridge.assistant = {
    settings: vi
      .fn()
      .mockResolvedValue({ settings: { ...DEFAULT_LOCAL_ASSISTANT, remember: true }, hasToken: false }),
    configure: vi.fn(),
    probe: vi.fn(),
    chat: vi.fn(),
    cancel: vi.fn().mockResolvedValue(undefined),
    historyLoad,
    historySave,
    transcribe: vi.fn(),
  };
  useSession.setState({
    session: sessionEnvelopeSchema.parse({ ok: true, session: SESSION_PAYLOAD }),
  });
  useWorkspace.setState({ identity: "current-account" });
  const view = render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <AssistantShell />
    </QueryClientProvider>,
  );
  await waitFor(() => expect(historyLoad).toHaveBeenCalledTimes(1));
  act(() =>
    useAssistant.setState({
      open: true,
      messages: [{ id: "session", role: "user", text: "current question", at: 2 }],
    }),
  );
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "مسح المحادثة" }));
  await user.click(
    within(screen.getByRole("dialog", { name: "مسح محادثة المساعد" })).getByRole("button", {
      name: "مسح المحادثة",
    }),
  );
  await waitFor(() => expect(historySave).toHaveBeenCalledWith({ expectedScope: scope, rows: [] }));
  await act(async () => {
    finish?.({ scope, rows });
    await delayed;
  });
  expect(useAssistant.getState().messages).toEqual([]);
  expect(screen.queryByText("old saved financial answer")).not.toBeInTheDocument();
  view.unmount();
});

it("does not render an old account's conversation before the new scope effect commits", () => {
  useSession.setState({ session: null });
  useWorkspace.setState({ identity: "different-account" });
  useAssistant.setState({
    open: true,
    scope: "previous-account",
    messages: [{ id: "old", role: "assistant", text: "private previous account balance", at: 1 }],
    training: null,
  });
  try {
    const html = renderToStaticMarkup(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <AssistantShell />
      </QueryClientProvider>,
    );
    expect(html).toContain("فتح مساعد فينورا");
    expect(html).not.toContain("private previous account balance");
    expect(html).not.toContain('class="finora-assistant-panel"');
  } finally {
    useAssistant.getState().reset("");
    useAssistant.setState({ open: false });
    useWorkspace.setState({ identity: "" });
  }
});
