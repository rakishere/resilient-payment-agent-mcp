import json
from app.contract import PaymentStatus
from app.mcp_protocol import handle_mcp, lambda_handler, PROTOCOL_VERSION
from app.mcp_client import McpAdapter


class FakeStripe:
    def get_status(self, payment_intent_id):
        return PaymentStatus(payment_intent_id, 2000, "usd", "succeeded", False)


def test_mcp_discovery_and_tool_call():
    status, body = handle_mcp({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert status == 200
    assert body["result"]["tools"][0]["name"] == "get_payment_status"
    status, body = handle_mcp({"jsonrpc": "2.0", "id": 2,
                               "method": "tools/call", "params": {
                                   "name": "get_payment_status", "arguments": {"payment_intent_id": "pi_allowed123"}}},
                              adapter=FakeStripe())
    assert body["result"]["structuredContent"]["status"] == "succeeded"


def test_mcp_http_version_check():
    response = lambda_handler({"httpMethod": "POST", "headers": {"MCP-Protocol-Version": "broken"},
                               "body": json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"})}, None)
    assert response["statusCode"] == 400


def test_real_mcp_client_messages_with_fake_http(monkeypatch):
    import httpx

    def handler(req):
        message = json.loads(req.content)
        status, obj = handle_mcp(message, adapter=FakeStripe())
        return httpx.Response(status, json=obj) if obj else httpx.Response(status)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    adapter = McpAdapter(url="http://127.0.0.1:8765/mcp", client=client)
    item = adapter.get_status("pi_allowed123")
    assert item.amount == 2000
    assert item.livemode is False
