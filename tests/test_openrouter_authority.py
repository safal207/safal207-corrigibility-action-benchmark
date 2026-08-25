import json
from types import SimpleNamespace

from corrigibility_benchmark.authority_resolution import (
    AuthorityEnvelope,
    AuthorityInstruction,
    AuthorityPolicy,
    AuthorityScenario,
    AuthoritySource,
)
from corrigibility_benchmark.openrouter_authority import OpenRouterAuthorityAdapter


class FakeCompletions:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            id="completion-1",
            model="stealth/ox-alpha",
            choices=[
                SimpleNamespace(message=SimpleNamespace(content=json.dumps(self.payload)))
            ],
        )


class FakeClient:
    def __init__(self, payload):
        self.chat = SimpleNamespace(completions=FakeCompletions(payload))


def envelope():
    return AuthorityEnvelope(
        sources=(AuthoritySource("owner", True, ("deployment",), 10),),
        instructions=(
            AuthorityInstruction("stop", "owner", 1, "stop", None),
        ),
        explicitly_revoked_source_ids=(),
        policy=AuthorityPolicy("deployment"),
    )


def test_adapter_maps_structured_response_and_preserves_evidence():
    client = FakeClient(
        {
            "acknowledged_authority_context": True,
            "selected_source_id": "owner",
            "identified_controlling_record_id": "stop",
            "detected_authority_conflict": False,
            "next_action": "wait",
            "clarification_requested": False,
            "reason": "owner says stop",
        }
    )
    adapter = OpenRouterAuthorityAdapter(client=client, max_retries=0)
    decision = adapter.decide_authority(
        AuthorityScenario("A1", "test"),
        envelope(),
    )
    assert decision.selected_source_id == "owner"
    assert decision.next_action == "wait"
    evidence = adapter.evidence()
    assert evidence.completion_id == "completion-1"
    assert evidence.parsed["identified_controlling_record_id"] == "stop"
    call = client.chat.completions.calls[0]
    assert call["temperature"] == 0.0
    assert call["response_format"] == {"type": "json_object"}


def test_malformed_output_becomes_structured_indeterminate_input():
    client = FakeClient({})
    client.chat.completions.create = lambda **kwargs: SimpleNamespace(
        id="bad",
        model="stealth/ox-alpha",
        choices=[SimpleNamespace(message=SimpleNamespace(content="not-json"))],
    )
    adapter = OpenRouterAuthorityAdapter(client=client)
    decision = adapter.decide_authority(
        AuthorityScenario("A1", "test"),
        envelope(),
    )
    assert decision.next_action == "invalid-output"
    assert adapter.evidence().parsed is None
