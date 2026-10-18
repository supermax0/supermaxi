import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useInterfaceSounds } from "./useInterfaceSounds";
import { playSound, unlockSounds } from "@/services/sounds";
import { useWindowManager } from "@/stores/windowManager";
import { useToasts } from "@/stores/toasts";
import { useNotifications } from "@/stores/notifications";
vi.mock("@/services/sounds", () => ({ playSound: vi.fn(), unlockSounds: vi.fn() }));
function Surface() {
  useInterfaceSounds();
  return (
    <>
      <button>حفظ</button>
      <button disabled>معطل</button>
      <button data-sound="off">معاينة</button>
      <input aria-label="كتابة" />
      <select aria-label="اختيار">
        <option>A</option>
        <option>B</option>
      </select>
    </>
  );
}
afterEach(() => {
  cleanup();
  useWindowManager.getState().reset();
  useNotifications.getState().clear();
  vi.clearAllMocks();
});
test("buttons and keyboard activation work, hover and disabled controls stay silent", () => {
  render(<Surface />);
  fireEvent.pointerDown(screen.getByText("حفظ"));
  fireEvent.click(screen.getByText("حفظ"));
  expect(unlockSounds).toHaveBeenCalled();
  expect(playSound).toHaveBeenCalledWith("click");
  vi.mocked(playSound).mockClear();
  fireEvent.click(screen.getByLabelText("كتابة"));
  expect(playSound).toHaveBeenCalledWith("click");
  vi.mocked(playSound).mockClear();
  fireEvent.click(screen.getByText("معطل"));
  fireEvent.click(screen.getByText("معاينة"));
  fireEvent.mouseOver(screen.getByText("حفظ"));
  expect(playSound).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("اختيار"), { target: { value: "B" } });
  expect(playSound).toHaveBeenCalledWith("toggle");
});
test("typing is connected globally and unmount cancels its pending sound", () => {
  vi.useFakeTimers();
  const mounted = render(<Surface />);
  fireEvent.keyDown(screen.getByLabelText("كتابة"), { key: "ع" });
  vi.advanceTimersByTime(100);
  expect(playSound).toHaveBeenCalledWith("typing");
  vi.mocked(playSound).mockClear();
  fireEvent.keyDown(screen.getByLabelText("كتابة"), { key: "x" });
  mounted.unmount();
  vi.advanceTimersByTime(100);
  expect(playSound).not.toHaveBeenCalled();
  vi.useRealTimers();
});
test("window transitions and actual operation feedback have their own cues, unmount removes subscriptions", () => {
  const mounted = render(<Surface />);
  act(() => useWindowManager.getState().open("products"));
  expect(playSound).toHaveBeenCalledWith("open");
  act(() => useWindowManager.getState().close());
  expect(playSound).toHaveBeenCalledWith("close");
  act(() => {
    useToasts.getState().push("success", "تم الحفظ");
  });
  expect(playSound).toHaveBeenCalledWith("success");
  act(() => useNotifications.getState().add({ tone: "warning", title: "تحقق", body: "مخزون" }));
  expect(playSound).toHaveBeenCalledWith("warning");
  mounted.unmount();
  vi.mocked(playSound).mockClear();
  useWindowManager.getState().open("purchases");
  expect(playSound).not.toHaveBeenCalled();
});
