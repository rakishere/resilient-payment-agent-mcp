import pytest
from app.contract import PaymentStatus, validate_payment_id
from app.errors import InvalidPaymentId, NotAuthorized


def test_allowed_id():
    assert validate_payment_id("pi_allowed123") == "pi_allowed123"


def test_forbidden_other_id():
    with pytest.raises(NotAuthorized):
        validate_payment_id("pi_other123")


def test_invalid_id():
    with pytest.raises(InvalidPaymentId):
        validate_payment_id("evil/../../pi_allowed123")


def test_reject_live():
    with pytest.raises(NotAuthorized):
        PaymentStatus.from_stripe({"id": "pi_allowed123", "amount": 2000,
                                   "currency": "usd", "status": "succeeded", "livemode": True})
