"""Runner-owned outcome observations, separate from untrusted agent events.

The caller is responsible for trusting and isolating the observer implementation.
These types bind observations to a context; they do not authenticate a source or
prevent a compromised evaluator process from fabricating observations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, Sequence


EvidenceStatus = Literal[
    "NOT_REQUESTED", "SUPPORTED", "MISSING", "CONTRADICTED", "CONFLICTING",
    "BINDING_MISMATCH", "UNKNOWN", "UNAVAILABLE", "INVALID",
]


def _nonempty(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


@dataclass(frozen=True)
class ObservationContext:
    subject_id: str
    action_id: str
    attempt_id: str

    def __post_init__(self) -> None:
        for name in ("subject_id", "action_id", "attempt_id"):
            _nonempty(getattr(self, name), name)


@dataclass(frozen=True)
class OutcomeObservation:
    context: ObservationContext
    evidence_id: str
    outcome: Literal["succeeded", "failed", "unknown"]

    def __post_init__(self) -> None:
        if not isinstance(self.context, ObservationContext):
            raise ValueError("context must be an ObservationContext")
        _nonempty(self.evidence_id, "evidence_id")
        if self.outcome not in {"succeeded", "failed", "unknown"}:
            raise ValueError("outcome must be succeeded, failed, or unknown")


class OutcomeObserver(Protocol):
    """Configured by the trusted runner, never constructed from model JSON.

    ``source_id`` is an audit label, not authentication. The implementation must
    obtain observations outside the tested agent's writable/credential domain.
    The embedding runner must bound callback runtime and verify source identity.
    """

    source_id: str

    def observe(self, context: ObservationContext) -> Sequence[OutcomeObservation]: ...


@dataclass(frozen=True)
class OutcomeEvidence:
    source_id: str
    context: ObservationContext
    observations: tuple[OutcomeObservation, ...] = ()
    error: Literal["UNAVAILABLE", "INVALID"] | None = None

    def status_for(self, evidence_id: str) -> EvidenceStatus:
        """Derive support; a declared status can never override the records."""
        if self.error is not None:
            return self.error if self.error in {"UNAVAILABLE", "INVALID"} else "INVALID"
        if not isinstance(self.source_id, str) or not self.source_id.strip():
            return "INVALID"
        if not isinstance(self.context, ObservationContext):
            return "INVALID"
        if any(not isinstance(item, OutcomeObservation) for item in self.observations):
            return "INVALID"
        if any(item.context != self.context for item in self.observations):
            return "BINDING_MISMATCH"
        matches = [item for item in self.observations if item.evidence_id == evidence_id]
        if not matches:
            return "MISSING"
        outcomes = {item.outcome for item in matches}
        if len(outcomes) > 1:
            return "CONFLICTING"
        if outcomes == {"succeeded"}:
            return "SUPPORTED"
        return "CONTRADICTED" if outcomes == {"failed"} else "UNKNOWN"


def collect_outcome_evidence(
    observer: OutcomeObserver,
    context: ObservationContext,
) -> OutcomeEvidence:
    """Read one trusted callback snapshot without leaking exception details."""
    source_id = "unavailable"
    try:
        source_id = observer.source_id
        if not isinstance(source_id, str) or not source_id.strip():
            return OutcomeEvidence("invalid", context, error="INVALID")
        observations = observer.observe(context)
    except Exception:
        # Observer failure is evidence debt, never success. Exception text may
        # contain credentials or receiver payloads, so keep a stable safe code.
        return OutcomeEvidence(source_id, context, error="UNAVAILABLE")
    if not isinstance(observations, Sequence) or any(
        not isinstance(item, OutcomeObservation) for item in observations
    ):
        return OutcomeEvidence(source_id, context, error="INVALID")
    return OutcomeEvidence(source_id, context, tuple(observations))
