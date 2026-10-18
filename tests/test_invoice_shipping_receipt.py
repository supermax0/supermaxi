from types import SimpleNamespace
from bs4 import BeautifulSoup
from utils.invoice_shipping_receipt import attach_shipping_receipt


def test_theme_receipt_stays_inside_customer_card_and_escapes_external_reference():
    order=SimpleNamespace(shipping_barcode='<script>alert(1)</script>',shipping_barcodes_json=None,shipping_company=SimpleNamespace(name='Carrier & Co'))
    html='<html><body><main class="invoice"><section class="customer-info">Original</section><table><tr><td>Item</td></tr></table></main></body></html>'
    output=attach_shipping_receipt(html,order);doc=BeautifulSoup(output,'html.parser')
    assert doc.select_one('.customer-info [data-finora-shipping-receipt]')
    assert not doc.find('script')
    assert '<script>alert(1)</script>' in doc.get_text() and 'Carrier & Co' in doc.get_text()
    assert str(doc.find('table'))=='<table><tr><td>Item</td></tr></table>'
    assert attach_shipping_receipt(output,order)==output


def test_no_receipt_preserves_original_markup_and_custom_page_has_safe_fallback():
    order=SimpleNamespace(shipping_barcode=None,shipping_barcodes_json=None)
    html='<html><body><article class="page-shell">Invoice</article></body></html>'
    assert attach_shipping_receipt(html,order)==html
    order.shipping_barcode='SHIP-002'
    assert BeautifulSoup(attach_shipping_receipt(html,order),'html.parser').select_one('.page-shell [data-finora-shipping-receipt]')
