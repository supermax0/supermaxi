import { ean13CheckDigit, generateStoreBarcode, isValidEan13 } from "./barcode";

describe("store barcodes", () => {
  it("computes the EAN-13 check digit", () => {
    expect(ean13CheckDigit("400638133393")).toBe(1);
    expect(isValidEan13("4006381333931")).toBe(true);
    expect(isValidEan13("4006381333932")).toBe(false);
  });

  it("generates valid in-store codes with the 29 prefix", () => {
    for (let i = 0; i < 50; i += 1) {
      const code = generateStoreBarcode();
      expect(code).toMatch(/^29\d{11}$/);
      expect(isValidEan13(code)).toBe(true);
    }
  });
});
