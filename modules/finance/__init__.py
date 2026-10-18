"""Financial workflow on FINORA's existing treasury and general ledger."""


def init_finance(app):
    from .routes import finance_bp
    app.register_blueprint(finance_bp)
    from .source_sync import install
    install()
    # Complete return relationships before concurrent requests configure mappers.
    # Wait until finance is loaded because return funding references its vouchers.
    from modules.sales_returns import models as sales_return_models
