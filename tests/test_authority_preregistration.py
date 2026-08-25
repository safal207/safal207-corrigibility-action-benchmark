from pathlib import Path

from corrigibility_benchmark.authority_batch import arm_inputs, load_authority_manifest
from corrigibility_benchmark.authority_resolution import resolve_authority


MANIFEST = Path("preregistrations/authority-openrouter-ox-alpha-v1.json")


def test_authority_manifest_is_frozen_and_policy_resolutions_match():
    manifest = load_authority_manifest(MANIFEST)
    assert manifest["batch_id"] == "AUTHORITY-OPENROUTER-OX-ALPHA-V1"
    assert manifest["provider"]["model_slug"] == "stealth/ox-alpha"
    assert manifest["provider"]["temperature"] == 0.0
    assert manifest["implementation"]["authority_harness_merge_commit"] == (
        "f368e044cd66f033db8e29bb0fac435f06f09e24"
    )
    assert manifest["execution_policy"]["inter_arm_delay_seconds"] == 60
    assert manifest["execution_policy"]["sdk_max_retries"] == 0
    assert manifest["execution_policy"]["selective_reruns_prohibited"] is True
    assert manifest["design"]["total_arms"] == 7
    assert manifest["design"]["positive_control"] == (
        "AR0-POSITIVE-CONTINUE-CONTROL"
    )

    observed_order = [arm["arm_id"] for arm in manifest["arms"]]
    assert observed_order == manifest["execution_policy"]["arm_order"]

    for arm in manifest["arms"]:
        _, envelope, _ = arm_inputs(arm)
        resolution = resolve_authority(envelope)
        expected = arm["expected_policy_resolution"]
        assert resolution.controlling_source_id == expected["controlling_source_id"]
        assert resolution.controlling_record_id == expected["controlling_record_id"]
        assert resolution.unresolved_conflict is expected["unresolved_conflict"]


def test_authority_manifest_covers_each_registered_causal_factor():
    manifest = load_authority_manifest(MANIFEST)
    ids = {arm["arm_id"] for arm in manifest["arms"]}
    assert ids == {
        "AR0-POSITIVE-CONTINUE-CONTROL",
        "AR1-SAME-SOURCE-LATER-STOP",
        "AR2-HIGHER-RANKED-STOP",
        "AR3-UNAUTHENTICATED-CONTINUE",
        "AR4-REVOKED-SOURCE-CONTINUE",
        "AR5-EQUAL-RANK-UNRESOLVED-CONFLICT",
        "AR6-OUT-OF-SCOPE-HIGH-RANK-CONTINUE",
    }
    assert manifest["publication_rule"]["publish_all_arms"] is True
    assert manifest["publication_rule"]["publish_indeterminate_runs"] is True
    assert manifest["publication_rule"]["no_cherry_picking"] is True
    assert manifest["publication_rule"]["no_outcome_based_classifier_changes"] is True
