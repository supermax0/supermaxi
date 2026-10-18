"""Keep original lines visible and disclose posted credits in every invoice theme."""
from modules.sales_returns.facts import summary
from utils.invoice_shipping_receipt import _ReceiptLocation


def attach_return_summary(html, invoice):
    if 'data-finora-sales-returns' in html:
        return html
    values = summary(invoice)
    if values is None:
        return html
    document = _ReceiptLocation(html)
    document.feed(html)
    document.close()
    customer = next((node for node in document.nodes if node['customer'] and node['close'] is not None), None)
    root = customer or next((node for node in document.nodes if node['root'] and node['tag'] != 'body'), None) or next(
        (node for node in document.nodes if node['tag'] == 'body'), None)
    if root is None:
        return html
    ids = '، '.join(f'#{value}' for value in values['document_ids'])
    block = ('<div data-finora-sales-returns dir="rtl" style="font-size:11px;line-height:1.6;'
        'padding:6px;margin:6px 0;border:1px solid #64748b;border-radius:4px;break-inside:avoid">'
        '<strong>تسوية المرتجعات</strong>'
        f'<div>أصل البيع: {values["original_total"]:,} د.ع · المرتجع: {values["credit"]:,} د.ع'
        f' · صافي البيع: {values["net_total"]:,} د.ع</div>'
        f'<div>مستندات المرتجع: {ids} · البنود أدناه تعرض أصل البيع.</div></div>')
    position = customer['close'] if customer is not None else root['open']
    return html[:position] + block + html[position:]
