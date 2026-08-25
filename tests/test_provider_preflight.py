import json
from datetime import datetime, timezone

from corrigibility_benchmark.provider_preflight import (
    JsonHttpResponse,
    run_openrouter_preflight,
    save_preflight_result,
)


MODEL = "openai/gpt-oss-120b:free"
NOW = datetime(2026, 8, 25, 17, 30, tzinfo=timezone.utc)


def catalog(*ids):
    return JsonHttpResponse(200, {"data": [{"id": value} for value in ids]})


def test_route_available_requires_catalog_match_and_live_endpoint():
    calls = []

    def fetcher(url, headers, timeout):
        calls.append((url, headers, timeout))
        if url.endswith("/models"):
            return catalog(MODEL, "other/model")
        return JsonHttpResponse(200, {"data": {"endpoints": [{"name": "free"}]}})

    result = run_openrouter_preflight(
        MODEL,
        api_key="sk-or-v1-secret",
        fetcher=fetcher,
        now=NOW,
    )

    assert result.classification == "ROUTE_AVAILABLE"
    assert result.route_available is True
    assert result.model_listed is True
    assert result.endpoint_count == 1
    assert result.generation_call_made is False
    assert len(calls) == 2
    assert calls[0][1]["Authorization"] == "Bearer sk-or-v1-secret"
    assert calls[1][0].endswith("/openai/gpt-oss-120b%3Afree/endpoints")


def test_catalog_present_but_endpoints_404_is_contract_drift(tmp_path):
    def fetcher(url, headers, timeout):
        if url.endswith("/models"):
            return catalog(MODEL)
        return JsonHttpResponse(
            404,
            {"error": {"message": "model unavailable for free"}},
        )

    result = run_openrouter_preflight(
        MODEL,
        api_key="sk-or-v1-secret",
        fetcher=fetcher,
        now=NOW,
    )
    path = tmp_path / "provider-preflight.json"
    save_preflight_result(result, path)
    saved = json.loads(path.read_text(encoding="utf-8"))

    assert result.classification == "CATALOG_ROUTE_DRIFT"
    assert result.endpoints_http_status == 404
    assert result.endpoint_count == 0
    assert saved["generation_call_made"] is False
    assert "secret" not in path.read_text(encoding="utf-8")


def test_catalog_missing_short_circuits_endpoint_probe():
    calls = []

    def fetcher(url, headers, timeout):
        calls.append(url)
        return catalog("openai/gpt-oss-120b")

    result = run_openrouter_preflight(
        MODEL,
        api_key="sk-or-v1-secret",
        fetcher=fetcher,
        now=NOW,
    )

    assert result.classification == "MODEL_NOT_LISTED"
    assert result.model_listed is False
    assert result.endpoints_checked is False
    assert calls == ["https://openrouter.ai/api/v1/models"]


def test_transport_failure_is_sanitized_and_deterministic():
    def fetcher(url, headers, timeout):
        raise RuntimeError(
            "Authorization: Bearer sk-or-v1-secret failed for sk-or-v1-secret"
        )

    result = run_openrouter_preflight(
        MODEL,
        api_key="sk-or-v1-secret",
        fetcher=fetcher,
        now=NOW,
    )

    assert result.classification == "PREFLIGHT_ERROR"
    assert result.catalog_http_status is None
    assert result.sanitized_error is not None
    assert "sk-or" not in result.sanitized_error
    assert "[REDACTED]" in result.sanitized_error


def test_zero_endpoint_list_is_catalog_route_drift():
    def fetcher(url, headers, timeout):
        if url.endswith("/models"):
            return catalog(MODEL)
        return JsonHttpResponse(200, {"endpoints": []})

    result = run_openrouter_preflight(
        MODEL,
        api_key="sk-or-v1-secret",
        fetcher=fetcher,
        now=NOW,
    )

    assert result.classification == "CATALOG_ROUTE_DRIFT"
    assert result.endpoints_http_status == 200
    assert result.endpoint_count == 0
