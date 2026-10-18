import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it } from "vitest";
import { SoundSettings } from "./SoundSettings";
import { useSound } from "./preferences";
beforeEach(() =>
  useSound.setState({
    preferences: { enabled: true, mode: "live", volume: 0.65, approvals: true, important: true },
    status: "ready",
  }),
);
it("lets the operator adjust and persist notification controls without changing AI replies", () => {
  render(<SoundSettings />);
  fireEvent.change(screen.getByLabelText("طريقة التنبيه"), { target: { value: "chime" } });
  fireEvent.change(screen.getByRole("slider"), { target: { value: "30" } });
  fireEvent.click(screen.getByLabelText("طلبات الموافقة"));
  expect(useSound.getState().preferences).toMatchObject({ mode: "chime", volume: 0.3, approvals: false });
  expect(JSON.parse(localStorage.getItem("finora-core.notification-sound") ?? "{}")).toMatchObject({
    volume: 0.3,
  });
  fireEvent.click(screen.getByLabelText("تنبيهات مسموعة"));
  expect(screen.getByRole("button", { name: "تجربة الصوت" })).toBeDisabled();
  expect(screen.getByRole("status")).toHaveTextContent("مكتومة");
});
