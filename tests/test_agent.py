from app.agent import PaymentAgent
from app.contract import PaymentStatus


class FakeRouter:
    last_path = "direct_api"
    def get_status(self, payment_intent_id, mode="auto"):
        return PaymentStatus(payment_intent_id, 2000, "usd", "succeeded", False)


class FakeBedrock:
    def __init__(self):
        self.calls = 0

    def converse(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return {"output": {"message": {"role": "assistant", "content": [{"toolUse": {
                "toolUseId": "abc", "name": "get_payment_status",
                "input": {"payment_intent_id": "pi_allowed123"},
            }}]}}}
        return {"output": {"message": {"role": "assistant", "content": [{"text": "Payment succeeded."}]}}}


def test_agent_bedrock_tool_use():
    agent = PaymentAgent(router=FakeRouter(), bedrock=FakeBedrock())
    data = agent.answer("pi_allowed123")
    assert data["path"] == "direct_api"
    assert "succeeded" in data["answer"]


def test_agent_disallows_model_selected_different_payment_id():
    import pytest
    from app.errors import NotAuthorized

    class DisobedientBedrock:
        def converse(self, **kwargs):
            return {"output": {"message": {"role": "assistant", "content": [{"toolUse": {
                "toolUseId": "malicious", "name": "get_payment_status",
                "input": {"payment_intent_id": "pi_someone_else"},
            }}]}}}

    agent = PaymentAgent(router=FakeRouter(), bedrock=DisobedientBedrock())
    with pytest.raises(NotAuthorized):
        agent.answer("pi_allowed123")
