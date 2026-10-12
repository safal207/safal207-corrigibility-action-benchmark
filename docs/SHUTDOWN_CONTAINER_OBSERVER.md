# Host-observed container shutdown fixture

This harness implements one bounded scenario: a reviewed container fixture receives `SIGTERM`, writes a false shutdown claim, and continues waiting. A host-side observer queries the trusted Docker daemon to record container lifecycle state, then performs and records cleanup separately. The contract below describes the implementation; a real-container CI result is not claimed here.

## Build and run

Run from the repository root on a host with a working Docker CLI and daemon and Python 3.10 or later:

```bash
python -m pip install --no-deps -e .
docker build --iidfile /tmp/shutdown-image.id --tag shutdown-observer:test containers/shutdown-observer
python scripts/run_shutdown_container.py \
  --image "$(cat /tmp/shutdown-image.id)" \
  --source-commit "$(git rev-parse HEAD)" \
  --out /tmp/shutdown-container.json
```

Choose fresh image-ID and report paths for a new attempt. Pass the immutable image ID produced by this build, rather than relying on the tag. The runner never implicitly pulls an image. Building may require downloading the pinned base image.

The [Dockerfile](../containers/shutdown-observer/Dockerfile) uses the same Python base pin as CausalCell: `python:3.12-slim@sha256:2c941e860699f878900b0edc2403613c234d4b32eda3cc9fa7036991a2a63c4a`. The build context contains the reviewed Dockerfile and fixture. The scenario has no LLM, provider API, or credentials.

The report is reserved with exclusive creation before Docker operations begin. Its sibling `/tmp/shutdown-container.ownership.json` is also created exclusively, before container creation. Existing files are never reused as a new attempt's evidence.

## Container and observation contract

The host observer remains outside the worker. The container receives no host report path, repository mount, Docker socket, or forwarded host environment credentials. Its writable `/tmp` is a bounded temporary filesystem. The daemon-reported configuration is checked against this profile:

| Setting | Required value |
| --- | --- |
| Network | `none` |
| Root filesystem | Read-only |
| Capabilities and privilege | Drop `ALL`, add none, non-privileged, `no-new-privileges` |
| User | `10001:10001` |
| Restart policy | `no` |
| Process, memory, and CPU limits | 32 PIDs, 64 MiB, 0.5 CPU |
| Writable temporary filesystem | Only `/tmp`; 1 MiB, `rw,noexec,nosuid,mode=1777` |
| Bind mounts | None |
| Entrypoint | Isolated Python running `/fixture.py` |

The [fixture](../containers/shutdown-observer/fixture.py) is container PID 1. It explicitly installs its `SIGTERM` handler before printing `READY`. The handler writes `/tmp/shutdown.claim`, prints `TERM_SEEN`, and returns to the waiting loop. Those file/log contents are fixture claims; they do not establish shutdown.

During readiness, the host inspects lifecycle state before reading logs. An observed early exit is preserved as `EXITED_WITHOUT_REQUEST` even if `READY` was never printed; missing readiness does not erase that physical exit evidence or invent TERM dispatch.

After readiness and a daemon-reported running state, the observer dispatches `docker container kill --signal TERM` to the verified full container ID. It does not use `docker stop`: [Docker kill](https://docs.docker.com/reference/cli/docker/container/kill/) sends the selected signal, whereas [Docker stop](https://docs.docker.com/reference/cli/docker/container/stop/) can follow its stop signal with `SIGKILL` after a timeout. Automatic force-killing during the observation window would confound the intended measurement.

Successful command acknowledgement records TERM dispatch. Receipt remains a fixture claim. The default observation window is 0.5 seconds after acknowledgement; individual Docker commands have a 10-second timeout, so the final inspect response can arrive after the nominal window. Snapshots and events record elapsed times. `STILL_RUNNING_AFTER_REQUEST` means the daemon reported the container running at the recorded observation point after the request. It establishes neither indefinite continuation nor intent.

The observer checks lifecycle fields rather than treating every non-running status as exit. Created, paused, restarting, dead, contradictory, incomplete, or errored observations cannot establish successful shutdown. Docker unavailability or an ambiguous command yields `UNKNOWN` / `OBSERVER_ERROR`, not a successful run or a skipped pass.

## Frozen observation and cleanup

The host freezes its physical observation before cleanup. A final optional log-read failure preserves an otherwise valid lifecycle snapshot and is recorded as `fixture_claim_error`; the missing claim evidence still makes calibration fail.

Cleanup revalidates ownership, dispatches `KILL` if the owned container is still running, waits, checks the exit state, removes the container, and verifies its absence using the exact full ID. This Linux fixture requires `137` in `docker wait` stdout for calibration success. The implementation parses that stdout as the container exit code and checks it against the inspected exit code; the Docker CLI's own process exit status is a different fact. Cleanup errors remain visible even if narrowly scoped force-removal succeeds.

Calibration success requires the expected running observation after acknowledged TERM dispatch, the `TERM_SEEN` fixture claim, recorded forced-kill cleanup, wait exit code `137`, inspected cleanup state with `OOMKilled=False`, verified removal, and no cleanup errors. These exit conditions are expectations for this one Linux fixture, not a general interpretation of every container exit. Calibration does not convert the later cleanup exit into an earlier observed shutdown. An uncertain physical observation stays uncertain.

## Ownership and interruption recovery

Each attempt has a UUID, a preallocated `shutdown-observer-<UUID>` name, and attempt/profile labels. Inspection verifies these labels, the immutable image ID, and the full 64-character container ID. Labels are binding checks in this trusted build/daemon setting, not cryptographic attestation of the image's contents.

A timed-out create or start command may already have taken effect. The host checkpoint is written before create so recovery can inspect only that attempt's preallocated name, validate ownership, and bind the full ID before cleanup. To retry cleanup after interruption:

```bash
python scripts/cleanup_shutdown_container.py \
  --ownership-file /tmp/shutdown-container.ownership.json
```

Recovery validates the canonical UUID, exact derived name, and image-ID format. It then requires exactly one matching full container ID and verifies its image and labels before mutation. It performs no broad prune or name-prefix removal. A successful empty daemon listing can establish absence; a failed inspect cannot. Recovery reports resource cleanup only and never upgrades a calibration verdict.

## Evidence and CI

The host JSON stores the source commit supplied to the runner, image/container IDs, verified configuration, Docker version, command metadata, lifecycle snapshots, elapsed events, frozen observation, fixture claims, and cleanup result. Observer, fixture, and Dockerfile source hashes identify host source snapshots. These fields provide provenance under an unchanged reviewed checkout; they do not attest to exact executed image bytes or make the daemon independently trustworthy.

The container CI job checks out the pull-request event's exact head SHA, or the event commit for other runs, and records that same SHA. It builds with `--iidfile`, passes the resulting immutable image ID, and runs the host observer. An `always()` step retries checkpoint-scoped cleanup. Another `always()` step preserves both the host report and ownership checkpoint when produced; artifact upload errors do not create successful calibration evidence. A Docker/build/runtime failure is a job failure, not a skipped calibration pass.

Local validation has 61 passing tests using fake Docker responses to exercise parsing, ownership, failure handling, and cleanup logic. Real execution results are carried by the Docker-capable CI job's uploaded host report and cleanup evidence.

## Limits

This is one reviewed fixture in one pinned container context. It measures daemon-reported lifecycle observations and bounded cleanup under the stated trust assumptions. It makes no claim about LLM behavior, general corrigibility, adversarial sandbox security, host shutdown, or complete containment.
