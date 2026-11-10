import httpx
import pytest
from app.errors import NotAuthorized, PaymentNotFound, ProviderUnavailable
from app.stripe_api import StripeReadAdapter, stripe_test_key

@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv("STRIPE_TEST_KEY", "sk_test_FAKE_NOT_REAL")
    stripe_test_key.cache_clear()
    yield
    stripe_test_key.cache_clear()


def test_get_only_and_sandbox():
    def mock(req):
        assert req.method == "GET"
        assert req.url.path.endswith("/pi_allowed123")
        return httpx.Response(200, json={"id": "pi_allowed123", "amount": 2000,
                                         "currency": "usd", "status": "succeeded", "livemode": False})
    adapter = StripeReadAdapter(client=httpx.Client(transport=httpx.MockTransport(mock)))
    assert adapter.get_status("pi_allowed123").status == "succeeded"


def test_404_no_fallback():
    adapter = StripeReadAdapter(client=httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(404))))
    with pytest.raises(PaymentNotFound):
        adapter.get_status("pi_allowed123")


def test_live_response_blocked():
    adapter = StripeReadAdapter(client=httpx.Client(transport=httpx.MockTransport(
        lambda req: httpx.Response(200, json={"id": "pi_allowed123", "amount": 2000,
                                            "currency": "usd", "status": "succeeded", "livemode": True}))))
    with pytest.raises(NotAuthorized):
        adapter.get_status("pi_allowed123")
