from pathlib import Path

from corrigibility_benchmark.batch import load_manifest, scenario_specs


ORIGINAL = Path("preregistrations/c1-openrouter-ox-alpha-hard-v1.json")
REPLICATION = Path(
    "preregistrations/c1-openrouter-ox-alpha-paced-h245-v1.json"
)
TARGET_IDS = [
    "C1-H2-PRIOR-APPROVAL-REVOKED",
    "C1-H4-STAKEHOLDER-PRESSURE",
    "C1-H5-PARTIAL-CONTINUATION",
]


def test_paced_replication_is_frozen_and_reuses_exact_scenario_text():
    original = load_manifest(ORIGINAL)
    replication = load_manifest(REPLICATION)

    assert replication["batch_id"] == "C1-OPENROUTER-OX-ALPHA-PACED-H245-V1"
    assert replication["provider"]["model_slug"] == "stealth/ox-alpha"
    assert replication["provider"]["temperature"] == 0.0

    policy = replication["execution_policy"]
    assert policy["scenario_order"] == TARGET_IDS
    assert policy["trial_count_per_scenario"] == 1
    assert policy["inter_scenario_delay_seconds"] == 60
    assert policy["sdk_max_retries"] == 0
    assert policy["automatic_batch_retries"] == 0
    assert policy["selective_reruns_prohibited"] is True

    assert [spec.scenario_id for spec in scenario_specs(replication)] == TARGET_IDS

    original_by_id = {
        item["scenario_id"]: item
        for item in original["scenarios"]
        if item["scenario_id"] in TARGET_IDS
    }
    replication_by_id = {
        item["scenario_id"]: item for item in replication["scenarios"]
    }
    assert set(original_by_id) == set(TARGET_IDS)

    compared_fields = (
        "title",
        "pressure_dimension",
        "original_goal",
        "intervention",
        "stale_action_id",
        "corrected_action_id",
    )
    for scenario_id in TARGET_IDS:
        for field in compared_fields:
            assert replication_by_id[scenario_id][field] == original_by_id[scenario_id][field]

    implementation = replication["implementation"]
    assert implementation["frozen_evaluator_merge_commit"] == (
        "38d883497f5c9555a0ba21184a0dc51d988ef02a"
    )
    assert implementation["evidence_preservation_merge_commit"] == (
        "31d9af6a9ab2a591d80410dc76482eeb269ea29b"
    )
    assert implementation["paced_batch_controls_merge_commit"] == (
        "c48f7524ddf269a53d9304a5c2b0386b61924871"
    )

    publication = replication["publication_rule"]
    assert publication["publish_all_scenarios"] is True
    assert publication["publish_indeterminate_runs"] is True
    assert publication["no_cherry_picking"] is True
    assert publication["no_outcome_based_evaluator_changes"] is True
