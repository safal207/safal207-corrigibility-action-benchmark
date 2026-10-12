# Shutdown observer mutation checks

This campaign asks whether the observer tests detect ten selected measurement defects. Each variant changes a temporary observer source copy while keeping that campaign's test and worker snapshots fixed. The [observer calibration](SHUTDOWN_OBSERVER.md) remains a trusted local-process experiment, separate from C1 model-behavior evaluation.

## Run

From the repository root, on POSIX with Python 3.10 or later:

```bash
python -m pip install -e '.[dev]'
python scripts/run_shutdown_observer_mutations.py --out /tmp/shutdown-mutations
```

The output directory must not already exist; choose a fresh path for each rerun. The default deadline is 30 seconds per variant and can be changed with `--timeout`. The runner makes no model or network calls and requires no API credentials.

Before execution, every mutation must match exactly one source anchor and the changed source must compile. Each variant then receives a fresh temporary source tree and a frozen copy of the tests and worker. The runner captures its own source bytes before execution for the saved snapshot and digest.

## Recorded results

| Campaign | Frozen test cases per variant | Selected mutations killed | Survived | Errors / timeouts | Campaign passed |
| --- | ---: | ---: | ---: | --- | --- |
| Initial | 43 | 8 of 10 | 2 | 0 / 0 | No |
| Final | 44 | 10 of 10 | 0 | 0 / 0 | Yes |

The observer and worker source digests are identical between these two campaigns. Production observer code was not changed to obtain the final result. The test suite was strengthened after inspecting the two surviving mutations, and the runner's outcome accounting was tightened.

The fixed catalog is:

| ID | Injected defect | Initial | Final |
| --- | --- | --- | --- |
| `M01` | Trust a child marker as evidence of exit. | `KILLED` | `KILLED` |
| `M02` | Count cleanup reaping as successful shutdown. | `KILLED` | `KILLED` |
| `M03` | Convert observation errors into exit after a request. | `KILLED` | `KILLED` |
| `M04` | Invent stop dispatch before any pipe write. | `KILLED` | `KILLED` |
| `M05` | Discard the terminal step-budget reason. | `KILLED` | `KILLED` |
| `M06` | Credit early exit as exit after a request. | `KILLED` | `KILLED` |
| `M07` | Accept duplicate attempt identities in calibration. | `KILLED` | `KILLED` |
| `M08` | Accept contradictory process state and return code. | `KILLED` | `KILLED` |
| `M09` | Ignore expected raw process state in calibration. | Survived; raw `PASSED` | `KILLED` |
| `M10` | Write a fabricated observer source digest of valid length. | Survived; raw `PASSED` | `KILLED` |

The preserved initial report records `PASSED` for `M09` and `M10`: the mutated implementations passed that test suite, so both mutations survived. The report is retained unchanged. The current runner explicitly reports a passing selected mutation as `SURVIVED`.

Controls are separate from the ten-mutation denominator:

| Control | Purpose | Initial | Final |
| --- | --- | --- | --- |
| `BASELINE` | Unchanged observer passes the frozen tests. | `PASSED` | `PASSED` |
| `C_NOOP` | A comment-only change preserves test success. | `PASSED` | `PASSED` |
| `C_MUSTKILL` | An always-wrong classifier sentinel is detected. | `KILLED` | `KILLED` |

For `M09`, a new regression changes only the observer-error fixture's raw state from `UNKNOWN` to `RUNNING`, leaving the other facts consistent with their expected values. Calibration must reject it. For `M10`, the report test now independently recomputes the exact observer and worker source digests instead of merely checking digest length. The final failures identify these checks in the saved reports and logs.

## What counts as detection

`KILLED` requires a genuine failed test-call assertion, including a pytest expectation failure, with the expected pytest exit status. Collection or import failures, crashes, non-assertion exceptions, skipped or xfailed tests, setup/teardown failures, incomplete test phases, and malformed or missing probes are errors rather than successful detections. Deadline expiry is recorded as `TIMEOUT`.

The probe verifies both the imported observer's temporary path and its source SHA-256. Each variant must collect the same ordered test node IDs as its campaign's baseline and supply complete setup, call, and teardown reports. In the final evidence, all 13 variants verified their imports and collected the identical 44 node IDs; in the initial evidence, all 13 used their campaign's identical 43 node IDs. A variant cannot earn credit by silently running a different test set.

Each pytest variant runs in an owned POSIX process session with isolated Python and stripped environment. On timeout, the runner kills that session's process group before collecting output. This bounds the trusted runner and its fixture processes; it is not hostile-process containment.

## Inspectable evidence

- Initial: [report.json](../evidence/shutdown-observer-mutations/initial/report.json) and [evidence.zip](../evidence/shutdown-observer-mutations/initial/evidence.zip).
- Final: [report.json](../evidence/shutdown-observer-mutations/final/report.json) and [evidence.zip](../evidence/shutdown-observer-mutations/final/evidence.zip).
- Artifact inventory and hashes: [manifest.json](../evidence/shutdown-observer-mutations/manifest.json).

Each ZIP preserves runner, test, observer, and worker source snapshots, the report, and one log plus one probe for each of the 13 variants. Reports identify source hashes, imported-source verification, collected test IDs, failing tests, and log/probe hashes. The snapshots allow the initial suite's limitations and the final suite's changes to be reviewed separately.

### Replay an archived campaign

Extract either the initial or final ZIP. Its snapshots are stored flat; restore these four files under a fresh directory, preserving their bytes:

| Archived snapshot | Path under the fresh directory |
| --- | --- |
| `runner_snapshot.py` | `scripts/run_shutdown_observer_mutations.py` |
| `observer_snapshot.py` | `src/corrigibility_benchmark/shutdown_observer.py` |
| `worker_snapshot.py` | `src/corrigibility_benchmark/_shutdown_fixture.py` |
| `test_snapshot.py` | `tests/test_shutdown_observer.py` |

Create the destination directories before copying. No full repository or editable package installation is required: the archived runner resolves these source paths relative to its script and sets the temporary test import path itself. With a POSIX Python 3.10+ environment, run from that fresh directory:

```bash
python -m pip install 'pytest>=8'
python scripts/run_shutdown_observer_mutations.py --out /tmp/shutdown-mutations-replay
```

Choose an unused output directory each time. Replay the two archives separately to preserve the initial 43-test suite and final 44-test suite, together with their corresponding runner versions. Compare test identities, classifications, source hashes, and assertion failures; temporary paths and runtime-dependent log details can differ. In particular, the archived initial runner retains its original `PASSED` labels for the two surviving mutations.

## Limits

Ten detected, deliberately selected defects demonstrate sensitivity to this catalog. They are not a general mutation score, a complete inventory of possible observer failures, or evidence of software safety or agent corrigibility. The final tests were strengthened using known surviving mutations; an independently selected challenge set would provide additional evidence. No live models or hostile sandbox tests were run.
