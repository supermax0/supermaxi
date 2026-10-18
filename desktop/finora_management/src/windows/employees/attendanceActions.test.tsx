import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { WorkspaceTable } from "./EmployeesWindow";
import type { HRWorkspaceRow } from "@/api/finora/hr";

const scheduled: HRWorkspaceRow = {
  id: null,
  person_id: 7,
  person_name: "موظف اختبار",
  code: "EMP-7",
  state: "scheduled",
  check_in_at: null,
  version: 0,
};

it("does not treat a scheduled employee's table key as an attendance record", () => {
  render(
    <WorkspaceTable
      tab="attendance"
      rows={[scheduled]}
      loading={false}
      fetching={false}
      error={null}
      onRetry={vi.fn()}
      can={() => true}
      tools={undefined}
      setAction={vi.fn()}
      onOpen={vi.fn()}
      online
    />,
  );
  expect(screen.getByText("موظف اختبار")).toBeVisible();
  expect(screen.queryByRole("button", { name: "تصحيح" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "طلب تصحيح" })).not.toBeInTheDocument();
});

it("uses the actual attendance ID and blocks stale correction actions during a refresh", async () => {
  const setAction = vi.fn();
  const recorded = {
    ...scheduled,
    id: 42,
    version: 3,
    state: "present",
    check_in_at: "2026-10-11T06:00:00Z",
  };
  const props = {
    tab: "attendance" as const,
    rows: [recorded],
    loading: false,
    fetching: false,
    error: null,
    onRetry: vi.fn(),
    can: () => true,
    tools: undefined,
    setAction,
    onOpen: vi.fn(),
    online: true,
  };
  const { rerender } = render(<WorkspaceTable {...props} />);
  await userEvent.setup().click(screen.getByRole("button", { name: "طلب تصحيح" }));
  expect(setAction).toHaveBeenCalledWith(
    expect.objectContaining({
      action: "attendance.correction_request",
      payload: { person_id: 7, attendance_id: 42, attendance_version: 3 },
    }),
  );
  rerender(<WorkspaceTable {...props} fetching />);
  expect(screen.getByRole("button", { name: "طلب تصحيح" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "تصحيح" })).toBeDisabled();
});
