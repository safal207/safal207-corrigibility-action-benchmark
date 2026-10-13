"""Validate that mutation infrastructure cannot count broken execution as detection."""

from copy import deepcopy
import importlib.util
from pathlib import Path
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_shutdown_observer_mutations.py"
SPEC = importlib.util.spec_from_file_location("shutdown_mutations", SCRIPT)
mutations = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mutations
SPEC.loader.exec_module(mutations)


def evidence(*, failed=False, kind="assertion"):
    node = "tests/test_shutdown_observer.py::test_observation"
    return {
        "collected": [node], "exitstatus": 1 if failed else 0, "collection_errors": [],
        "reports": [
            {"nodeid": node, "when": phase,
             "outcome": "failed" if failed and phase == "call" else "passed",
             "failure_kind": kind if failed and phase == "call" else None,
             "xfail": False}
            for phase in ("setup", "call", "teardown")
        ],
    }


def test_only_completed_assertion_failures_count_as_killed():
    facts = evidence(failed=True)
    assert mutations.classify_run(1, facts, facts["collected"]) == "KILLED"
    facts = evidence()
    assert mutations.classify_run(0, facts, facts["collected"]) == "PASSED"
    exception = evidence(failed=True, kind="exception")
    assert mutations.classify_run(1, exception, exception["collected"]) == "ERROR"


@pytest.mark.parametrize("phase", ["setup", "teardown"])
def test_fixture_errors_never_count_as_killed(phase):
    facts = evidence(failed=True)
    next(r for r in facts["reports"] if r["when"] == phase)["outcome"] = "failed"
    assert mutations.classify_run(1, facts, facts["collected"]) == "ERROR"


@pytest.mark.parametrize("corruption", ["skip", "xfail", "missing_phase", "duplicate_phase",
                                       "collection_error", "wrong_exit", "missing_call"])
def test_partial_or_changed_test_execution_is_inconclusive(corruption):
    facts = evidence(failed=True)
    if corruption == "skip":
        facts["reports"][1]["outcome"] = "skipped"
    elif corruption == "xfail":
        facts["reports"][1]["xfail"] = True
    elif corruption == "missing_phase":
        facts["reports"].pop()
    elif corruption == "duplicate_phase":
        facts["reports"].append(deepcopy(facts["reports"][-1]))
    elif corruption == "collection_error":
        facts["collection_errors"] = ["import failed"]
    elif corruption == "wrong_exit":
        facts["exitstatus"] = 3
    elif corruption == "missing_call":
        facts["reports"].pop(1)
    assert mutations.classify_run(1, facts, facts["collected"]) == "ERROR"


def test_collected_tests_must_match_the_frozen_baseline():
    facts = evidence(failed=True)
    assert mutations.classify_run(1, facts, ["different_test"]) == "ERROR"
    facts["collected"] = []
    assert mutations.classify_run(1, facts, []) == "ERROR"


def test_source_patch_requires_one_unique_anchor_and_valid_python():
    change = mutations.Mutation("test", "test", "x = 1", "x = 2")
    assert mutations.apply_mutation("x = 1\n", change) == "x = 2\n"
    for source in ("x = 0\n", "x = 1\nx = 1\n"):
        with pytest.raises(ValueError, match="exactly one source anchor"):
            mutations.apply_mutation(source, change)
    broken = mutations.Mutation("test", "test", "x = 1", "x = (")
    with pytest.raises(SyntaxError):
        mutations.apply_mutation("x = 1\n", broken)


@pytest.mark.parametrize("partial", [b'{"collected": [', b"\xff", b"[]", b""])
def test_interrupted_or_invalid_probe_is_an_error_record(partial):
    facts, error = mutations.decode_probe(partial)
    assert facts == {}
    assert error
    assert mutations.classify_run(1, facts, ["test_observation"]) == "ERROR"


def test_campaign_requires_controls_and_every_selected_mutation_detected():
    results = [
        {"name": "BASELINE", "status": "PASSED"},
        {"name": "C_NOOP", "status": "PASSED"},
        {"name": "C_MUSTKILL", "status": "KILLED"},
        *[{"name": mutation.name, "status": "KILLED"} for mutation in mutations.MUTATIONS],
    ]
    assert mutations.campaign_passed(results)
    for index, status in [(1, "KILLED"), (2, "PASSED"), (3, "SURVIVED"),
                          (3, "ERROR"), (3, "TIMEOUT")]:
        changed = deepcopy(results)
        changed[index]["status"] = status
        assert not mutations.campaign_passed(changed)
    assert not mutations.campaign_passed(results[:-1])
