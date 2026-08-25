"""Batch orchestration for preregistered recovery-transition experiments."""

from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from .recovery import (
    IntentRecord,
    RecoveryCheckpoint,
    RecoveryEnvelope,
    RecoveryResult,
    RecoveryScenario,
    run_recovery,
    save_recovery_result,
    validate_recovery_envelope,
)


AdapterFactory = Callable[[str, float, int], Any]


@dataclass(frozen=True)
class RecoveryArm:
    arm_id: str
    title: str
    scenario: RecoveryScenario
    envelope: RecoveryEnvelope
    backstop_enabled: bool


@dataclass(frozen=True)
class RecoveryBatchRecord:
    arm_id: str
    title: str
    classification: str
    result_path: str | None
    evidence_path: str | None
    error_path: str | None


@dataclass(frozen=True)
class RecoveryBatchSummary:
    batch_id: str
    requested_model: str
    temperature: float
    sdk_max_retries: int
    inter_arm_delay_seconds: float
    total_arms: int
    counts: dict[str, int]
    counterexample_arms: tuple[str, ...]
    indeterminate_arms: tuple[str, ...]
    records: tuple[RecoveryBatchRecord, ...]


def _require_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _require_bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean")
    return value


def _intent_record(raw: Mapping[str, Any], field: str) -> IntentRecord:
    revoked = raw.get("revoked_action_ids", [])
    if not isinstance(revoked, list) or not all(
        isinstance(item, str) and item.strip() for item in revoked
    ):
        raise ValueError(f"{field}.revoked_action_ids must be a string list")
    sequence = raw.get("sequence")
    if not isinstance(sequence, int) or isinstance(sequence, bool):
        raise ValueError(f"{field}.sequence must be an integer")
    kind = raw.get("kind")
    if kind not in {"original", "correction", "revocation"}:
        raise ValueError(f"{field}.kind is invalid")
    action_id = raw.get("action_id")
    if action_id is not None and not isinstance(action_id, str):
        raise ValueError(f"{field}.action_id must be a string or null")
    parent = raw.get("supersedes_record_id")
    if parent is not None and not isinstance(parent, str):
        raise ValueError(f"{field}.supersedes_record_id must be a string or null")
    return IntentRecord(
        record_id=_require_string(raw.get("record_id"), f"{field}.record_id"),
        sequence=sequence,
        kind=kind,
        instruction=_require_string(raw.get("instruction"), f"{field}.instruction"),
        action_id=action_id,
        supersedes_record_id=parent,
        revoked_action_ids=tuple(revoked),
        requires_fresh_approval=_require_bool(
            raw.get("requires_fresh_approval", False),
            f"{field}.requires_fresh_approval",
        ),
    )


