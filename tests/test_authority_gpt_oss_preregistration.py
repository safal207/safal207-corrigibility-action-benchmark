import json
from pathlib import Path

from corrigibility_benchmark.authority_batch import arm_inputs, load_authority_manifest
from corrigibility_benchmark.authority_resolution import resolve_authority


SOURCE = Path("preregistrations/authority-openrouter-ox-alpha-v1.json")
REPLICATION = Path("preregistrations/authority-openrouter-gpt-oss-120b-v1.json")


def test_named_model_replication_copies_provider_obscured_arms_exactly():
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    replication = load_authority_manifest(REPLICATION)

    ids = replication["execution_policy"]["arm_order"]
    source_by_id = {arm["arm_id"]: arm for arm in source["arms"]}
    assert replication["arms"] == [source_by_id[arm_id] for arm_id in ids]

    assert ids == [
        "AR1-SAME-SOURCE-LATER-STOP",
        "AR3-UNAUTHENTICATED-CONTINUE",
        "AR4-REVOKED-SOURCE-CONTINUE",
        "AR5-EQUAL-RANK-UNRESOLVED-CONFLICT",
    ]


def test_named_model_replication_changes_only_registered_provider_identity():
    replication = load_authority_manifest(REPLICATION)
    assert replication["provider"]["model_slug"] == "openai/gpt-oss-120b:free"
    assert replication["provider"]["temperature"] == 0.0
    assert replication["design"]["changed_factor"] == "model/provider identity only"
    assert replication["implementation"]["authority_harness_merge_commit"] == (
        "f368e044cd66f033db8e29bb0fac435f06f09e24"
    )
    policy = replication["execution_policy"]
    assert policy["inter_arm_delay_seconds"] == 60
    assert policy["sdk_max_retries"] == 0
    assert policy["automatic_batch_retries"] == 0
    assert policy["selective_reruns_prohibited"] is True
    assert replication["publication_rule"]["publish_all_arms"] is True
    assert replication["publication_rule"]["no_cherry_picking"] is True

    for arm in replication["arms"]:
        _, envelope, _ = arm_inputs(arm)
        resolution = resolve_authority(envelope)
        expected = arm["expected_policy_resolution"]
        assert resolution.controlling_source_id == expected["controlling_source_id"]
        assert resolution.controlling_record_id == expected["controlling_record_id"]
        assert resolution.unresolved_conflict is expected["unresolved_conflict"]
