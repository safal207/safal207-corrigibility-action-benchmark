import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def test_preregistration_manifests_are_valid_and_pinned():
    manifests = sorted((ROOT / "preregistrations").glob("*.json"))
    assert manifests, "at least one preregistration manifest is required"

    for path in manifests:
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data.get("preregistration_id") or data.get("batch_id")
        assert data["provider"]["model_slug"]

        implementation = data["implementation"]
        merge_pins = {
            key: value
            for key, value in implementation.items()
            if key.endswith("_merge_commit")
        }
        assert merge_pins, f"{path.name} must pin at least one merged implementation"
        assert all(
            isinstance(value, str) and SHA_RE.fullmatch(value)
            for value in merge_pins.values()
        )

        assert data["classification_contract"]["allowed_labels"]
        publication = data["publication_rule"]
        outcome_freeze = publication.get(
            "no_outcome_based_evaluator_changes",
            publication.get("no_outcome_based_classifier_changes"),
        )
        assert outcome_freeze is True
        assert publication["no_cherry_picking"] is True
