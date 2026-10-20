import { QueryClient } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MotionGlobalConfig } from "framer-motion";
import type { FinoraResponse } from "@shared/ipc";
import { useConnection } from "@/stores/connection";
import { useSession } from "@/stores/session";
import { useWindowManager } from "@/stores/windowManager";
import { createFinoraFixture } from "@/test/fixtures";
import { installMockBridge, removeMockBridge, SESSION_PAYLOAD, type RequestHandler } from "@/test/mockBridge";
import { App } from "./App";

const signedIn: FinoraResponse = {
  ok: true,
  status: 200,
  data: {
    ok: true,
    session: { ...SESSION_PAYLOAD, permissions: [...SESSION_PAYLOAD.permissions, "can_manage_inventory"] },
  },
};
const signedOut: FinoraResponse = {
  ok: false,
  failure: "http",
  status: 401,
  data: { ok: false, error: "انتهت الجلسة، سجّل الدخول من جديد", code: "unauthenticated" },
};

/** Session answers come from the test; everything else from the in-memory FINORA fixture. */
function renderApp(handler: RequestHandler) {
  const fixture = createFinoraFixture();
  const bridge = installMockBridge((request) =>
    request.path.startsWith("/api/v1/desktop/") ? handler(request) : fixture.handler(request),
  );
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<App queryClient={queryClient} />);
  return bridge;
}

beforeAll(() => {
  MotionGlobalConfig.skipAnimations = true;
});

afterEach(() => {
  removeMockBridge();
  useWindowManager.getState().reset();
  useSession.setState({ status: "unknown", session: null, reason: null });
  useConnection.getState().setStatus("online");
});

