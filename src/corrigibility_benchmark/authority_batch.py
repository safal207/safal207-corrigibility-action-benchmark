"""Batch orchestration for preregistered authority-resolution experiments."""

from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from .authority_resolution import (
    AuthorityEnvelope,
    AuthorityInstruction,
    AuthorityPolicy,
    AuthorityScenario,
    AuthoritySource,
    run_authority_resolution,
    save_authority_result,
)


AdapterFactory = Callable[[str, float, int], Any]


@dataclass(frozen=True)
class AuthorityBatchRecord:
    arm_id: str
    title: str
    classification: str
    result_path: str | None
    evidence_path: str | None
    error_path: str | None


@dataclass(frozen=True)
class AuthorityBatchSummary:
    batch_id: str
    requested_model: str
    temperature: float
    sdk_max_retries: int
    inter_arm_delay_seconds: float
    total_arms: int
    counts: dict[str, int]
    counterexample_arms: tuple[str, ...]
    indeterminate_arms: tuple[str, ...]
    records: tuple[AuthorityBatchRecord, ...]


def _require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def load_authority_manifest(path: str | Path) -> dict[str, Any]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("manifest root must be an object")
    _require_text(raw.get("batch_id"), "batch_id")

    provider = raw.get("provider")
    if not isinstance(provider, dict):
        raise ValueError("provider must be an object")
    _require_text(provider.get("model_slug"), "provider.model_slug")
    if not isinstance(provider.get("temperature"), (int, float)):
        raise ValueError("provider.temperature must be numeric")

    policy = raw.get("execution_policy")
    if not isinstance(policy, dict):
        raise ValueError("execution_policy must be an object")
    delay = policy.get("inter_arm_delay_seconds")
    retries = policy.get("sdk_max_retries")
    if not isinstance(delay, (int, float)) or isinstance(delay, bool) or delay < 0:
        raise ValueError("inter_arm_delay_seconds must be non-negative")
    if not isinstance(retries, int) or isinstance(retries, bool) or retries < 0:
        raise ValueError("sdk_max_retries must be a non-negative integer")

    arms = raw.get("arms")
    if not isinstance(arms, list) or not arms:
        raise ValueError("arms must be a non-empty list")
    seen: set[str] = set()
    for index, arm in enumerate(arms):
        if not isinstance(arm, dict):
            raise ValueError(f"arms[{index}] must be an object")
        arm_id = _require_text(arm.get("arm_id"), f"arms[{index}].arm_id")
        _require_text(arm.get("title"), f"arms[{index}].title")
        if arm_id in seen:
            raise ValueError(f"duplicate arm_id: {arm_id}")
        seen.add(arm_id)

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


def _source(data: Mapping[str, Any]) -> AuthoritySource:
    return AuthoritySource(
        source_id=data["source_id"],
        authenticated=bool(data["authenticated"]),
        authority_domains=tuple(data["authority_domains"]),
        rank=int(data["rank"]),
        active=bool(data.get("active", True)),
    )


def _instruction(data: Mapping[str, Any]) -> AuthorityInstruction:
    return AuthorityInstruction(
        record_id=data["record_id"],
        source_id=data["source_id"],
        sequence=int(data["sequence"]),
        instruction=data["instruction"],
        action_id=data.get("action_id"),
        supersedes_record_id=data.get("supersedes_record_id"),
    )


def arm_inputs(
    arm: Mapping[str, Any],
) -> tuple[AuthorityScenario, AuthorityEnvelope, bool]:
    scenario = AuthorityScenario(
        scenario_id=arm["arm_id"],
        title=arm["title"],
        protected_action_id=arm.get("protected_action_id", "deploy:version-A"),
    )
    policy_data = arm["policy"]
    envelope = AuthorityEnvelope(
        sources=tuple(_source(value) for value in arm["sources"]),
        instructions=tuple(_instruction(value) for value in arm["instructions"]),
        explicitly_revoked_source_ids=tuple(
            arm.get("explicitly_revoked_source_ids", [])
        ),
        policy=AuthorityPolicy(
            required_domain=policy_data["required_domain"],
            higher_rank_wins=bool(policy_data.get("higher_rank_wins", True)),
            equal_rank_conflict_requires_clarification=bool(
                policy_data.get("equal_rank_conflict_requires_clarification", True)
            ),
        ),
    )
    return scenario, envelope, bool(arm.get("backstop_enabled", True))


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


def run_authority_batch(
    manifest: Mapping[str, Any],
    *,
    adapter_factory: AdapterFactory,
    output_dir: str | Path,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> AuthorityBatchSummary:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    provider = manifest["provider"]
    execution = manifest["execution_policy"]
    model = str(provider["model_slug"])
    temperature = float(provider["temperature"])
    retries = int(execution["sdk_max_retries"])
    delay = float(execution["inter_arm_delay_seconds"])

    records: list[AuthorityBatchRecord] = []
    for index, arm in enumerate(manifest["arms"]):
        if index > 0 and delay > 0:
            sleep_fn(delay)
        scenario, envelope, backstop = arm_inputs(arm)
        arm_dir = destination / scenario.scenario_id
        result_path = arm_dir / "result.json"
        evidence_path = arm_dir / "model-evidence.json"
        error_path = arm_dir / "error.json"
        try:
            adapter = adapter_factory(model, temperature, retries)
            result = run_authority_resolution(
                adapter,
                scenario,
                envelope,
                backstop_enabled=backstop,
            )
            save_authority_result(result, result_path)
            _write_json(evidence_path, _evidence_payload(adapter.evidence()))
            records.append(
                AuthorityBatchRecord(
                    arm_id=scenario.scenario_id,
                    title=scenario.title,
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
                    "arm_id": scenario.scenario_id,
                    "classification": "INDETERMINATE",
                    "stage": "execution_or_evidence",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )
            records.append(
                AuthorityBatchRecord(
                    arm_id=scenario.scenario_id,
                    title=scenario.title,
                    classification="INDETERMINATE",
                    result_path=None,
                    evidence_path=None,
                    error_path=str(error_path),
                )
            )

    counts = Counter(record.classification for record in records)
    counterexample_labels = {
        "AUTHORITY_FOLLOWED_NONCONTROLLING_SOURCE",
        "AUTHORITY_ACCEPTED_INVALID_SOURCE",
        "AUTHORITY_CONFLICT_UNRESOLVED_ACTION",
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
    summary = AuthorityBatchSummary(
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
