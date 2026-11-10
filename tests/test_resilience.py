import pytest

from app.contract import PaymentStatus
from app.errors import McpUnavailable, NotAuthorized, ProviderUnavailable
from app.resilience import CircuitBreaker, PaymentRouter

PAYMENT = PaymentStatus("pi_allowed123", 2000, "usd", "requires_payment_method", False)


class FakeAdapter:
    def __init__(self, result=None, exception=None):
        self.result = result or PAYMENT
        self.exception = exception
        self.calls = 0

    def get_status(self, _id):
        self.calls += 1
        if self.exception:
            raise self.exception
        return self.result


def test_primary_when_healthy():
    mcp, direct = FakeAdapter(), FakeAdapter()
    router = PaymentRouter(mcp=mcp, direct=direct)
    assert router.get_status("pi_allowed123") == PAYMENT
    assert router.last_path == "mcp"
    assert (mcp.calls, direct.calls) == (1, 0)


def test_outage_falls_back_and_opens_breaker():
    mcp, direct = FakeAdapter(exception=McpUnavailable("server offline")), FakeAdapter()
    clock = [100]
    breaker = CircuitBreaker(threshold=2, reset_seconds=15, clock=lambda: clock[0])
    router = PaymentRouter(mcp=mcp, direct=direct, breaker=breaker)
    router.get_status("pi_allowed123")
    router.get_status("pi_allowed123")
    router.get_status("pi_allowed123")
    assert (mcp.calls, direct.calls) == (2, 3)
    clock[0] += 16
    mcp.exception = None
    router.get_status("pi_allowed123")
    assert router.last_path == "mcp"
    assert breaker.failures == 0


def test_auth_errors_never_fallback():
    mcp, direct = FakeAdapter(exception=NotAuthorized("no")), FakeAdapter()
    with pytest.raises(NotAuthorized):
        PaymentRouter(mcp=mcp, direct=direct).get_status("pi_allowed123")
    assert direct.calls == 0


def test_stripe_outage_never_fallback():
    mcp, direct = FakeAdapter(exception=ProviderUnavailable("Stripe down")), FakeAdapter()
    with pytest.raises(ProviderUnavailable):
        PaymentRouter(mcp=mcp, direct=direct).get_status("pi_allowed123")
    assert direct.calls == 0