def _recovery_arm(raw: Mapping[str, Any], index: int) -> RecoveryArm:
    prefix = f"arms[{index}]"
    scenario_raw = raw.get("scenario")
    envelope_raw = raw.get("envelope")
    if not isinstance(scenario_raw, Mapping):
        raise ValueError(f"{prefix}.scenario must be an object")
    if not isinstance(envelope_raw, Mapping):
        raise ValueError(f"{prefix}.envelope must be an object")

    scenario = RecoveryScenario(
        scenario_id=_require_string(
            scenario_raw.get("scenario_id"), f"{prefix}.scenario.scenario_id"
        ),
        original_intent_id=_require_string(
            scenario_raw.get("original_intent_id"),
            f"{prefix}.scenario.original_intent_id",
        ),
        correction_intent_id=_require_string(
            scenario_raw.get("correction_intent_id"),
            f"{prefix}.scenario.correction_intent_id",
        ),
        original_goal=_require_string(
            scenario_raw.get("original_goal"), f"{prefix}.scenario.original_goal"
        ),
        correction=_require_string(
            scenario_raw.get("correction"), f"{prefix}.scenario.correction"
        ),
        stale_action_id=_require_string(
            scenario_raw.get("stale_action_id"),
            f"{prefix}.scenario.stale_action_id",
        ),
        corrected_action_id=_require_string(
            scenario_raw.get("corrected_action_id"),
            f"{prefix}.scenario.corrected_action_id",
        ),
        fresh_approval_required=_require_bool(
            scenario_raw.get("fresh_approval_required"),
            f"{prefix}.scenario.fresh_approval_required",
        ),
    )

    checkpoint_raw = envelope_raw.get("checkpoint")
    intents_raw = envelope_raw.get("durable_intents")
    if not isinstance(checkpoint_raw, Mapping):
        raise ValueError(f"{prefix}.envelope.checkpoint must be an object")
    if not isinstance(intents_raw, list) or not intents_raw:
        raise ValueError(f"{prefix}.envelope.durable_intents must be non-empty")
    captured = checkpoint_raw.get("captured_through_sequence")
    if not isinstance(captured, int) or isinstance(captured, bool):
        raise ValueError(
            f"{prefix}.envelope.checkpoint.captured_through_sequence must be integer"
        )
    checkpoint = RecoveryCheckpoint(
        checkpoint_id=_require_string(
            checkpoint_raw.get("checkpoint_id"),
            f"{prefix}.envelope.checkpoint.checkpoint_id",
        ),
        captured_through_sequence=captured,
        selected_intent_id=_require_string(
            checkpoint_raw.get("selected_intent_id"),
            f"{prefix}.envelope.checkpoint.selected_intent_id",
        ),
        committed_action_id=_require_string(
            checkpoint_raw.get("committed_action_id"),
            f"{prefix}.envelope.checkpoint.committed_action_id",
        ),
    )
    intents: list[IntentRecord] = []
    for intent_index, intent_raw in enumerate(intents_raw):
        if not isinstance(intent_raw, Mapping):
            raise ValueError(
                f"{prefix}.envelope.durable_intents[{intent_index}] must be object"
            )
        intents.append(
            _intent_record(
                intent_raw,
                f"{prefix}.envelope.durable_intents[{intent_index}]",
            )
        )
    envelope = RecoveryEnvelope(
        recovery_instance_id=_require_string(
            envelope_raw.get("recovery_instance_id"),
            f"{prefix}.envelope.recovery_instance_id",
        ),
        crash_id=_require_string(
            envelope_raw.get("crash_id"), f"{prefix}.envelope.crash_id"
        ),
        checkpoint=checkpoint,
        durable_intents=tuple(intents),
    )
    validate_recovery_envelope(envelope)
    return RecoveryArm(
        arm_id=_require_string(raw.get("arm_id"), f"{prefix}.arm_id"),
        title=_require_string(raw.get("title"), f"{prefix}.title"),
        scenario=scenario,
        envelope=envelope,
        backstop_enabled=_require_bool(
            raw.get("backstop_enabled"), f"{prefix}.backstop_enabled"
        ),
    )


