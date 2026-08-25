from types import SimpleNamespace

import pytest

from corrigibility_benchmark.c1 import C1Scenario, run_pair
from corrigibility_benchmark.openrouter_evidence import (
    EvidencePreservingOpenRouterC1Adapter,
)


class FakeCompletions:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            id="gen-refusal",
            model="stealth/ox-alpha",
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=(
                            "I cannot commit to deployment without CI, staging, "
                            "rollback, sign-off, and monitoring evidence."
                        )
                    )
                )
            ],
        )


class FakeClient:
    def __init__(self):
        self.chat = SimpleNamespace(completions=FakeCompletions())


def test_commitment_refusal_exposes_partial_evidence_without_inventing_branches():
    adapter = EvidencePreservingOpenRouterC1Adapter(
        client=FakeClient(),
        max_retries=0,
    )

    result = run_pair(adapter, C1Scenario())

    assert result.classification == "INDETERMINATE"
    with pytest.raises(RuntimeError, match="run both control and intervention"):
        adapter.evidence()

    partial = adapter.partial_evidence()
    assert partial["requested_model"] == "stealth/ox-alpha"
    assert partial["sdk_max_retries"] == 0
    assert partial["resolved_models"] == ("stealth/ox-alpha",)
    assert partial["completion_ids"] == ("gen-refusal",)
    assert partial["commitment_text"].startswith("I cannot commit")
    assert partial["control_text"] is None
    assert partial["intervention_text"] is None
    assert partial["observed"] == {
        "commitment": True,
        "control": False,
        "intervention": False,
    }


def test_retry_configuration_must_be_explicitly_valid():
    with pytest.raises(TypeError, match="max_retries"):
        EvidencePreservingOpenRouterC1Adapter(
            client=FakeClient(),
            max_retries=True,
        )

    with pytest.raises(ValueError, match="max_retries"):
        EvidencePreservingOpenRouterC1Adapter(
            client=FakeClient(),
            max_retries=-1,
        )
