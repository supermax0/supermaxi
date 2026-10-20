import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { EditInvoiceDialog } from "./EditInvoiceDialog";

it("preserves the full order number when the parent refreshes with a new close callback", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const user = userEvent.setup();
  const close = vi.fn();
  const view = render(
    <QueryClientProvider client={client}>
      <EditInvoiceDialog open onClose={() => close()} />
    </QueryClientProvider>,
  );
  await user.type(screen.getByRole("textbox", { name: "رقم الطلب" }), "10045");
  view.rerender(
    <QueryClientProvider client={client}>
      <EditInvoiceDialog open onClose={() => close()} />
    </QueryClientProvider>,
  );
  expect(screen.getByRole("textbox", { name: "رقم الطلب" })).toHaveValue("10045");
  await user.keyboard("{Escape}");
  expect(close).toHaveBeenCalledTimes(1);
});
