"""Bedrock Converse tool use; application (not model) owns routing and authorization."""
import os

import boto3

from .contract import validate_payment_id
from .errors import ConfigurationError, NotAuthorized, PaymentError
from .mcp_protocol import TOOL_NAME, TOOL_SPEC
from .resilience import PaymentRouter


def plain_answer(item):
    return (f"Sandbox payment {item.payment_intent_id}: {item.status}; "
            f"amount {item.amount / 100:.2f} {item.currency.upper()}.")


class PaymentAgent:
    def __init__(self, router=None, bedrock=None):
        self.router = router or PaymentRouter()
        self.bedrock = bedrock

    def answer(self, payment_intent_id, question=None, use_ai=True, mode="auto"):
        # Validated before any LLM call; caller cannot request another user's record.
        validate_payment_id(payment_intent_id)
        if not use_ai:
            payment = self.router.get_status(payment_intent_id, mode=mode)
            return {"answer": plain_answer(payment), "payment": payment.to_dict(), "path": self.router.last_path}

        model_id = os.getenv("BEDROCK_MODEL_ID", "amazon.nova-lite-v1:0")
        bedrock = self.bedrock or boto3.client("bedrock-runtime")
        user_text = question or f"What is the status of sandbox payment {payment_intent_id}?"
        messages = [{"role": "user", "content": [{"text": user_text + f"\nAuthorized PaymentIntent: {payment_intent_id}"}]}]
        tools = [{"toolSpec": {
            "name": TOOL_NAME,
            "description": TOOL_SPEC["description"],
            "inputSchema": {"json": {
                "type": "object",
                "properties": TOOL_SPEC["inputSchema"]["properties"],
                "required": TOOL_SPEC["inputSchema"]["required"],
            }},
        }}]
        try:
            first = bedrock.converse(
                modelId=model_id,
                system=[{"text": "You are a payment-status assistant. Always use the authorized tool; never invent payment information. Only answer about the provided sandbox PaymentIntent."}],
                messages=messages,
                toolConfig={"tools": tools, "toolChoice": {"tool": {"name": TOOL_NAME}}},
                inferenceConfig={"maxTokens": 400, "temperature": 0},
            )
            tool_calls = [c["toolUse"] for c in first["output"]["message"]["content"] if "toolUse" in c]
            if len(tool_calls) != 1 or tool_calls[0].get("name") != TOOL_NAME:
                raise ConfigurationError("Model did not request exactly one payment-status tool call")
            tool = tool_calls[0]
            if tool.get("input", {}).get("payment_intent_id") != payment_intent_id:
                raise NotAuthorized("Model tried to request a different PaymentIntent")
            payment = self.router.get_status(payment_intent_id, mode=mode)
            messages.append(first["output"]["message"])
            messages.append({"role": "user", "content": [{"toolResult": {
                "toolUseId": tool["toolUseId"],
                "content": [{"json": payment.to_dict()}],
                "status": "success",
            }}]})
            second = bedrock.converse(
                modelId=model_id,
                system=[{"text": "Respond concisely using only the payment data returned by the tool. No guesses."}],
                messages=messages,
                inferenceConfig={"maxTokens": 250, "temperature": 0},
            )
            lines = [c["text"] for c in second["output"]["message"]["content"] if "text" in c]
            answer = "\n".join(lines) or plain_answer(payment)
            return {"answer": answer, "payment": payment.to_dict(), "path": self.router.last_path}
        except PaymentError:
            raise
        except Exception as exc:
            raise ConfigurationError("Bedrock request failed; check model access, IAM permissions, and AWS Region") from exc