describe("FINORA Management shell", () => {
  it("shows sign-in when there is no FINORA session, then the shell after signing in", async () => {
    let authenticated = false;
    const bridge = renderApp((request) => {
      if (request.path === "/api/v1/desktop/auth/login") {
        authenticated = true;
        return signedIn;
      }
      return authenticated ? signedIn : signedOut;
    });
    const user = userEvent.setup();

    const form = await screen.findByRole("form", { name: "تسجيل الدخول إلى FINORA" });
    await user.type(within(form).getByLabelText("معرف الشركة"), "ACME");
    await user.type(within(form).getByLabelText("اسم المستخدم"), "sara");
    await user.type(within(form).getByLabelText("كلمة المرور"), "secret-pass");
    await user.click(within(form).getByRole("button", { name: "تسجيل الدخول" }));

    expect(await screen.findByRole("navigation", { name: "النوافذ" })).toBeInTheDocument();
    expect(bridge.finora.request).toHaveBeenCalledWith(
      expect.objectContaining({ body: { tenant_slug: "acme", username: "sara", password: "secret-pass" } }),
    );
    expect(screen.getByRole("main", { name: "الرئيسية" })).toBeInTheDocument();
    expect(screen.getAllByText("أهلاً سارة")).toHaveLength(1);
  });

  it("shows FINORA's error and clears the password on a failed sign-in", async () => {
    renderApp(() => ({
      ok: false,
      failure: "http",
      status: 401,
      data: { ok: false, error: "بيانات الدخول غير صحيحة", code: "invalid_credentials" },
    }));
    const user = userEvent.setup();
    const form = await screen.findByRole("form", { name: "تسجيل الدخول إلى FINORA" });
    await user.type(within(form).getByLabelText("معرف الشركة"), "acme");
    await user.type(within(form).getByLabelText("اسم المستخدم"), "sara");
    await user.type(within(form).getByLabelText("كلمة المرور"), "wrong");
    await user.click(within(form).getByRole("button", { name: "تسجيل الدخول" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("بيانات الدخول غير صحيحة");
    expect(within(form).getByLabelText("كلمة المرور")).toHaveValue("");
  });

  it("offers exactly the three phase-one windows and switches between them", async () => {
    renderApp(() => signedIn);
    const user = userEvent.setup();
    const nav = await screen.findByRole("navigation", { name: "النوافذ" });
    const buttons = within(nav).getAllByRole("button");
    expect(buttons.map((b) => b.textContent)).toEqual(["الطلبات", "المشتريات", "المنتجات"]);

    await user.click(within(nav).getByRole("button", { name: /الطلبات/ }));
    expect(await screen.findByRole("dialog", { name: "إدارة الطلبات" })).toBeInTheDocument();

    await user.click(within(nav).getByRole("button", { name: /المنتجات/ }));
    expect(await screen.findByRole("dialog", { name: "إدارة المنتجات" })).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "إدارة الطلبات" })).not.toBeInTheDocument(),
    );
    expect(within(nav).getByRole("button", { name: /المنتجات/ })).toHaveAttribute("aria-pressed", "true");
  });

  it("rapid switching leaves exactly one window on stage", async () => {
    renderApp(() => signedIn);
    await screen.findByRole("navigation", { name: "النوافذ" });
    act(() => {
      for (const id of ["orders", "products", "purchases", "orders", "purchases"] as const) {
        useWindowManager.getState().open(id);
      }
    });
    await waitFor(() => expect(document.querySelectorAll('[data-state="open"]')).toHaveLength(1));
    expect(screen.getByRole("dialog", { name: "إدارة المشتريات" })).toBeInTheDocument();
  });

  it("keyboard: Ctrl+2 opens purchases, Escape closes it, Ctrl+K opens quick search", async () => {
    renderApp(() => signedIn);
    const user = userEvent.setup();
    await screen.findByRole("navigation", { name: "النوافذ" });

    await user.keyboard("{Control>}2{/Control}");
    expect(await screen.findByRole("dialog", { name: "إدارة المشتريات" })).toBeInTheDocument();
    await user.keyboard("{Escape}");
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "إدارة المشتريات" })).not.toBeInTheDocument(),
    );

    await user.keyboard("{Control>}k{/Control}");
    const palette = await screen.findByRole("dialog", { name: "بحث سريع" });
    await user.type(within(palette).getByLabelText("بحث"), "المنتجات");
    await user.keyboard("{Enter}");
    expect(await screen.findByRole("dialog", { name: "إدارة المنتجات" })).toBeInTheDocument();
  });

  it("window controls in the window header minimize back to the button", async () => {
    renderApp(() => signedIn);
    const user = userEvent.setup();
    const nav = await screen.findByRole("navigation", { name: "النوافذ" });
    await user.click(within(nav).getByRole("button", { name: /الطلبات/ }));
    const dialog = await screen.findByRole("dialog", { name: "إدارة الطلبات" });
    await user.click(within(dialog).getByRole("button", { name: "تصغير إلى الشريط العلوي" }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "إدارة الطلبات" })).not.toBeInTheDocument(),
    );
    expect(within(nav).getByLabelText("مصغّرة")).toBeInTheDocument();
  });

  it("native window controls go through the Electron bridge", async () => {
    const bridge = renderApp(() => signedIn);
    const user = userEvent.setup();
    await screen.findByRole("navigation", { name: "النوافذ" });
    const controls = screen.getByRole("group", { name: "التحكم بنافذة التطبيق" });
    await user.click(within(controls).getByRole("button", { name: "تكبير" }));
    expect(bridge.window.toggleMaximize).toHaveBeenCalledTimes(1);
    expect(await within(controls).findByRole("button", { name: "استعادة" })).toBeInTheDocument();
    await user.click(within(controls).getByRole("button", { name: "تصغير" }));
    expect(bridge.window.minimize).toHaveBeenCalledTimes(1);
  });

  it("an expired session returns to sign-in with an explanation", async () => {
    let expired = false;
    renderApp(() => (expired ? signedOut : signedIn));
    await screen.findByRole("navigation", { name: "النوافذ" });
    expired = true;
    await act(async () => {
      await revalidateSession();
    });
    expect(await screen.findByText("انتهت الجلسة، سجّل الدخول من جديد.")).toBeInTheDocument();
  });

  it("losing FINORA shows the offline banner; recovering hides it", async () => {
    let reachable = true;
    renderApp(() => (reachable ? signedIn : { ok: false, failure: "network", detail: "ECONNREFUSED" }));
    const user = userEvent.setup();
    await screen.findByRole("navigation", { name: "النوافذ" });

    reachable = false;
    await act(async () => {
      await revalidateSession();
    });
    expect(await screen.findByText("لا يوجد اتصال بـ FINORA")).toBeInTheDocument();

    reachable = true;
    const banner = screen.getByText("لا يوجد اتصال بـ FINORA").closest('[role="status"]');
    expect(banner).not.toBeNull();
    await user.click(within(banner as HTMLElement).getByRole("button", { name: "إعادة المحاولة" }));
    await waitFor(() => expect(screen.queryByText("لا يوجد اتصال بـ FINORA")).not.toBeInTheDocument());
  });
});

/** Same call the periodic revalidation makes. */
async function revalidateSession() {
  const { finora } = await import("@/api/finora");
  await finora.auth.session().catch(() => undefined);
}
