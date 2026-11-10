"""MCP client adapter with optional AWS API Gateway IAM SigV4 signing."""
import json
import os
from urllib.parse import urlparse

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
import httpx

from .contract import PaymentStatus, validate_payment_id
from .errors import (
    ConfigurationError, InvalidPaymentId, McpUnavailable,
    NotAuthorized, PaymentNotFound, ProviderUnavailable,
)
from .mcp_protocol import PROTOCOL_VERSION, TOOL_NAME

ERRORS = {
    "INVALID_PAYMENT_ID": InvalidPaymentId,
    "NOT_AUTHORIZED": NotAuthorized,
    "PAYMENT_NOT_FOUND": PaymentNotFound,
    "STRIPE_UNAVAILABLE": ProviderUnavailable,
    "CONFIGURATION_ERROR": ConfigurationError,
}


class McpAdapter:
    def __init__(self, url=None, client=None):
        self.url = url or os.getenv("MCP_URL", "http://127.0.0.1:8765/mcp")
        self.client = client or httpx.Client(timeout=4.0)
        self._initialized = False

    def _request(self, rpc: dict):
        body = json.dumps(rpc).encode("utf-8")
        headers = {
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
            "mcp-protocol-version": PROTOCOL_VERSION,
        }
        if os.getenv("MCP_AWS_IAM", "0") == "1":
            try:
                region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION", "us-east-1")
                credentials = boto3.Session().get_credentials()
                if credentials is None:
                    raise ConfigurationError("AWS credentials not available for MCP IAM signing")
                request = AWSRequest(method="POST", url=self.url, data=body, headers=headers)
                SigV4Auth(credentials.get_frozen_credentials(), "execute-api", region).add_auth(request)
                headers = dict(request.headers)
            except ConfigurationError:
                raise
            except Exception as exc:
                raise ConfigurationError("Could not sign MCP request") from exc
        try:
            http_resp = self.client.post(self.url, content=body, headers=headers)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise McpUnavailable("MCP endpoint cannot be reached") from exc
        if http_resp.status_code in (500, 502, 503, 504):
            raise McpUnavailable(f"MCP endpoint HTTP {http_resp.status_code}")
        if http_resp.status_code in (401, 403):
            raise NotAuthorized("MCP authorization denied: no fallback allowed")
        if http_resp.status_code >= 400:
            raise ConfigurationError(f"MCP HTTP {http_resp.status_code}: verify protocol and configuration")
        if http_resp.status_code == 202:
            return {}
        try:
            payload = http_resp.json()
        except (ValueError, TypeError) as exc:
            raise McpUnavailable("MCP returned malformed JSON") from exc
        if payload.get("error"):
            raise ConfigurationError("MCP JSON-RPC error: " + str(payload["error"].get("message")))
        return payload.get("result", {})

    def _initialize(self):
        if self._initialized:
            return
        result = self._request({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": PROTOCOL_VERSION,
                       "capabilities": {}, "clientInfo": {"name": "stripe-agent", "version": "0.1.0"}},
        })
        if result.get("protocolVersion") != PROTOCOL_VERSION:
            raise ConfigurationError("MCP protocol version negotiation failed")
        self._request({"jsonrpc": "2.0", "method": "notifications/initialized"})
        tools = self._request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).get("tools", [])
        if not any(item.get("name") == TOOL_NAME for item in tools):
            raise ConfigurationError("Required MCP tool is not exposed")
        self._initialized = True

    def get_status(self, payment_intent_id: str) -> PaymentStatus:
        validate_payment_id(payment_intent_id)
        self._initialize()
        result = self._request({
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": TOOL_NAME, "arguments": {"payment_intent_id": payment_intent_id}},
        })
        if result.get("isError"):
            error = result.get("structuredContent") or {}
            code = error.get("error_code")
            error_cls = ERRORS.get(code, ConfigurationError)
            raise error_cls(error.get("message", "MCP tool failed"))
        data = result.get("structuredContent")
        if not isinstance(data, dict):
            raise McpUnavailable("MCP tool response missing structuredContent")
        item = PaymentStatus.from_dict(data)
        if item.payment_intent_id != payment_intent_id:
            raise McpUnavailable("MCP returned the wrong PaymentIntent")
        return item
