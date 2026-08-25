"""Batch orchestration for commitment-admission experiments."""

from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from .commitment_admission import (
    AdmissionResult,
    AdmissionScenario,
    run_admission,
    save_admission_result,
)


AdapterFactory = Callable[[str, float, int], Any]


@dataclass(frozen=True)
class AdmissionBatchRecord:
    scenario_id: str
    title: str
    classification: str
    result_path: str | None
    evidence_path: str | None
    error_path: str | None


@dataclass(frozen=True)
class AdmissionBatchSummary:
    batch_id: str
    requested_model: str
    temperature: float
    sdk_max_retries: int
    inter_scenario_delay_seconds: float
    total_scenarios: int
    counts: dict[str, int]
    unsafe_admission_scenarios: tuple[str, ...]
    indeterminate_scenarios: tuple[str, ...]
    records: tuple[AdmissionBatchRecord, ...]


def _require_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _require_string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ValueError(f"{field} must be a list of non-empty strings")
    return value


def load_admission_manifest(path: str | Path) -> dict[str, Any]:
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
    delay = policy.get("inter_scenario_delay_seconds")
    if not isinstance(delay, (int, float)) or isinstance(delay, bool) or delay < 0:
        raise ValueError("inter_scenario_delay_seconds must be non-negative")
    retries = policy.get("sdk_max_retries")
    if not isinstance(retries, int) or isinstance(retries, bool) or retries < 0:
        raise ValueError("sdk_max_retries must be a non-negative integer")

    scenarios = raw.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise ValueError("scenarios must be a non-empty list")
    seen: set[str] = set()
    for index, item in enumerate(scenarios):
        if not isinstance(item, dict):
            raise ValueError(f"scenarios[{index}] must be an object")
        for field in ("scenario_id", "title", "goal", "action_id"):
            _require_string(item.get(field), f"scenarios[{index}].{field}")
        evidence_state = item.get("evidence_state")
        if evidence_state not in {"sufficient", "missing", "contradictory"}:
            raise ValueError(f"scenarios[{index}].evidence_state is invalid")
        _require_string_list(
            item.get("evidence_facts"),
            f"scenarios[{index}].evidence_facts",
        )
        _require_string_list(
            item.get("required_evidence"),
            f"scenarios[{index}].required_evidence",
        )
        pressure_facts = item.get("pressure_facts", [])
        _require_string_list(
            pressure_facts,
            f"scenarios[{index}].pressure_facts",
        )
        scenario_id = str(item["scenario_id"])
        if scenario_id in seen:
            raise ValueError(f"duplicate scenario_id: {scenario_id}")
        seen.add(scenario_id)

    publication = raw.get("publication_rule")
    if not isinstance(publication, dict):
        raise ValueError("publication_rule must be an object")
    if publication.get("publish_all_scenarios") is not True:
        raise ValueError("publish_all_scenarios must be true")
    if publication.get("publish_indeterminate_runs") is not True:
        raise ValueError("publish_indeterminate_runs must be true")
    if publication.get("no_cherry_picking") is not True:
        raise ValueError("no_cherry_picking must be true")
    if publication.get("no_outcome_based_classifier_changes") is not True:
        raise ValueError("no_outcome_based_classifier_changes must be true")

    return raw


def admission_scenarios(
    manifest: Mapping[str, Any],
) -> tuple[AdmissionScenario, ...]:
    values: list[AdmissionScenario] = []
    for item in manifest["scenarios"]:
        values.append(
            AdmissionScenario(
                scenario_id=item["scenario_id"],
                title=item["title"],
                goal=item["goal"],
                action_id=item["action_id"],
                evidence_state=item["evidence_state"],
                evidence_facts=tuple(item["evidence_facts"]),
                required_evidence=tuple(item["required_evidence"]),
                pressure_facts=tuple(item.get("pressure_facts", [])),
            )
        )
    return tuple(values)


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


def run_admission_batch(
    manifest: Mapping[str, Any],
    *,
    adapter_factory: AdapterFactory,
    output_dir: str | Path,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> AdmissionBatchSummary:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)

    provider = manifest["provider"]
    policy = manifest["execution_policy"]
    model = str(provider["model_slug"])
    temperature = float(provider["temperature"])
    retries = int(policy["sdk_max_retries"])
    delay = float(policy["inter_scenario_delay_seconds"])

    records: list[AdmissionBatchRecord] = []
    for index, scenario in enumerate(admission_scenarios(manifest)):
        if index > 0 and delay > 0:
            sleep_fn(delay)

        scenario_dir = destination / scenario.scenario_id
        result_path = scenario_dir / "result.json"
        evidence_path = scenario_dir / "model-evidence.json"
        error_path = scenario_dir / "error.json"

        try:
            adapter = adapter_factory(model, temperature, retries)
            result: AdmissionResult = run_admission(adapter, scenario)
            save_admission_result(result, result_path)
            _write_json(evidence_path, _evidence_payload(adapter.evidence()))
            records.append(
                AdmissionBatchRecord(
                    scenario_id=scenario.scenario_id,
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
                    "scenario_id": scenario.scenario_id,
                    "stage": "execution_or_evidence",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "classification": "INDETERMINATE",
                },
            )
            records.append(
                AdmissionBatchRecord(
                    scenario_id=scenario.scenario_id,
                    title=scenario.title,
                    classification="INDETERMINATE",
                    result_path=None,
                    evidence_path=None,
                    error_path=str(error_path),
                )
            )

    counts = Counter(record.classification for record in records)
    unsafe = tuple(
        record.scenario_id
        for record in records
        if record.classification == "UNSAFE_ADMISSION"
    )
    indeterminate = tuple(
        record.scenario_id
        for record in records
        if record.classification == "INDETERMINATE"
    )
    summary = AdmissionBatchSummary(
        batch_id=str(manifest["batch_id"]),
        requested_model=model,
        temperature=temperature,
        sdk_max_retries=retries,
        inter_scenario_delay_seconds=delay,
        total_scenarios=len(records),
        counts=dict(sorted(counts.items())),
        unsafe_admission_scenarios=unsafe,
        indeterminate_scenarios=indeterminate,
        records=tuple(records),
    )
    _write_json(destination / "batch-summary.json", asdict(summary))
    return summary
