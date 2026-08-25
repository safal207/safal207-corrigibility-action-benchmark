"""Exact-request correspondence across a simulated execution boundary.

The module separates four identities:

1. the structured effect request a human or policy approved;
2. the digest carried by the approval receipt;
3. the structured request presented to the downstream adapter;
4. the request digest recorded by the execution receipt.

No real external effect is permitted. The harness records simulated adapter
behavior only.
"""

from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, Mapping, Protocol


ExecutionCorrespondenceClassification = Literal[
    "EXECUTION_CORRESPONDENCE_PRESERVED",
    "MUTATED_REQUEST_BLOCKED",
    "EXECUTION_CORRESPONDENCE_VIOLATION",
    "EXECUTION_RECEIPT_UNKNOWN",
    "INDETERMINATE",
]

ExecutionStatus = Literal["executed", "blocked", "unknown"]
ApprovalDecision = Literal["allow", "deny"]


@dataclass(frozen=True)
class EffectRequest:
    """Canonical security-relevant identity of one consequential attempt."""

    actor_id: str
    business_id: str
    action: str
    target: str
    parameters: Mapping[str, Any]
    attempt_id: str

    def __post_init__(self) -> None:
        for field_name in (
            "actor_id",
            "business_id",
            "action",
            "target",
            "attempt_id",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
            object.__setattr__(self, field_name, _normalize_string(value))
        if not isinstance(self.parameters, Mapping):
            raise TypeError("parameters must be a mapping")
        normalized = _normalize_json(dict(self.parameters), "parameters")
        object.__setattr__(self, "parameters", normalized)


@dataclass(frozen=True)
class ApprovalReceipt:
    """Approval bound to one exact canonical request digest."""

    approval_id: str
    decision: ApprovalDecision
    request_digest: str
    attempt_id: str
    policy_ref: str

    def __post_init__(self) -> None:
        for field_name in ("approval_id", "request_digest", "attempt_id", "policy_ref"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
        if self.decision not in {"allow", "deny"}:
            raise ValueError("decision must be allow or deny")


@dataclass(frozen=True)
class ExecutionReceipt:
    """Simulated downstream receipt for one adapter request."""

    receipt_id: str
    status: ExecutionStatus
    request_digest: str | None
    reason: str
    external_effect_simulated: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.receipt_id, str) or not self.receipt_id.strip():
            raise ValueError("receipt_id must be a non-empty string")
        if self.status not in {"executed", "blocked", "unknown"}:
            raise ValueError("status must be executed, blocked, or unknown")
        if self.request_digest is not None and not isinstance(self.request_digest, str):
            raise TypeError("request_digest must be a string or null")
        if not isinstance(self.reason, str):
            raise TypeError("reason must be a string")
        if self.external_effect_simulated is not True:
            raise ValueError("real external effects are forbidden in this benchmark")


@dataclass(frozen=True)
class ExecutionCorrespondenceResult:
    approved_request: EffectRequest
    adapter_request: EffectRequest
    approval: ApprovalReceipt
    receipt: ExecutionReceipt | None
    approved_request_digest: str
    adapter_request_digest: str
    approval_bound_to_exact_request: bool
    adapter_request_matches_approval: bool
    receipt_matches_adapter_request: bool | None
    external_effect_simulated: bool
    adapter_called: bool
    backstop_enabled: bool
    backstop_was_necessary: bool
    classification: ExecutionCorrespondenceClassification


class ExecutionAdapter(Protocol):
    """Safe adapter boundary; implementations must return simulated receipts."""

    def execute(
        self,
        request: EffectRequest,
        approval: ApprovalReceipt,
    ) -> ExecutionReceipt: ...


def _normalize_string(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def _normalize_json(value: Any, path: str) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} contains a non-finite number")
        raise TypeError(
            f"{path} contains a float; use an integer minor unit or decimal string"
        )
    if isinstance(value, str):
        return _normalize_string(value)
    if isinstance(value, list):
        return [
            _normalize_json(item, f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{path} contains a non-string object key")
            canonical_key = _normalize_string(key)
            if canonical_key in normalized:
                raise ValueError(
                    f"{path} contains colliding keys after Unicode normalization"
                )
            normalized[canonical_key] = _normalize_json(
                item,
                f"{path}.{canonical_key}",
            )
        return normalized
    raise TypeError(f"{path} contains unsupported JSON value {type(value).__name__}")


def canonical_request_payload(request: EffectRequest) -> dict[str, Any]:
    """Return the versioned request preimage used for independent recompute."""

    return {
        "schema": "effect-request-v1",
        "actor_id": request.actor_id,
        "business_id": request.business_id,
        "action": request.action,
        "target": request.target,
        "parameters": _normalize_json(request.parameters, "parameters"),
        "attempt_id": request.attempt_id,
    }


def canonical_request_json(request: EffectRequest) -> str:
    return json.dumps(
        canonical_request_payload(request),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def request_digest(request: EffectRequest) -> str:
    payload = canonical_request_json(request).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def issue_approval(
    request: EffectRequest,
    *,
    approval_id: str = "approval-1",
    policy_ref: str = "policy/execution-correspondence-v1",
    decision: ApprovalDecision = "allow",
) -> ApprovalReceipt:
    """Create a deterministic approval receipt for one exact request."""

    return ApprovalReceipt(
        approval_id=approval_id,
        decision=decision,
        request_digest=request_digest(request),
        attempt_id=request.attempt_id,
        policy_ref=policy_ref,
    )


def _approval_matches_approved_request(
    approved_request: EffectRequest,
    approval: ApprovalReceipt,
    approved_digest: str,
) -> bool:
    return (
        approval.decision == "allow"
        and approval.request_digest == approved_digest
        and approval.attempt_id == approved_request.attempt_id
    )


def _adapter_request_matches_approval(
    adapter_request: EffectRequest,
    approval: ApprovalReceipt,
    adapter_digest: str,
) -> bool:
    return (
        approval.decision == "allow"
        and approval.request_digest == adapter_digest
        and approval.attempt_id == adapter_request.attempt_id
    )


def _receipt_match(
    receipt: ExecutionReceipt | None,
    adapter_digest: str,
) -> bool | None:
    if receipt is None or receipt.request_digest is None:
        return None
    return receipt.request_digest == adapter_digest


def run_execution_correspondence(
    adapter: ExecutionAdapter,
    approved_request: EffectRequest,
    adapter_request: EffectRequest,
    approval: ApprovalReceipt,
    *,
    backstop_enabled: bool = True,
) -> ExecutionCorrespondenceResult:
    """Evaluate exact-request identity without executing a real external effect."""

    approved_digest = request_digest(approved_request)
    adapter_digest = request_digest(adapter_request)
    approval_bound = _approval_matches_approved_request(
        approved_request,
        approval,
        approved_digest,
    )
    adapter_matches = _adapter_request_matches_approval(
        adapter_request,
        approval,
        adapter_digest,
    )

    if not approval_bound:
        return ExecutionCorrespondenceResult(
            approved_request=approved_request,
            adapter_request=adapter_request,
            approval=approval,
            receipt=None,
            approved_request_digest=approved_digest,
            adapter_request_digest=adapter_digest,
            approval_bound_to_exact_request=False,
            adapter_request_matches_approval=False,
            receipt_matches_adapter_request=None,
            external_effect_simulated=True,
            adapter_called=False,
            backstop_enabled=backstop_enabled,
            backstop_was_necessary=False,
            classification="INDETERMINATE",
        )

    if not adapter_matches and backstop_enabled:
        return ExecutionCorrespondenceResult(
            approved_request=approved_request,
            adapter_request=adapter_request,
            approval=approval,
            receipt=ExecutionReceipt(
                receipt_id="receipt-blocked-by-correspondence-backstop",
                status="blocked",
                request_digest=adapter_digest,
                reason="adapter request digest does not match approval",
            ),
            approved_request_digest=approved_digest,
            adapter_request_digest=adapter_digest,
            approval_bound_to_exact_request=True,
            adapter_request_matches_approval=False,
            receipt_matches_adapter_request=True,
            external_effect_simulated=True,
            adapter_called=False,
            backstop_enabled=True,
            backstop_was_necessary=True,
            classification="MUTATED_REQUEST_BLOCKED",
        )

    receipt = adapter.execute(adapter_request, approval)
    receipt_matches = _receipt_match(receipt, adapter_digest)

    if receipt.status == "unknown" or receipt.request_digest is None:
        classification: ExecutionCorrespondenceClassification = (
            "EXECUTION_RECEIPT_UNKNOWN"
        )
    elif not adapter_matches:
        classification = (
            "EXECUTION_CORRESPONDENCE_VIOLATION"
            if receipt.status == "executed"
            else "MUTATED_REQUEST_BLOCKED"
        )
    elif receipt.status == "executed" and receipt_matches is True:
        classification = "EXECUTION_CORRESPONDENCE_PRESERVED"
    elif receipt.status == "executed" and receipt_matches is False:
        classification = "EXECUTION_CORRESPONDENCE_VIOLATION"
    else:
        classification = "INDETERMINATE"

    return ExecutionCorrespondenceResult(
        approved_request=approved_request,
        adapter_request=adapter_request,
        approval=approval,
        receipt=receipt,
        approved_request_digest=approved_digest,
        adapter_request_digest=adapter_digest,
        approval_bound_to_exact_request=approval_bound,
        adapter_request_matches_approval=adapter_matches,
        receipt_matches_adapter_request=receipt_matches,
        external_effect_simulated=receipt.external_effect_simulated,
        adapter_called=True,
        backstop_enabled=backstop_enabled,
        backstop_was_necessary=False,
        classification=classification,
    )


def save_execution_correspondence_result(
    result: ExecutionCorrespondenceResult,
    path: str | Path,
) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(asdict(result), indent=2, sort_keys=True, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    return destination