def load_recovery_manifest(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    raw = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("manifest root must be an object")
    _require_string(raw.get("batch_id"), "batch_id")

    provider = raw.get("provider")
    if not isinstance(provider, dict):
        raise ValueError("provider must be an object")
    _require_string(provider.get("model_slug"), "provider.model_slug")
    if not isinstance(provider.get("temperature"), (int, float)):
        raise ValueError("provider.temperature must be numeric")

    policy = raw.get("execution_policy")
    if not isinstance(policy, dict):
        raise ValueError("execution_policy must be an object")
    delay = policy.get("inter_arm_delay_seconds")
    if not isinstance(delay, (int, float)) or isinstance(delay, bool) or delay < 0:
        raise ValueError("inter_arm_delay_seconds must be non-negative")
    retries = policy.get("sdk_max_retries")
    if not isinstance(retries, int) or isinstance(retries, bool) or retries < 0:
        raise ValueError("sdk_max_retries must be a non-negative integer")

    arms = raw.get("arms")
    if not isinstance(arms, list) or not arms:
        raise ValueError("arms must be a non-empty list")
    seen: set[str] = set()
    for index, item in enumerate(arms):
        if not isinstance(item, Mapping):
            raise ValueError(f"arms[{index}] must be an object")
        arm = _recovery_arm(item, index)
        if arm.arm_id in seen:
            raise ValueError(f"duplicate arm_id: {arm.arm_id}")
        seen.add(arm.arm_id)

    publication = raw.get("publication_rule")
    if not isinstance(publication, dict):
        raise ValueError("publication_rule must be an object")
    for field in (
        "publish_all_arms",
        "publish_indeterminate_runs",
        "no_cherry_picking",
        "no_outcome_based_classifier_changes",
    ):
        if publication.get(field) is not True:
            raise ValueError(f"{field} must be true")
    return raw


def recovery_arms(manifest: Mapping[str, Any]) -> tuple[RecoveryArm, ...]:
    return tuple(_recovery_arm(item, index) for index, item in enumerate(manifest["arms"]))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _evidence_payload(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Mapping):
        return dict(value)
    raise TypeError("adapter evidence must be a dataclass or mapping")


def run_recovery_batch(
    manifest: Mapping[str, Any],
    *,
    adapter_factory: AdapterFactory,
    output_dir: str | Path,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> RecoveryBatchSummary:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)

    provider = manifest["provider"]
    policy = manifest["execution_policy"]
    model = str(provider["model_slug"])
    temperature = float(provider["temperature"])
    retries = int(policy["sdk_max_retries"])
    delay = float(policy["inter_arm_delay_seconds"])

    records: list[RecoveryBatchRecord] = []
    for index, arm in enumerate(recovery_arms(manifest)):
        if index > 0 and delay > 0:
            sleep_fn(delay)

        arm_dir = destination / arm.arm_id
        result_path = arm_dir / "result.json"
        evidence_path = arm_dir / "model-evidence.json"
        error_path = arm_dir / "error.json"
        try:
            adapter = adapter_factory(model, temperature, retries)
            result: RecoveryResult = run_recovery(
                adapter,
                arm.scenario,
                arm.envelope,
                backstop_enabled=arm.backstop_enabled,
            )
            save_recovery_result(result, result_path)
            _write_json(evidence_path, _evidence_payload(adapter.evidence()))
            records.append(
                RecoveryBatchRecord(
                    arm_id=arm.arm_id,
                    title=arm.title,
                    classification=result.classification,
                    result_path=str(result_path),
                    evidence_path=str(evidence_path),
                    error_path=None,
                )
            )
        except Exception as exc:
            _write_json(
                error_path,
                {
                    "arm_id": arm.arm_id,
                    "stage": "execution_or_evidence",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "classification": "INDETERMINATE",
                },
            )
            records.append(
                RecoveryBatchRecord(
                    arm_id=arm.arm_id,
                    title=arm.title,
                    classification="INDETERMINATE",
                    result_path=None,
                    evidence_path=None,
                    error_path=str(error_path),
                )
            )

    counts = Counter(record.classification for record in records)
    counterexample_labels = {
        "RECOVERY_REVIVED_STALE_INTENT",
        "RECOVERY_CORRECTED_ACTION_WITHOUT_APPROVAL",
    }
    counterexamples = tuple(
        record.arm_id
        for record in records
        if record.classification in counterexample_labels
    )
    indeterminate = tuple(
        record.arm_id
        for record in records
        if record.classification == "INDETERMINATE"
    )
    summary = RecoveryBatchSummary(
        batch_id=str(manifest["batch_id"]),
        requested_model=model,
        temperature=temperature,
        sdk_max_retries=retries,
        inter_arm_delay_seconds=delay,
        total_arms=len(records),
        counts=dict(sorted(counts.items())),
        counterexample_arms=counterexamples,
        indeterminate_arms=indeterminate,
        records=tuple(records),
    )
    _write_json(destination / "batch-summary.json", asdict(summary))
    return summary
