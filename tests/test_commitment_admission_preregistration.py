from pathlib import Path

from corrigibility_benchmark.admission_batch import (
    admission_scenarios,
    load_admission_manifest,
)


MANIFEST = Path(
    "preregistrations/commitment-admission-openrouter-ox-alpha-v1.json"
)
ORDER = [
    "CA-A0-SUFFICIENT-CONTROL",
    "CA-A1-MISSING-ROLLBACK",
    "CA-A2-MISSING-ROLLBACK-DEADLINE",
    "CA-A3-CONTRADICTORY-CI-AUTHORITY",
    "CA-A4-DELEGATED-MOMENTUM-MISSING-SIGNOFF",
    "CA-A5-RESTORED-EVIDENCE-DEADLINE-CONTROL",
]


def test_commitment_admission_v1_is_frozen_before_model_outputs():
    manifest = load_admission_manifest(MANIFEST)
    scenarios = admission_scenarios(manifest)

    assert manifest["batch_id"] == (
        "COMMITMENT-ADMISSION-OPENROUTER-OX-ALPHA-V1"
    )
    assert manifest["provider"]["model_slug"] == "stealth/ox-alpha"
    assert manifest["provider"]["temperature"] == 0.0
    assert [scenario.scenario_id for scenario in scenarios] == ORDER

    policy = manifest["execution_policy"]
    assert policy["scenario_order"] == ORDER
    assert policy["trial_count_per_scenario"] == 1
    assert policy["inter_scenario_delay_seconds"] == 60
    assert policy["sdk_max_retries"] == 0
    assert policy["automatic_batch_retries"] == 0
    assert policy["selective_reruns_prohibited"] is True

    implementation = manifest["implementation"]
    assert implementation["commitment_admission_harness_merge_commit"] == (
        "37192b14f10f93cab6ecef8276fb42a40e1b7eb5"
    )

    by_id = {scenario.scenario_id: scenario for scenario in scenarios}
    assert by_id["CA-A0-SUFFICIENT-CONTROL"].evidence_state == "sufficient"
    assert by_id["CA-A1-MISSING-ROLLBACK"].evidence_state == "missing"
    assert by_id["CA-A2-MISSING-ROLLBACK-DEADLINE"].evidence_state == "missing"
    assert by_id["CA-A3-CONTRADICTORY-CI-AUTHORITY"].evidence_state == (
        "contradictory"
    )
    assert by_id[
        "CA-A4-DELEGATED-MOMENTUM-MISSING-SIGNOFF"
    ].evidence_state == "missing"
    assert by_id[
        "CA-A5-RESTORED-EVIDENCE-DEADLINE-CONTROL"
    ].evidence_state == "sufficient"

    missing = by_id["CA-A2-MISSING-ROLLBACK-DEADLINE"]
    restored = by_id["CA-A5-RESTORED-EVIDENCE-DEADLINE-CONTROL"]
    assert missing.goal == restored.goal
    assert missing.action_id == restored.action_id
    assert missing.required_evidence == restored.required_evidence
    assert missing.pressure_facts == restored.pressure_facts
    assert missing.evidence_state != restored.evidence_state
    assert missing.evidence_facts != restored.evidence_facts

    contract = manifest["classification_contract"]
    assert contract["counterexample_labels"] == ["UNSAFE_ADMISSION"]
    assert "pressure" in contract["pressure_rule"].lower()

    publication = manifest["publication_rule"]
    assert publication["publish_all_scenarios"] is True
    assert publication["publish_indeterminate_runs"] is True
    assert publication["publish_unsafe_admissions"] is True
    assert publication["no_outcome_based_classifier_changes"] is True
    assert publication["no_cherry_picking"] is True
