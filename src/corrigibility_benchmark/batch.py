"""Batch orchestration for preregistered C1 experiments.

The batch layer does not alter the frozen C1 classifier. It only loads a
preregistered manifest, runs each scenario independently, and preserves every
outcome, including indeterminate infrastructure failures.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any, Callable, Literal, Mapping

from .c1 import C1Scenario, PairResult, run_pair, save_pair


AdapterFactory = Callable[[str, float], Any]
EvidenceStatus = Literal["complete", "partial", "unavailable"]


@dataclass(frozen=True)
class ScenarioSpec:
    scenario_id: str
    title: str
    original_goal: str
    intervention: str
    stale_action_id: str
    corrected_action_id: str
    required_success_evidence: str | None = None

    def to_scenario(self) -> C1Scenario:
        return C1Scenario(
            scenario_id=self.scenario_id,
            original_goal=self.original_goal,
            intervention=self.intervention,
            stale_action_id=self.stale_action_id,
            corrected_action_id=self.corrected_action_id,
            required_success_evidence=self.required_success_evidence,
        )


@dataclass(frozen=True)
class BatchRecord:
    scenario_id: str
    title: str
    classification: str
    backstop_was_necessary: bool
    trace_path: str | None
    evidence_path: str | None
    evidence_status: EvidenceStatus
    evidence_error_path: str | None
    error_path: str | None


@dataclass(frozen=True)
class BatchSummary:
    batch_id: str
    requested_model: str
    temperature: float
    inter_scenario_delay_seconds: float
    total_scenarios: int
    counts: dict[str, int]
    counterexample_scenarios: tuple[str, ...]
    indeterminate_scenarios: tuple[str, ...]
    records: tuple[BatchRecord, ...]


def _require_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def load_manifest(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    raw = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("manifest root must be an object")

    _require_string(raw.get("batch_id"), "batch_id")
    provider = raw.get("provider")
    if not isinstance(provider, dict):
        raise ValueError("provider must be an object")
    _require_string(provider.get("model_slug"), "provider.model_slug")
    temperature = provider.get("temperature")
    if not isinstance(temperature, (int, float)):
        raise ValueError("provider.temperature must be numeric")

    execution_policy = raw.get("execution_policy")
    if execution_policy is not None:
        if not isinstance(execution_policy, dict):
            raise ValueError("execution_policy must be an object")
        delay = execution_policy.get("inter_scenario_delay_seconds", 0)
        if not isinstance(delay, (int, float)) or isinstance(delay, bool) or delay < 0:
            raise ValueError(
                "execution_policy.inter_scenario_delay_seconds must be non-negative"
            )
        max_retries = execution_policy.get("sdk_max_retries", 0)
        if not isinstance(max_retries, int) or isinstance(max_retries, bool) or max_retries < 0:
            raise ValueError(
                "execution_policy.sdk_max_retries must be a non-negative integer"
            )

    scenarios = raw.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise ValueError("scenarios must be a non-empty list")

    seen: set[str] = set()
    required = (
        "scenario_id",
        "title",
        "original_goal",
        "intervention",
        "stale_action_id",
        "corrected_action_id",
    )
    for index, item in enumerate(scenarios):
        if not isinstance(item, dict):
            raise ValueError(f"scenarios[{index}] must be an object")
        for field in required:
            _require_string(item.get(field), f"scenarios[{index}].{field}")
        scenario_id = str(item["scenario_id"])
        if scenario_id in seen:
            raise ValueError(f"duplicate scenario_id: {scenario_id}")
        seen.add(scenario_id)

    publication = raw.get("publication_rule")
    if not isinstance(publication, dict):
        raise ValueError("publication_rule must be an object")
    if publication.get("publish_all_scenarios") is not True:
        raise ValueError("publish_all_scenarios must be true")
    if publication.get("no_cherry_picking") is not True:
        raise ValueError("no_cherry_picking must be true")
    if publication.get("no_outcome_based_evaluator_changes") is not True:
        raise ValueError("no_outcome_based_evaluator_changes must be true")

    classification = raw.get("classification_contract")
    if not isinstance(classification, dict):
        raise ValueError("classification_contract must be an object")
    labels = classification.get("counterexample_labels")
    if not isinstance(labels, list) or not labels:
        raise ValueError("counterexample_labels must be a non-empty list")

    return raw


def scenario_specs(manifest: Mapping[str, Any]) -> tuple[ScenarioSpec, ...]:
    values: list[ScenarioSpec] = []
    for item in manifest["scenarios"]:
        values.append(
            ScenarioSpec(
                scenario_id=item["scenario_id"],
                title=item["title"],
                original_goal=item["original_goal"],
                intervention=item["intervention"],
                stale_action_id=item["stale_action_id"],
                corrected_action_id=item["corrected_action_id"],
                required_success_evidence=item.get("required_success_evidence"),
            )
        )
    return tuple(values)


def _evidence_payload(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Mapping):
        return dict(value)
    raise TypeError("adapter evidence must be a dataclass or mapping")


def _partial_evidence_payload(adapter: Any) -> Any | None:
    exporter = getattr(adapter, "partial_evidence", None)
    if not callable(exporter):
        return None
    value = exporter()
    if value is None:
        return None
    return _evidence_payload(value)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def run_batch(
    manifest: Mapping[str, Any],
    *,
    adapter_factory: AdapterFactory,
    output_dir: str | Path,
    backstop_enabled: bool = True,
    inter_scenario_delay_seconds: float = 0.0,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> BatchSummary:
    """Run every preregistered scenario and preserve every outcome.

    A provider/runtime exception before classification is recorded as
    ``INDETERMINATE`` and the batch continues. Once a normalized trace and
    classification exist, a later evidence-export failure cannot overwrite
    them; evidence completeness is recorded on a separate axis.

    Pacing is explicit and occurs only between scenarios, never before the
    first scenario or after the final one.
    """

    if inter_scenario_delay_seconds < 0:
        raise ValueError("inter_scenario_delay_seconds must be non-negative")

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)

    provider = manifest["provider"]
    model = str(provider["model_slug"])
    temperature = float(provider["temperature"])
    counterexample_labels = set(
        manifest["classification_contract"]["counterexample_labels"]
    )

    records: list[BatchRecord] = []
    for index, spec in enumerate(scenario_specs(manifest)):
        if index > 0 and inter_scenario_delay_seconds > 0:
            sleep_fn(inter_scenario_delay_seconds)

        scenario_dir = destination / spec.scenario_id
        trace_path = scenario_dir / "trace.json"
        evidence_path = scenario_dir / "model-evidence.json"
        partial_evidence_path = scenario_dir / "model-evidence.partial.json"
        evidence_error_path = scenario_dir / "evidence-error.json"
        error_path = scenario_dir / "error.json"

        try:
            adapter = adapter_factory(model, temperature)
            result: PairResult = run_pair(
                adapter,
                spec.to_scenario(),
                backstop_enabled=backstop_enabled,
            )
        except Exception as exc:
            _write_json(
                error_path,
                {
                    "scenario_id": spec.scenario_id,
                    "stage": "execution",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "classification": "INDETERMINATE",
                },
            )
            records.append(
                BatchRecord(
                    scenario_id=spec.scenario_id,
                    title=spec.title,
                    classification="INDETERMINATE",
                    backstop_was_necessary=False,
                    trace_path=None,
                    evidence_path=None,
                    evidence_status="unavailable",
                    evidence_error_path=None,
                    error_path=str(error_path),
                )
            )
            continue

        save_pair(result, trace_path)

        evidence_status: EvidenceStatus = "unavailable"
        stored_evidence_path: str | None = None
        stored_evidence_error_path: str | None = None
        try:
            _write_json(evidence_path, _evidence_payload(adapter.evidence()))
            evidence_status = "complete"
            stored_evidence_path = str(evidence_path)
        except Exception as exc:
            partial_export_error: dict[str, str] | None = None
            try:
                partial_payload = _partial_evidence_payload(adapter)
                if partial_payload is not None:
                    _write_json(partial_evidence_path, partial_payload)
                    evidence_status = "partial"
                    stored_evidence_path = str(partial_evidence_path)
            except Exception as partial_exc:
                partial_export_error = {
                    "error_type": type(partial_exc).__name__,
                    "error": str(partial_exc),
                }

            error_payload: dict[str, Any] = {
                "scenario_id": spec.scenario_id,
                "stage": "evidence_export",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "classification_preserved": result.classification,
                "trace_path": str(trace_path),
                "evidence_status": evidence_status,
            }
            if partial_export_error is not None:
                error_payload["partial_export_error"] = partial_export_error
            _write_json(evidence_error_path, error_payload)
            stored_evidence_error_path = str(evidence_error_path)

        records.append(
            BatchRecord(
                scenario_id=spec.scenario_id,
                title=spec.title,
                classification=result.classification,
                backstop_was_necessary=result.backstop_was_necessary,
                trace_path=str(trace_path),
                evidence_path=stored_evidence_path,
                evidence_status=evidence_status,
                evidence_error_path=stored_evidence_error_path,
                error_path=None,
            )
        )

    counts = Counter(record.classification for record in records)
    counterexamples = tuple(
        record.scenario_id
        for record in records
        if record.classification in counterexample_labels
    )
    indeterminate = tuple(
        record.scenario_id
        for record in records
        if record.classification == "INDETERMINATE"
    )
    summary = BatchSummary(
        batch_id=str(manifest["batch_id"]),
        requested_model=model,
        temperature=temperature,
        inter_scenario_delay_seconds=inter_scenario_delay_seconds,
        total_scenarios=len(records),
        counts=dict(sorted(counts.items())),
        counterexample_scenarios=counterexamples,
        indeterminate_scenarios=indeterminate,
        records=tuple(records),
    )
    _write_json(destination / "batch-summary.json", asdict(summary))
    return summary
