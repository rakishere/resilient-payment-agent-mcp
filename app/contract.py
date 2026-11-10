"""Single contract shared by MCP and direct-API adapters."""
from dataclasses import asdict, dataclass
import os
import re

from .errors import InvalidPaymentId, NotAuthorized, ProviderUnavailable

_ID_PATTERN = re.compile(r"^pi_[a-zA-Z0-9]+$")

@dataclass(frozen=True)
class PaymentStatus:
    payment_intent_id: str
    amount: int
    currency: str
    status: str
    livemode: bool

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_stripe(cls, data: dict):
        if data.get("livemode") is not False:
            raise NotAuthorized("Only Stripe sandbox PaymentIntents are supported")
        return cls(
            payment_intent_id=str(data["id"]),
            amount=int(data["amount"]),
            currency=str(data["currency"]),
            status=str(data["status"]),
            livemode=False,
        )

    @classmethod
    def from_dict(cls, data: dict):
        try:
            return cls.from_stripe({
                "id": data["payment_intent_id"], "amount": data["amount"],
                "currency": data["currency"], "status": data["status"],
                "livemode": data["livemode"],
            })
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderUnavailable("Invalid payment status response") from exc


def validate_payment_id(payment_intent_id: str):
    if not isinstance(payment_intent_id, str) or not _ID_PATTERN.fullmatch(payment_intent_id):
        raise InvalidPaymentId("Expected a Stripe PaymentIntent ID (pi_...) with letters/digits")
    # Explicit allowlist is intentional for this learning project. Never accept arbitrary IDs.
    allowed = {v.strip() for v in os.getenv("ALLOWED_PAYMENT_INTENT_IDS", "").split(",") if v.strip()}
    if not allowed or payment_intent_id not in allowed:
        raise NotAuthorized("PaymentIntent is not authorized for this demo")
    return payment_intent_id
