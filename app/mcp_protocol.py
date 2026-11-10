"""Small educational MCP 2025-06-18 Streamable HTTP JSON-RPC subset.

This implements initialize, initialized notification, tools/list, tools/call
using stateless JSON responses. It intentionally does NOT implement the full
MCP SDK feature set, SSE streaming, OAuth discovery, resources, or prompts.
AWS IAM protects the API Gateway endpoint; localhost binds to loopback only.
"""
import json
import os

from .errors import PaymentError
from .stripe_api import StripeReadAdapter

PROTOCOL_VERSION = "2025-06-18"
TOOL_NAME = "get_payment_status"
TOOL_SPEC = {
    "name": TOOL_NAME,
    "description": "Read the status of one explicitly authorized Stripe sandbox PaymentIntent. Never changes payments.",
    "inputSchema": {
        "type": "object",
        "properties": {"payment_intent_id": {"type": "string", "description": "Stripe pi_... identifier"}},
        "required": ["payment_intent_id"],
        "additionalProperties": False,
    },
}


def response(status: int, obj=None):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json", "Cache-Control": "no-store"},
        "body": "" if obj is None else json.dumps(obj),
    }


def rpc_result(request_id, result):
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def rpc_error(request_id, code, message):
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def handle_mcp(request: dict, *, adapter=None):
    """Return (HTTP status, body), independent of Lambda transport."""
    if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
        return 400, rpc_error(None, -32600, "Invalid JSON-RPC request")
    method, request_id = request.get("method"), request.get("id")
    if method == "notifications/initialized" and "id" not in request:
        return 202, None
    if request_id is None:
        return 400, rpc_error(None, -32600, "Request id required")
    if method == "initialize":
        return 200, rpc_result(request_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "resilient-stripe-sandbox", "version": "0.1.0"},
        })
    if method == "tools/list":
        return 200, rpc_result(request_id, {"tools": [TOOL_SPEC]})
    if method == "tools/call":
        params = request.get("params") or {}
        if not isinstance(params, dict) or params.get("name") != TOOL_NAME:
            return 200, rpc_error(request_id, -32602, "Unknown tool")
        args = params.get("arguments") or {}
        if not isinstance(args, dict) or set(args) != {"payment_intent_id"}:
            return 200, rpc_error(request_id, -32602, "Requires payment_intent_id")
        try:
            item = (adapter or StripeReadAdapter()).get_status(args["payment_intent_id"])
        except PaymentError as exc:
            return 200, rpc_result(request_id, {
                "isError": True,
                "content": [{"type": "text", "text": exc.code}],
                "structuredContent": {"error_code": exc.code, "message": str(exc)},
            })
        return 200, rpc_result(request_id, {
            "isError": False,
            "content": [{"type": "text", "text": json.dumps(item.to_dict())}],
            "structuredContent": item.to_dict(),
        })
    return 200, rpc_error(request_id, -32601, "Method not found")


def lambda_handler(event, context):
    if os.getenv("SIMULATE_MCP_OUTAGE") == "1":
        return response(503, {"error": "Simulated MCP outage"})
    if event.get("httpMethod") != "POST":
        return response(405, {"error": "POST required"})
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    origin = headers.get("origin")
    if origin and origin not in {"http://127.0.0.1:8765", "http://localhost:8765"}:
        return response(403, {"error": "Origin not allowed"})
    version = headers.get("mcp-protocol-version")
    if version and version != PROTOCOL_VERSION:
        return response(400, rpc_error(None, -32600, "Unsupported MCP protocol version"))
    try:
        request = json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, ValueError):
        return response(400, rpc_error(None, -32700, "Invalid JSON"))
    status, obj = handle_mcp(request)
    return response(status, obj)
