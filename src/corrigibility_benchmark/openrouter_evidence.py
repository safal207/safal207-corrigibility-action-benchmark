"""Evidence-preserving OpenRouter adapter for batch experiments.

The normal adapter intentionally requires a complete commitment/control/
intervention triple before returning its complete evidence dataclass. Batch
experiments also need a partial representation when the model stops before the
commitment boundary. This subclass exposes only already-observed fields and
never invents missing continuations.
"""

from __future__ import annotations

from typing import Any

from .openrouter_live import OpenRouterC1Adapter


class EvidencePreservingOpenRouterC1Adapter(OpenRouterC1Adapter):
    """OpenRouter adapter with an explicit partial-evidence export path."""

    def partial_evidence(self) -> dict[str, Any]:
        resolved_models = tuple(
            value
            for value in (
                self._commitment_model,
                self._control_model,
                self._intervention_model,
            )
            if value is not None
        )
        completion_ids = tuple(
            value
            for value in (
                self._commitment_id,
                self._control_id,
                self._intervention_id,
            )
            if value is not None
        )
        return {
            "requested_model": self.model,
            "resolved_models": resolved_models,
            "completion_ids": completion_ids,
            "temperature": self.temperature,
            "commitment_text": self._commitment_text,
            "control_text": self._control_text,
            "intervention_text": self._intervention_text,
            "observed": {
                "commitment": self._commitment_text is not None,
                "control": self._control_text is not None,
                "intervention": self._intervention_text is not None,
            },
        }
