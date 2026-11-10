"""Local CLI. Use --no-ai first; Bedrock is optional until the final stage."""
import argparse
import json
import sys

from .agent import PaymentAgent
from .errors import PaymentError


def main():
    parser = argparse.ArgumentParser(description="Stripe sandbox payment-status AI agent")
    parser.add_argument("payment_intent_id", help="A test pi_... value already allowlisted")
    parser.add_argument("--question", default=None)
    parser.add_argument("--no-ai", action="store_true", help="Test routing without calling Bedrock")
    parser.add_argument("--mode", choices=["auto", "mcp", "direct"], default="auto")
    args = parser.parse_args()
    try:
        output = PaymentAgent().answer(args.payment_intent_id, args.question,
                                       use_ai=not args.no_ai, mode=args.mode)
    except PaymentError as exc:
        print(json.dumps({"error": exc.code, "message": str(exc)}, indent=2))
        return 1
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
