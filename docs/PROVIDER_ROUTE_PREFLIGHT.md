# Authenticated provider-route preflight

A public or previously discoverable model slug is not proof that the route is
available to the current account at execution time.

The provider-contract transition is:

```text
preregistered model slug
-> authenticated catalog snapshot
-> authenticated endpoint-route snapshot
-> behavioral batch may start
```

The preflight makes **no completion or generation request**. It records only
catalog and endpoint-discovery evidence.

## Deterministic outcomes

- `ROUTE_AVAILABLE` — the exact model is listed and at least one endpoint route
  is returned.
- `CATALOG_ROUTE_DRIFT` — the model is listed but endpoint discovery returns
  `404` or zero endpoints.
- `MODEL_NOT_LISTED` — the exact requested model id is absent from the
  authenticated catalog.
- `PREFLIGHT_ERROR` — authentication, transport, HTTP, or response-shape
  failure prevents a trustworthy route conclusion.

## CLI

```bash
export OPENROUTER_API_KEY='...'
python scripts/run_openrouter_provider_preflight.py \
  --model openai/gpt-oss-120b:free \
  --out provider-preflight.json
```

For CI gating, add `--require-route`. Evidence is written before the command
returns non-zero for an unavailable route.

A preregistered manifest can be used instead of repeating the slug:

```bash
python scripts/run_openrouter_provider_preflight.py \
  --manifest preregistrations/authority-openrouter-gpt-oss-120b-v1.json \
  --out live-artifacts/provider-preflight.json \
  --require-route
```

## Evidence boundary

A successful preflight proves only that an authenticated provider route was
discoverable at the recorded time. It does not prove model identity beyond the
provider contract, stable future availability, correct generation, or safe
behavior.

A failed preflight must not be converted into one `INDETERMINATE` row per
behavioral arm. It is one provider-layer result, and changing the model slug,
provider, or pricing route requires a new preregistration.
