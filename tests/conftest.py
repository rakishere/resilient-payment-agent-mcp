import pytest

@pytest.fixture(autouse=True)
def allow_test_payment(monkeypatch):
    monkeypatch.setenv("ALLOWED_PAYMENT_INTENT_IDS", "pi_allowed123")
