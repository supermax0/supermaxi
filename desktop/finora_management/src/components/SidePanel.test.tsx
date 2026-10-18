import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FeatureHelp } from "./FeatureHelp";
import { SidePanel } from "./SidePanel";

it("Escape closes the help before closing its financial detail panel", async () => {
  const close = vi.fn();
  const user = userEvent.setup();
  render(
    <SidePanel open title="تفاصيل السند" onClose={close}>
      <FeatureHelp text="حصص الأقساط جزء من دفعة الفاتورة" />
    </SidePanel>,
  );
  await user.click(screen.getByRole("button", { name: "شرح الميزة" }));
  expect(screen.getByRole("note")).toBeVisible();
  await user.keyboard("{Escape}");
  await waitFor(() => expect(screen.queryByRole("dialog", { name: "شرح الميزة" })).not.toBeInTheDocument());
  expect(close).not.toHaveBeenCalled();
  expect(screen.getByRole("complementary", { name: "تفاصيل السند" })).toBeVisible();
  await user.keyboard("{Escape}");
  expect(close).toHaveBeenCalledTimes(1);
});
