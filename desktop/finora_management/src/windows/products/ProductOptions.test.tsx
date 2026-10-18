import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { ProductOptions, type OptionsDraft } from "./ProductOptions";

function Editor({ existing = [] }: { existing?: Parameters<typeof ProductOptions>[0]["existing"] }) {
  const [value, onChange] = useState<OptionsDraft | null>(null);
  return (
    <>
      <ProductOptions
        existing={existing}
        axes={[]}
        value={value}
        onChange={onChange}
        create={false}
        currentStock={6}
        openingStock={0}
        supported
        photos={{}}
        onPhotoChange={() => {}}
        serverUrl={null}
        busy={false}
        priceLocked={false}
      />
      <output data-testid="draft">{JSON.stringify(value)}</output>
    </>
  );
}

it("supports size alone with optional prices, explicit stock allocation and accessible help", async () => {
  const user = userEvent.setup();
  render(<Editor />);
  expect(screen.queryByLabelText("قيمة اللون")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "شرح الميزة" }));
  expect(screen.getByRole("note")).toHaveTextContent("اختياري");
  await user.keyboard("{Escape}");
  await waitFor(() => expect(screen.queryByRole("note")).not.toBeInTheDocument());
  await user.click(screen.getByRole("checkbox", { name: "هذا المنتج عنده خيارات" }));
  await user.click(screen.getByRole("button", { name: "الحجم فقط" }));
  await user.type(screen.getByLabelText("قيمة الحجم"), "50 مل");
  await user.click(screen.getByRole("button", { name: "إضافة خيار" }));
  expect(screen.queryByLabelText("قيمة اللون")).not.toBeInTheDocument();
  expect(screen.getByLabelText("مخزون الحجم: 50 مل")).toHaveValue(6);
  expect(screen.getByLabelText("سعر بيع الحجم: 50 مل")).toHaveValue(null);
  await user.type(screen.getByLabelText("قيمة الحجم"), "100 مل");
  await user.click(screen.getByRole("button", { name: "إضافة خيار" }));
  await user.type(screen.getByLabelText("سعر بيع الحجم: 100 مل"), "25000");
  const draft = JSON.parse(screen.getByTestId("draft").textContent ?? "{}");
  expect(draft).toMatchObject({
    axes: ["الحجم"],
    expected_stock: 6,
    rows: [
      { attributes: { الحجم: "50 مل" }, qty: 6, sale_price: null },
      { attributes: { الحجم: "100 مل" }, qty: 0, sale_price: 25000 },
    ],
  });
});

it("retains saved options and offers stock distribution when a second attribute is added", async () => {
  const user = userEvent.setup();
  render(<Editor existing={[{ id: 10, name: "أسود", qty: 6, image_url: "" }]} />);
  expect(screen.getByLabelText("مخزون أسود")).toBeDisabled();
  expect(screen.queryByRole("button", { name: "إزالة خيار أسود" })).not.toBeInTheDocument();
  await user.type(screen.getByLabelText("اسم صفة جديدة"), "المقاس");
  await user.click(screen.getByRole("button", { name: "إضافة صفة" }));
  await user.type(screen.getByLabelText("قيمة اللون"), "أسود");
  await user.type(screen.getByLabelText("قيمة المقاس"), "M");
  await user.click(screen.getByRole("button", { name: "إضافة خيار" }));
  await user.selectOptions(screen.getByLabelText("مصدر مخزون اللون: أسود / المقاس: M"), "10");
  expect(screen.getByLabelText("مخزون اللون: أسود / المقاس: M")).toBeEnabled();
  const draft = JSON.parse(screen.getByTestId("draft").textContent ?? "{}");
  expect(draft.rows[0]).toMatchObject({ id: 10, active: false, qty: 6 });
  expect(draft.rows[1]).toMatchObject({ source_id: 10, qty: 0 });
});
