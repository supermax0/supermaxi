from types import SimpleNamespace

import pytest

from models.rotating_savings import RotatingSavingPayment
from utils.rotating_savings_service import (
    RotatingSavingError,
    _validated_prior_payment_values,
)


def test_prior_payment_amount_defaults_to_monthly_amount():
    count, amount = _validated_prior_payment_values(
        {"prior_payments_count": "10", "prior_payment_amount": ""},
        monthly=1_000_000,
        months=20,
    )
    assert count == 10
    assert amount == 1_000_000


def test_money_value_cannot_be_entered_as_prior_payment_count():
    with pytest.raises(RotatingSavingError, match="لا يمكن أن يتجاوز"):
        _validated_prior_payment_values(
            {"prior_payments_count": "10000000", "prior_payment_amount": "1000000"},
            monthly=1_000_000,
            months=20,
        )


def test_reversed_payment_displays_zero_effective_amount():
    payment = SimpleNamespace(amount=10_000_000_000_000, status="reversed")
    effective_amount = RotatingSavingPayment.effective_amount.fget
    assert effective_amount(payment) == 0

    payment.status = "paid"
    assert effective_amount(payment) == 10_000_000_000_000
