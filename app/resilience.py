"""Circuit breaker + Strategy selection. Only MCP transport outages trigger failover."""
import logging
import time

from .errors import McpUnavailable
from .mcp_client import McpAdapter
from .stripe_api import StripeReadAdapter

log = logging.getLogger(__name__)


class CircuitBreaker:
    """In-memory breaker per process. For learning, NOT shared across Lambda instances."""

    def __init__(self, threshold=2, reset_seconds=15, clock=None):
        self.threshold = threshold
        self.reset_seconds = reset_seconds
        self.clock = clock or time.monotonic
        self.failures = 0
        self.opened_at = None

    def can_attempt(self):
        return self.opened_at is None or self.clock() - self.opened_at >= self.reset_seconds

    def success(self):
        self.failures = 0
        self.opened_at = None

    def fail(self):
        self.failures += 1
        if self.failures >= self.threshold:
            self.opened_at = self.clock()


class PaymentRouter:
    def __init__(self, mcp=None, direct=None, breaker=None):
        self.mcp = mcp or McpAdapter()
        self.direct = direct or StripeReadAdapter()
        self.breaker = breaker or CircuitBreaker()
        self.last_path = None

    def get_status(self, payment_intent_id, mode="auto"):
        if mode == "direct":
            self.last_path = "direct_api"
            return self.direct.get_status(payment_intent_id)
        if mode == "mcp":
            result = self.mcp.get_status(payment_intent_id)
            self.last_path = "mcp"
            return result
        if mode != "auto":
            raise ValueError("mode must be auto, mcp or direct")
        if self.breaker.can_attempt():
            try:
                result = self.mcp.get_status(payment_intent_id)
                self.breaker.success()
                self.last_path = "mcp"
                log.info("payment_status path=mcp")
                return result
            except McpUnavailable as exc:
                self.breaker.fail()
                log.warning("mcp_transport_unavailable falling_back=true reason=%s", str(exc))
        self.last_path = "direct_api"
        log.info("payment_status path=direct_api")
        return self.direct.get_status(payment_intent_id)
