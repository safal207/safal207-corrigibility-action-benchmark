"""Invalid CLI inputs cannot reserve outputs or reach the Docker boundary."""

import importlib.util
import json
from pathlib import Path
import sys

import pytest

from corrigibility_benchmark import container_shutdown as container


VALID_IMAGE = "shutdown-fixture:test"
VALID_SOURCE = "a" * 40
INVALID_ARGUMENTS = [
    pytest.param(VALID_IMAGE, "not-a-full-commit", id="malformed-source"),
    pytest.param("fixture name:latest", VALID_SOURCE, id="invalid-image"),
    pytest.param("", VALID_SOURCE, id="empty-image"),
]


@pytest.fixture
def cli(monkeypatch):
    def forbidden_docker(*_args, **_kwargs):
        pytest.fail("CLI validation test attempted a Docker operation")

    monkeypatch.setattr(container.subprocess, "run", forbidden_docker)
    path = Path(__file__).resolve().parents[1] / "scripts" / "run_shutdown_container.py"
    spec = importlib.util.spec_from_file_location("shutdown_container_cli_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def arguments(path, *, image=VALID_IMAGE, source=VALID_SOURCE):
    return [
        "run_shutdown_container.py", f"--image={image}", "--out", str(path),
        "--source-commit", source,
    ]


@pytest.mark.parametrize(("image", "source"), INVALID_ARGUMENTS)
def test_invalid_input_leaves_no_artifacts_and_same_path_accepts_corrected_retry(
    cli, monkeypatch, tmp_path, capsys, image, source
):
    path = tmp_path / "new-parent" / "report.json"
    runtime_calls = []

    def successful_runtime(image, **kwargs):
        runtime_calls.append((image, kwargs))
        return {
            "classification": "STILL_RUNNING_AFTER_REQUEST",
            "calibration_passed": True,
            "cleanup": {"removed": True},
        }

    monkeypatch.setattr(cli, "run_container_case", successful_runtime)
    monkeypatch.setattr(sys, "argv", arguments(path, image=image, source=source))
    with pytest.raises(SystemExit) as rejected:
        cli.main()
    assert rejected.value.code == 2
    assert "error:" in capsys.readouterr().err
    assert runtime_calls == []
    assert not path.exists()
    assert not path.parent.exists()
    assert not path.with_suffix(".ownership.json").exists()

    monkeypatch.setattr(sys, "argv", arguments(path))
    assert cli.main() == 0
    assert runtime_calls == [(VALID_IMAGE, {
        "source_commit": VALID_SOURCE,
        "ownership_file": path.with_suffix(".ownership.json"),
    })]
    saved = json.loads(path.read_text())
    assert saved["classification"] == "STILL_RUNNING_AFTER_REQUEST"
    assert saved["calibration_passed"] is True
    assert saved["cleanup"]["removed"] is True
    assert set(saved["host_source_snapshots"]) == {"fixture.py", "Dockerfile"}


def test_existing_report_is_preserved_and_runtime_never_starts(cli, monkeypatch, tmp_path):
    path = tmp_path / "existing.json"
    original = b'{"earlier_attempt":"retain exact bytes"}\n'
    path.write_bytes(original)

    def forbidden_runtime(*_args, **_kwargs):
        pytest.fail("existing output triggered another container attempt")

    monkeypatch.setattr(cli, "run_container_case", forbidden_runtime)
    monkeypatch.setattr(sys, "argv", arguments(path))
    with pytest.raises(FileExistsError):
        cli.main()
    assert path.read_bytes() == original
    assert not path.with_suffix(".ownership.json").exists()


@pytest.mark.parametrize(("image", "source"), INVALID_ARGUMENTS)
def test_invalid_arguments_do_not_replace_existing_evidence(
    cli, monkeypatch, tmp_path, image, source
):
    path = tmp_path / "existing.json"
    original = b'{"prior_evidence":true}\n'
    path.write_bytes(original)

    def forbidden_runtime(*_args, **_kwargs):
        pytest.fail("invalid arguments reached the container runtime")

    monkeypatch.setattr(cli, "run_container_case", forbidden_runtime)
    monkeypatch.setattr(sys, "argv", arguments(path, image=image, source=source))
    with pytest.raises(SystemExit) as rejected:
        cli.main()
    assert rejected.value.code == 2
    assert path.read_bytes() == original
    assert not path.with_suffix(".ownership.json").exists()
