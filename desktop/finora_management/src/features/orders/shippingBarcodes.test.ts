import { initialBarcodes, shippingBarcodeProblem, shippingSlots } from "./shippingBarcodes";

describe("shipping barcode slots", () => {
  it("creates one slot per piece, numbered when an item has several", () => {
    expect(
      shippingSlots([
        { name: "شاشة", qty: 2 },
        { name: "مكيف", qty: 1 },
      ]).map((s) => s.label),
    ).toEqual(["شاشة — 1", "شاشة — 2", "مكيف"]);
    expect(shippingSlots([])).toEqual([{ label: "باركود الشحن" }]);
  });

  it("lays saved barcodes onto the slots", () => {
    expect(initialBarcodes(3, { shipping_barcodes: ["A1", "A2"] })).toEqual(["A1", "A2", ""]);
    expect(initialBarcodes(1, { shipping_barcode: "B9" })).toEqual(["B9"]);
    expect(initialBarcodes(1, { shipping_barcode: "—" })).toEqual([""]);
  });

  it("reports what FINORA would refuse", () => {
    expect(shippingBarcodeProblem(null, ["A"])).toMatch(/شركة النقل/);
    expect(shippingBarcodeProblem(1, ["A", ""])).toMatch(/لكل قطعة/);
    expect(shippingBarcodeProblem(1, ["A", "A"])).toMatch(/تكرار/);
    expect(shippingBarcodeProblem(1, ["A", "B"])).toBeNull();
  });
});
