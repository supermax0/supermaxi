/** EAN-13 check digit for the first 12 digits. */
export function ean13CheckDigit(first12: string): number {
  let sum = 0;
  for (let i = 0; i < 12; i += 1) sum += Number(first12[i]) * (i % 2 === 0 ? 1 : 3);
  return (10 - (sum % 10)) % 10;
}

/**
 * A scannable in-store EAN-13 (GS1 prefix "2x" is reserved for internal use,
 * so it never collides with a manufacturer barcode). FINORA still rejects a
 * duplicate within the branch on save.
 */
export function generateStoreBarcode(random: () => number = Math.random): string {
  let body = "29";
  for (let i = 0; i < 10; i += 1) body += String(Math.floor(random() * 10));
  return body + String(ean13CheckDigit(body));
}

export function isValidEan13(code: string): boolean {
  return /^\d{13}$/.test(code) && ean13CheckDigit(code.slice(0, 12)) === Number(code[12]);
}
