from types import SimpleNamespace

from utils.shipping_barcodes import should_move_order_to_shipping_on_barcode_save


def _invoice(status, payment_status="غير مسدد"):
    return SimpleNamespace(status=status, payment_status=payment_status)


def test_should_move_to_shipping_only_for_pre_shipment_orders():
    assert should_move_order_to_shipping_on_barcode_save(_invoice("تم الطلب")) is True
    assert should_move_order_to_shipping_on_barcode_save(_invoice("معباة")) is True


def test_should_not_move_delivered_or_paid_orders_back_to_shipping():
    assert should_move_order_to_shipping_on_barcode_save(_invoice("تم التوصيل", "مسدد")) is False
    assert should_move_order_to_shipping_on_barcode_save(_invoice("جاري الشحن", "غير مسدد")) is False
    assert should_move_order_to_shipping_on_barcode_save(_invoice("تم التوصيل", "غير مسدد")) is False


def test_should_not_move_canceled_or_returned_orders():
    assert should_move_order_to_shipping_on_barcode_save(_invoice("ملغي", "ملغي")) is False
    assert should_move_order_to_shipping_on_barcode_save(_invoice("راجع", "راجع")) is False
