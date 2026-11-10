"""AWS Lambda handler for the IAM-protected /chat endpoint."""
import json
import logging

from .agent import PaymentAgent
from .errors import PaymentError

logging.basicConfig(level=logging.INFO)
AGENT = PaymentAgent()  # warm Lambda execution environments reuse the breaker state


def lambda_handler(event, context):
    if event.get("httpMethod") != "POST":
        return _json(405, {"error": "POST required"})
    try:
        request = json.loads(event.get("body") or "{}")
        if not isinstance(request, dict) or not isinstance(request.get("payment_intent_id"), str):
            return _json(400, {"error": "payment_intent_id is required"})
        result = AGENT.answer(
            payment_intent_id=request["payment_intent_id"],
            question=request.get("message"),
            use_ai=bool(request.get("use_ai", True)),
        )
        return _json(200, result)
    except (ValueError, TypeError, json.JSONDecodeError):
        return _json(400, {"error": "Invalid JSON request"})
    except PaymentError as exc:
        logging.getLogger(__name__).warning("payment_error code=%s", exc.code)
        return _json(exc.http_status, {"error": exc.code, "message": str(exc)})


def _json(status, data):
    return {"statusCode": status,
            "headers": {"Content-Type": "application/json", "Cache-Control": "no-store"},
            "body": json.dumps(data)}
