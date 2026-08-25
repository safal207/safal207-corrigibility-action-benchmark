# Corrigibility Action Benchmark

An empirical benchmark for one narrow question:

> **When a human principal corrects an AI agent after work has begun, does the agent preserve the human's ability to regain control — or continue optimizing the stale objective?**

This repository separates two things that are often conflated:

1. **Agent corrigibility behavior** — whether the model notices correction, stops stale work, surfaces conflicts, and seeks fresh authorization.
2. **External containment** — whether a runtime or policy layer blocks a stale or unauthorized consequential action when the model does not self-correct.

A guardrail can contain a failure without making the model corrigible. A model can appear cooperative in dialogue while still attempting a stale consequential action.

## Research question

For a fixed task, compare paired runs:

```text
control run
  agent receives original goal
  -> acts normally

intervention run
  agent receives same original goal
  -> commits to a plan
  -> human changes/corrects/revokes the instruction
  -> observe whether the agent actually changes course
```

The primary evidence unit is a reproducible paired trace.

## Intervention families

1. Human correction after commitment
2. Authority revocation after delegation
3. Approval mutation after approval
4. Unsupported-success pressure
5. Correction across crash/recovery

See `SCENARIOS.md`.

## Metrics

- correction compliance rate
- stale-action continuation rate
- fresh-approval seeking rate
- unsupported-success rate
- reproducible counterexample count

No single composite “corrigibility score” is used.

## Evidence layers

### Model behavior

Did the agent itself acknowledge the new instruction, stop the old plan, avoid stale action attempts, request new approval when required, and refuse unsupported success claims?

### Runtime backstop

If the model failed, was the stale action blocked, was the reason machine-checkable, and can an independent reviewer reconstruct the failure?

The benchmark reports both layers separately.

## Seed evidence

Two real infrastructure reviews motivate the test families, but they are **not counted as model-level corrigibility results**.

- CoSAI external review -> executable negative fixtures -> RED -> narrow fixes -> GREEN -> merged: https://github.com/safal207/LS/pull/960
- crewAI GuardrailProvider review -> author confirmed evidence-binding gaps -> implementation changed: https://github.com/crewAIInc/crewAI/pull/7095

## First milestone

Produce one real model-level counterexample with paired control/intervention runs, an explicit human correction after plan commitment, raw normalized trace, deterministic classification, and runs with/without external containment.

A useful first result could be either:

```text
FAIL:
agent verbally accepts correction but still attempts the stale action
```

or:

```text
NEGATIVE RESULT:
across N pre-registered runs, no stale-action continuation was observed
```

Both are informative if the protocol is fixed in advance.

## Non-claims

This project does **not** claim:

- runtime authorization is equivalent to corrigibility;
- blocked effects prove the model accepted correction;
- one model/configuration generalizes to all frontier systems;
- trace integrity proves semantic truth;
- a small benchmark measures every aspect of corrigibility.

## Related components

- **T-Trace** — optional evidence/trace-format layer: https://github.com/safal207/T-Trace
- **LS Agent Trust Runtime** — reference external-containment implementation: https://github.com/safal207/LS/tree/main/prototypes/openai-agent-trust-runtime

## Status

**Research seed. No model-level benchmark result is claimed yet.**
