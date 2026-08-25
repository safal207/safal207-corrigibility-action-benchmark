import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_preregistration_manifests_are_valid_and_pinned():
    manifests = sorted((ROOT / "preregistrations").glob("*.json"))
    assert manifests, "at least one preregistration manifest is required"

    for path in manifests:
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data.get("preregistration_id") or data.get("batch_id")
        assert data["provider"]["model_slug"]
        assert data["implementation"]["frozen_evaluator_merge_commit"]
        assert data["classification_contract"]["allowed_labels"]
        assert data["publication_rule"]["no_outcome_based_evaluator_changes"] is True
        assert data["publication_rule"]["no_cherry_picking"] is True
