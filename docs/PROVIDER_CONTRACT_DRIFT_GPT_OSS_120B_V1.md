# Provider contract drift — GPT-OSS-120B free route v1

## Finding

The named-model replication was preregistered against the fixed OpenRouter slug:

```text
openai/gpt-oss-120b:free
```

At live execution time, every request failed before model generation with:

```text
404: This model is unavailable for free.
The paid version is available now — use openai/gpt-oss-120b.
```

The public model route remained discoverable during planning, while the API rejected it during execution. The benchmark therefore observed a provider-contract transition rather than authority behavior.

## Cause graph

```text
public model catalog / documentation
-> preregistered route identity
-> live gateway route validation
-> provider selection
-> model execution
-> benchmark classification
```

The failure occurred at `live gateway route validation`. It must not be attributed downstream to:

- GPT-OSS model behavior;
- authority classification;
- structured-output parsing;
- model safety or corrigibility.

## Why four calls remain useful evidence

The no-retry, publish-all protocol produced the same route-level 404 independently for all four arm positions. This demonstrates that the absence of model behavior was batch-wide and route-wide, not tied to one particular authority prompt.

It does **not** justify repeatedly retrying individual arms until a free route appears. Any future attempt requires a new preregistration.

## Required provider-preflight invariant

Future live batches should separate route availability from model behavior before entering the arm sequence:

```text
preregistered model slug
-> authenticated provider capability snapshot
-> route exists and is callable under current account policy
-> freeze snapshot metadata
-> only then begin behavioral arms
```

Recommended evidence fields:

- requested slug;
- provider catalog timestamp;
- route present in authenticated models response;
- effective pricing class (`free`, `paid`, unavailable);
- provider IDs eligible for routing;
- route-preflight result;
- account/credit precondition status without exposing secrets;
- first live request error, if different from preflight.

A failed preflight should classify the **batch** as provider-unavailable before consuming the behavioral arm sequence. It must not silently substitute a different model or paid route.

## Next decision

Two scientifically clean paths remain:

1. preregister the paid `openai/gpt-oss-120b` route with an explicit maximum budget; or
2. use a locally controlled/open-weight deployment and record the exact model artifact, serving stack, and hardware.

Both change the provider boundary and therefore require a new preregistration.
