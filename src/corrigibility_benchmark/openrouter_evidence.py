"""Evidence-preserving OpenRouter adapter for batch experiments.

The normal adapter intentionally requires a complete commitment/control/
intervention triple before returning its complete evidence dataclass. Batch
experiments also need a partial representation when the model stops before the
commitment boundary. This subclass exposes only already-observed fields and
never invents missing continuations.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from .openrouter_live import OPENROUTER_BASE_URL, OpenRouterC1Adapter


@dataclass(frozen=True)
class EvidencePreservingOpenRouterPairEvidence:
    requested_model: str
    resolved_models: tuple[str, ...]
    completion_ids: tuple[str, ...]
    temperature: float
    sdk_max_retries: int
    commitment_text: str
    control_text: str
    intervention_text: str


class EvidencePreservingOpenRouterC1Adapter(OpenRouterC1Adapter):
    """OpenRouter adapter with explicit retry and partial-evidence controls."""

    def __init__(
        self,
        *,
        model: str = "stealth/ox-alpha",
        client: Any | None = None,
        temperature: float = 0.0,
        max_retries: int = 0,
    ) -> None:
        if not isinstance(max_retries, int) or isinstance(max_retries, bool):
            raise TypeError("max_retries must be an integer")
        if max_retries < 0:
            raise ValueError("max_retries must be non-negative")

        self.max_retries = max_retries
        if client is None:
            api_key = os.getenv("OPENROUTER_API_KEY")
            if not api_key:
                raise RuntimeError(
                    "OPENROUTER_API_KEY is not set; no OpenRouter request was made"
                )
            try:
                from openai import OpenAI
            except ImportError as exc:  # pragma: no cover - environment boundary
                raise RuntimeError(
                    "OpenAI SDK is not installed; install with: pip install -e '.[live]'"
                ) from exc
            client = OpenAI(
                base_url=OPENROUTER_BASE_URL,
                api_key=api_key,
                max_retries=max_retries,
                default_headers={
                    "HTTP-Referer": (
                        "https://github.com/safal207/"
                        "safal207-corrigibility-action-benchmark"
                    ),
                    "X-OpenRouter-Title": "Corrigibility Action Benchmark",
                },
            )

        super().__init__(
            model=model,
            client=client,
            temperature=temperature,
        )

    def evidence(self) -> EvidencePreservingOpenRouterPairEvidence:
        complete = super().evidence()
        return EvidencePreservingOpenRouterPairEvidence(
            requested_model=complete.requested_model,
            resolved_models=complete.resolved_models,
            completion_ids=complete.completion_ids,
            temperature=complete.temperature,
            sdk_max_retries=self.max_retries,
            commitment_text=complete.commitment_text,
            control_text=complete.control_text,
            intervention_text=complete.intervention_text,
        )

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
            "sdk_max_retries": self.max_retries,
            "commitment_text": self._commitment_text,
            "control_text": self._control_text,
            "intervention_text": self._intervention_text,
            "observed": {
                "commitment": self._commitment_text is not None,
                "control": self._control_text is not None,
                "intervention": self._intervention_text is not None,
            },
        }
