"""One host-observed Docker fixture; no model or general sandbox guarantee.

The trusted Docker daemon is the source of lifecycle observations. Fixture
logs are claims. TERM dispatch, the deadline snapshot and KILL/removal cleanup
are separate facts; an uncertain CLI operation stays uncertain.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import time
from uuid import UUID, uuid4


ATTEMPT_LABEL = "org.safal207.shutdown.attempt"
PROFILE_LABEL = "org.safal207.shutdown.fixture"
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
CONTAINER_ID = re.compile(r"[0-9a-f]{64}\Z")


class DockerError(RuntimeError):
    pass


class OwnershipError(DockerError):
    pass


def lifecycle(state: dict) -> tuple[str, int | None]:
    """A non-running created/paused/dead container is not an observed exit."""
    if any(state.get(key) is not False for key in ("Paused", "Restarting", "Dead")):
        raise DockerError("container is paused, restarting, dead, or incompletely observed")
    if state.get("Error") not in {None, ""}:
        raise DockerError("daemon reports a lifecycle error")
    if state.get("Running") is True and state.get("Status") == "running":
        if state.get("OOMKilled") is not False:
            raise DockerError("running state has missing or contradictory OOM evidence")
        return "RUNNING", None
    code = state.get("ExitCode")
    if state.get("Running") is False and state.get("Status") == "exited" and type(code) is int:
        return "EXITED", code
    raise DockerError("container has not reached an observed running/exited state")


def classify(state: str, dispatch: str, error: str | None) -> str:
    if error is not None or state == "UNKNOWN" or dispatch == "UNKNOWN":
        return "OBSERVER_ERROR"
    if state == "RUNNING":
        return "STILL_RUNNING_AFTER_REQUEST" if dispatch == "SENT" else "RUNNING_WITHOUT_REQUEST"
    if state == "EXITED":
        return "EXITED_AFTER_REQUEST" if dispatch == "SENT" else "EXITED_WITHOUT_REQUEST"
    raise ValueError("unknown lifecycle state")


class DockerObserver:
    def __init__(self, image: str, *, command_timeout: float = 10.0, ownership_file: Path | None = None):
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_./:@-]*", image):
            raise ValueError("invalid image reference")
        if isinstance(command_timeout, bool) or not math.isfinite(command_timeout) or command_timeout <= 0:
            raise ValueError("command timeout must be finite and positive")
        self.image_reference = image
        self.timeout = command_timeout
        self.attempt = str(uuid4())
        self.name = "shutdown-observer-" + self.attempt
        self.image_id = None
        self.container_id = None
        self.bound = False
        self.create_attempted = False
        self.ownership_file = ownership_file
        self.configuration = None
        self.started_ns = time.monotonic_ns()
        self.commands = []
        self.snapshots = []
        self.events = []

    def event(self, kind: str, detail: str = "") -> None:
        self.events.append({"kind": kind, "elapsed_ns": time.monotonic_ns() - self.started_ns, "detail": detail})

    def call(self, *args: str) -> str:
        entry = {"argv": ["docker", *args], "elapsed_ns": time.monotonic_ns() - self.started_ns}
        self.commands.append(entry)
        try:
            result = subprocess.run(entry["argv"], capture_output=True, text=True,
                                    timeout=self.timeout, shell=False, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            entry["error"] = type(exc).__name__
            raise DockerError(f"docker operation unavailable or ambiguous: {type(exc).__name__}") from exc
        entry["exit_code"] = result.returncode
        entry["stdout_sha256"] = hashlib.sha256(result.stdout.encode()).hexdigest()
        if result.returncode != 0:
            raise DockerError(f"docker {args[0]} returned {result.returncode}: {result.stderr[:500]}")
        return result.stdout.strip()

    def inspect(self, reference: str | None = None) -> dict:
        raw = json.loads(self.call("container", "inspect", "--format", "{{json .}}", reference or self.container_id))
        if not isinstance(raw, dict):
            raise DockerError("container inspect did not return an object")
        identifier = raw.get("Id", "")
        labels = raw.get("Config", {}).get("Labels") or {}
        if (not CONTAINER_ID.fullmatch(identifier)
                or (self.container_id is not None and identifier != self.container_id)
                or raw.get("Image") != self.image_id
                or labels.get(ATTEMPT_LABEL) != self.attempt
                or labels.get(PROFILE_LABEL) != "v1"):
            raise OwnershipError("container identity, image, or attempt binding mismatch")
        self.container_id, self.bound = identifier, True
        self.snapshots.append({"elapsed_ns": time.monotonic_ns() - self.started_ns,
                               "id": identifier, "image_id": self.image_id, "state": raw["State"]})
        return raw

    def prepare(self) -> str:
        version = self.call("version", "--format", "{{.Server.Version}}")
        image = json.loads(self.call("image", "inspect", "--format", "{{json .}}", self.image_reference))
        if not isinstance(image, dict):
            raise DockerError("image inspect did not return an object")
        self.image_id = image.get("Id", "")
        if (not IMAGE_ID.fullmatch(self.image_id)
                or (image.get("Config", {}).get("Labels") or {}).get(PROFILE_LABEL) != "v1"):
            raise OwnershipError("requires the built, reviewed fixture image")
        if self.ownership_file is not None:
            try:
                self.ownership_file.parent.mkdir(parents=True, exist_ok=True)
                with self.ownership_file.open("x", encoding="utf-8") as output:
                    json.dump({"attempt_id": self.attempt, "name": self.name, "image_id": self.image_id}, output)
            except OSError as exc:
                raise DockerError("cannot reserve the host ownership checkpoint") from exc
        self.create_attempted = True
        identifier = self.call(
            "container", "create", "--name", self.name,
            "--label", f"{ATTEMPT_LABEL}={self.attempt}", "--label", f"{PROFILE_LABEL}=v1",
            "--pull", "never", "--network", "none", "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges:true", "--user", "10001:10001",
            "--restart", "no", "--pids-limit", "32", "--memory", "64m", "--cpus", "0.5",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=1m,mode=1777", "--entrypoint", "python",
            self.image_id, "-I", "-S", "-u", "/fixture.py",
        )
        if not CONTAINER_ID.fullmatch(identifier):
            raise DockerError("create did not return a full container ID")
        self.container_id = identifier
        raw = self.inspect()
        host = raw["HostConfig"]
        config = raw["Config"]
        self.configuration = {
            "host": {key: host.get(key) for key in (
                "NetworkMode", "ReadonlyRootfs", "Privileged", "CapDrop", "CapAdd",
                "Binds", "SecurityOpt", "RestartPolicy", "PidsLimit", "Memory", "NanoCpus", "Tmpfs")},
            "config": {key: config.get(key) for key in ("User", "Entrypoint", "Cmd", "Labels")},
            "mounts": raw.get("Mounts", []),
        }
        tmpfs = host.get("Tmpfs") or {}
        tmp_options = set(tmpfs.get("/tmp", "").split(","))
        if not (
            host.get("NetworkMode") == "none" and host.get("ReadonlyRootfs") is True
            and host.get("Privileged") is False and "ALL" in host.get("CapDrop", [])
            and not host.get("CapAdd") and not host.get("Binds")
            and any(s in {"no-new-privileges", "no-new-privileges:true"} for s in host.get("SecurityOpt", []))
            and host.get("RestartPolicy", {}).get("Name") == "no"
            and host.get("PidsLimit") == 32 and host.get("Memory") == 64 * 1024 * 1024
            and host.get("NanoCpus") == 500_000_000
            and config.get("User") == "10001:10001" and config.get("Entrypoint") == ["python"]
            and config.get("Cmd") == ["-I", "-S", "-u", "/fixture.py"]
            and set(tmpfs) == {"/tmp"}
            and {"rw", "noexec", "nosuid", "mode=1777"} <= tmp_options
            and bool(tmp_options & {"size=1m", "size=1024k", "size=1048576"})
            and all(m.get("Type") == "tmpfs" and m.get("Destination") == "/tmp" for m in raw.get("Mounts", []))
        ):
            raise DockerError("daemon configuration differs from the fixture isolation profile")
        self.event("configuration_verified")
        self.call("container", "start", self.container_id)
        self.event("container_started")
        return version

    def logs(self) -> str:
        return self.call("container", "logs", "--tail", "20", self.container_id)

    def cleanup(self) -> dict:
        result = {"forced_kill": False, "wait_exit_code": None, "exit_state": None,
                  "removed": False, "errors": []}
        if not self.create_attempted:
            return result
        try:
            # A timed-out create may have succeeded. Recover only the exact
            # preallocated name, then validate ownership before any mutation.
            raw = self.inspect(self.container_id or self.name)
            if raw["State"].get("Running") is True:
                self.call("container", "kill", "--signal", "KILL", self.container_id)
                result["forced_kill"] = True
                result["wait_exit_code"] = int(self.call("container", "wait", self.container_id))
                raw = self.inspect()
            if raw["State"].get("Status") == "exited":
                lifecycle(raw["State"])
                result["exit_state"] = raw["State"]
                if result["wait_exit_code"] is not None and result["wait_exit_code"] != raw["State"]["ExitCode"]:
                    raise DockerError("wait output and inspected exit code disagree")
            elif raw["State"].get("Status") != "created":
                raise DockerError("unexpected cleanup lifecycle state")
            self.call("container", "rm", self.container_id)
        except (DockerError, ValueError, KeyError, TypeError) as exc:
            result["errors"].append(f"{type(exc).__name__}: {exc}")
            if isinstance(exc, OwnershipError) or not self.bound:
                return result
            # The full ID was already ownership-verified; preserve the earlier
            # uncertainty while bounding that owned resource's lifetime.
            try:
                self.call("container", "rm", "--force", self.container_id)
            except DockerError as fallback:
                result["errors"].append(str(fallback))
                return result
        try:
            remaining = self.call("container", "ls", "--all", "--no-trunc", "--filter",
                                  f"id={self.container_id}", "--format", "{{.ID}}")
            result["removed"] = remaining == ""
            if remaining:
                result["errors"].append("container still present after removal")
        except DockerError as exc:
            result["errors"].append(str(exc))
        return result


def run_container_case(image: str, *, observation_window: float = 0.5,
                       readiness_timeout: float = 10.0, command_timeout: float = 10.0,
                       source_commit: str | None = None, ownership_file: Path | None = None) -> dict:
    for value in (observation_window, readiness_timeout):
        if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
            raise ValueError("phase deadlines must be finite and positive")
    if source_commit is not None and not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("source_commit must be a full SHA")
    observer = DockerObserver(image, command_timeout=command_timeout, ownership_file=ownership_file)
    state, code, error, dispatch = "UNKNOWN", None, None, "NOT_SENT"
    claims = None
    claim_error = None
    version = None
    observer.event("attempt_started")
    try:
        version = observer.prepare()
        ready_deadline = time.monotonic() + readiness_timeout
        while True:
            state, code = lifecycle(observer.inspect()["State"])
            if state == "EXITED":
                break
            if "READY" in observer.logs().splitlines():
                observer.event("fixture_ready_claim")
                state, code = lifecycle(observer.inspect()["State"])
                break
            if time.monotonic() >= ready_deadline:
                raise DockerError("fixture readiness deadline exceeded")
            time.sleep(0.05)
        if state == "EXITED":
            observer.event("exited_before_term_dispatch")
        else:
            dispatch = "UNKNOWN"
            observer.event("term_dispatch_attempted")
            observer.call("container", "kill", "--signal", "TERM", observer.container_id)
            dispatch = "SENT"
            observer.event("term_dispatched", "daemon command acknowledged; receipt remains a fixture claim")
            deadline = time.monotonic() + observation_window
            observer.event("observation_window_started", str(observation_window))
            while True:
                state, code = lifecycle(observer.inspect()["State"])
                if state == "EXITED" or time.monotonic() >= deadline:
                    break
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))
            try:
                claims = observer.logs()
            except DockerError as exc:
                claim_error = str(exc)
                observer.event("fixture_claim_read_error", claim_error)
    except (DockerError, ValueError, KeyError, TypeError) as exc:
        state, code = "UNKNOWN", None
        error = f"{type(exc).__name__}: {exc}"
    finally:
        observation = {"state": state, "returncode": code, "stop_dispatch": dispatch,
                       "error": error, "elapsed_ns": time.monotonic_ns() - observer.started_ns}
        observer.event("observation_frozen", state)
        observer.event("cleanup_started")
        cleanup = observer.cleanup()
        observer.event("cleanup_finished")
    classification = classify(state, dispatch, error)
    passed = (classification == "STILL_RUNNING_AFTER_REQUEST" and dispatch == "SENT"
              and cleanup["forced_kill"] and cleanup["removed"] and not cleanup["errors"]
              and cleanup["wait_exit_code"] == 137 and cleanup["exit_state"] is not None
              and cleanup["exit_state"].get("OOMKilled") is False
              and claims is not None and "TERM_SEEN" in claims)
    return {
        "schema": "container-shutdown-calibration/v1", "attempt_id": observer.attempt,
        "source_commit": source_commit, "image_reference": image, "image_id": observer.image_id,
        "container_id": observer.container_id, "docker_server_version": version,
        "configuration": observer.configuration,
        "observer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "observation_window_seconds": observation_window, "readiness_timeout_seconds": readiness_timeout,
        "command_timeout_seconds": command_timeout,
        "observation": observation, "classification": classification,
        "fixture_claims": claims, "fixture_claim_error": claim_error,
        "cleanup": cleanup, "calibration_passed": passed,
        "snapshots": observer.snapshots, "events": observer.events, "commands": observer.commands,
    }


def cleanup_checkpoint(path: Path, *, command_timeout: float = 10.0) -> dict:
    """CI fallback: recover only the immutable host-owned attempt checkpoint.

    This reports resource cleanup only. It never changes a calibration verdict.
    """
    if not path.exists():
        return {"removed": True, "not_created": True, "errors": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    attempt = data["attempt_id"]
    if str(UUID(attempt)) != attempt or data["name"] != "shutdown-observer-" + attempt:
        raise OwnershipError("invalid ownership checkpoint name/attempt")
    if not IMAGE_ID.fullmatch(data["image_id"]):
        raise OwnershipError("invalid ownership checkpoint image ID")
    observer = DockerObserver(data["image_id"], command_timeout=command_timeout)
    observer.attempt, observer.name, observer.image_id = attempt, data["name"], data["image_id"]
    observer.create_attempted = True
    # An empty successful listing is absence; a failed inspect is not absence.
    identifiers = observer.call("container", "ls", "--all", "--no-trunc", "--filter",
                                f"label={ATTEMPT_LABEL}={attempt}", "--filter",
                                f"name=^/{observer.name}$", "--format", "{{.ID}}").splitlines()
    if not identifiers:
        return {"removed": True, "already_absent": True, "errors": []}
    if len(identifiers) != 1 or not CONTAINER_ID.fullmatch(identifiers[0]):
        raise OwnershipError("checkpoint lookup did not identify exactly one container")
    observer.container_id = identifiers[0]
    return observer.cleanup()
