import type { OfflineEngine } from "./offlineEngine";

export function receiptHtml(receipt: Awaited<ReturnType<OfflineEngine["posReceipt"]>>): string {
  const escape = (value: unknown) =>
    String(value).replace(
      /[&<>"']/g,
      (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] ?? c,
    );
  const money = (n: number) => new Intl.NumberFormat("ar-IQ").format(n) + " د.ع";
  const sale = receipt.sale;
  const timestamp = new Date(receipt.created).toLocaleString("ar-IQ", {
    timeZone: "Asia/Baghdad",
    hour12: receipt.timeFormat !== "24",
  });
  return `<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'"><title>إيصال FINORA</title>
    <style>body{font:16px Tahoma,sans-serif;color:#25213d;margin:32px}h1{color:#801d40}small{overflow-wrap:anywhere}table{width:100%;border-collapse:collapse;margin:24px 0}td,th{padding:12px;border-bottom:1px solid #e6ddf4;text-align:right}.total{color:#7438dc;font-size:24px}</style>
    <h1>FINORA</h1><h2>إيصال بيع محلي</h2><small dir="ltr">${escape(receipt.number)}</small>
    <p>الزبون: ${escape(sale.customerName)}</p><p>${escape(timestamp)}</p>
    <table><thead><tr><th>الصنف</th><th>الكمية</th><th>السعر</th><th>المبلغ</th></tr></thead><tbody>${sale.items.map((i, n) => `<tr><td>${escape(receipt.names[n])} ${escape(i.variant_color ?? "")}</td><td>${i.qty}</td><td>${money(i.price)}</td><td>${money(i.price * i.qty)}</td></tr>`).join("")}</tbody></table>
    <p>الخصم: ${money(sale.discount)}</p><p class="total">الإجمالي: ${money(sale.total)}</p>
    <p>الدفع: ${sale.payment === "credit" ? "آجل — غير مسدد" : sale.payment === "cash" ? "نقدي — مستلم محلياً" : "تحويل — مسجل محلياً"}</p>
    <p>${receipt.invoice ? `رقم الفاتورة على السيرفر: ${escape(receipt.invoice)}` : "بانتظار المزامنة مع السيرفر"}</p></html>`;
}
