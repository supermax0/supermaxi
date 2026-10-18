from routes.orders import required_order_mutation_permission
from routes.permissions import DEFAULT_PERMISSIONS


def test_order_action_permissions_are_exposed_independently():
    names = {name for name, _description in DEFAULT_PERMISSIONS}

    assert {"view_orders", "pay_orders", "return_orders", "delete_orders"} <= names


def test_payment_and_return_requests_require_different_permissions():
    assert required_order_mutation_permission(
        "/orders/payment", {"payment": "مسدد"}
    ) == "pay_orders"
    assert required_order_mutation_permission(
        "/orders/payment", {"payment": "جزئي"}
    ) == "pay_orders"
    assert required_order_mutation_permission(
        "/orders/payment", {"payment": "راجع"}
    ) == "return_orders"
    assert required_order_mutation_permission(
        "/orders/bulk-return", {}
    ) == "return_orders"


def test_delete_cancel_and_regular_edits_require_their_own_permissions():
    assert required_order_mutation_permission(
        "/orders/delete/15", {}
    ) == "delete_orders"
    assert required_order_mutation_permission(
        "/orders/cancel/15", {}
    ) == "delete_orders"
    assert required_order_mutation_permission(
        "/orders/update", {"status": "ملغي"}
    ) == "delete_orders"
    assert required_order_mutation_permission(
        "/orders/update", {"status": "جاري الشحن"}
    ) == "manage_orders"
    assert required_order_mutation_permission(
        "/orders/quick-edit/15", {}
    ) == "manage_orders"
