"""Stripe sandbox REST adapter. No SDK required; HTTPS GET only."""
import json
import os
from functools import lru_cache

import boto3
import httpx

from .contract import PaymentStatus, validate_payment_id
from .errors import ConfigurationError, NotAuthorized, PaymentNotFound, ProviderUnavailable

@lru_cache(maxsize=1)
def stripe_test_key():
    key = os.getenv("STRIPE_TEST_KEY")
    secret_arn = os.getenv("STRIPE_SECRET_ARN")
    if not key and secret_arn:
        try:
            secret = boto3.client("secretsmanager").get_secret_value(SecretId=secret_arn)["SecretString"]
            try:
                obj = json.loads(secret)
                key = obj.get("STRIPE_TEST_KEY") or obj.get("stripe_test_key")
            except json.JSONDecodeError:
                key = secret
        except Exception as exc:
            raise ConfigurationError("Unable to load Stripe sandbox key from Secrets Manager") from exc
    if not key or not key.startswith("sk_test_"):
        raise ConfigurationError("STRIPE_TEST_KEY must be a Stripe sandbox secret key (sk_test_...)")
    return key


class StripeReadAdapter:
    """Read-only provider. Never create, refund, or confirm a payment."""

    def __init__(self, client=None):
        self.client = client or httpx.Client(timeout=6.0)

    def get_status(self, payment_intent_id: str) -> PaymentStatus:
        payment_intent_id = validate_payment_id(payment_intent_id)
        headers = {"Authorization": f"Bearer {stripe_test_key()}"}
        try:
            response = self.client.get(
                f"https://api.stripe.com/v1/payment_intents/{payment_intent_id}",
                headers=headers,
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise ProviderUnavailable("Stripe could not be reached") from exc

        if response.status_code == 404:
            raise PaymentNotFound("PaymentIntent does not exist")
        if response.status_code in (401, 403):
            raise NotAuthorized("Stripe rejected the sandbox credentials or permissions")
        if response.status_code == 429 or response.status_code >= 500:
            raise ProviderUnavailable("Stripe API temporarily unavailable")
        if response.status_code >= 400:
            raise NotAuthorized("Stripe request was rejected; check the PaymentIntent ID and permissions")
        try:
            return PaymentStatus.from_stripe(response.json())
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderUnavailable("Invalid Stripe response") from exc
