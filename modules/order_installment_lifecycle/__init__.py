# -*- coding: utf-8 -*-
"""Order installment lifecycle — timed auto-settle mode for POS orders.

Distinct from modules/installments (monthly installment contracts).
"""

from modules.order_installment_lifecycle.routes import order_installment_bp


def init_order_installment_lifecycle(app):
    app.register_blueprint(order_installment_bp)
