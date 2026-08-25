from pathlib import Path

from corrigibility_benchmark.batch import load_manifest, scenario_specs


MANIFEST = Path("preregistrations/c1-openrouter-ox-alpha-hard-v1.json")


def test_hard_batch_manifest_is_frozen_and_complete():
    manifest = load_manifest(MANIFEST)
    specs = scenario_specs(manifest)

    assert manifest["batch_id"] == "C1-OPENROUTER-OX-ALPHA-HARD-V1"
    assert manifest["provider"]["model_slug"] == "stealth/ox-alpha"
    assert manifest["provider"]["temperature"] == 0.0
    assert manifest["design"]["total_scenarios"] == 5
    assert manifest["design"]["expected_api_calls"] == 15
    assert len(specs) == 5
    assert [spec.scenario_id for spec in specs] == [
        "C1-H1-SUNK-COST-DEADLINE",
        "C1-H2-PRIOR-APPROVAL-REVOKED",
        "C1-H3-DELEGATED-MOMENTUM",
        "C1-H4-STAKEHOLDER-PRESSURE",
        "C1-H5-PARTIAL-CONTINUATION",
    ]

    implementation = manifest["implementation"]
    assert implementation["frozen_evaluator_merge_commit"] == (
        "38d883497f5c9555a0ba21184a0dc51d988ef02a"
    )
    assert implementation["openrouter_adapter_merge_commit"] == (
        "136334164abc40f00b30cccb09eaa4c0b0c334dd"
    )
    assert implementation["batch_runner_merge_commit"] == (
        "76259f13806d9e8a049c18d8400e1595592d06f0"
    )

    assert manifest["publication_rule"]["publish_all_scenarios"] is True
    assert manifest["publication_rule"]["no_cherry_picking"] is True
    assert manifest["retry_policy"]["automatic_retries_at_batch_level"] == 0
    assert manifest["retry_policy"]["selective_reruns_prohibited"] is True
