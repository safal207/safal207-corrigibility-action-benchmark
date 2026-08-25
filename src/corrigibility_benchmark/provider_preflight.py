"""Authenticated provider-route preflight for OpenRouter model slugs.

This module deliberately makes catalog and endpoint-discovery requests only. It
never sends a prompt or invokes model generation. The result belongs to the
provider-contract layer and must not be interpreted as model behavior.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
PreflightClassification = Literal[
    "ROUTE_AVAILABLE",
    "CATALOG_ROUTE_DRIFT",
    "MODEL_NOT_LISTED",
    "PREFLIGHT_ERROR",
]


@dataclass(frozen=True)
class JsonHttpResponse:
    """Small transport-neutral JSON response used by the preflight evaluator."""

    status: int
    payload: Any


@dataclass(frozen=True)
class ProviderPreflightResult:
    """Sanitized, machine-readable provider-route evidence."""

    evidence_version: str
    provider: str
    requested_model: str
    checked_at_utc: str
    classification: PreflightClassification
    route_available: bool
    generation_call_made: bool
    catalog_url: str
    catalog_http_status: int | None
    catalog_model_count: int | None
    model_listed: bool | None
    endpoints_url: str
    endpoints_checked: bool
    endpoints_http_status: int | None
    endpoint_count: int | None
    sanitized_error: str | None


Fetcher = Callable[[str, Mapping[str, str], float], JsonHttpResponse]


_SECRET_PATTERNS = (
    re.compile(r"(?i)authorization\s*[:=]\s*bearer\s+[^\s,;]+"),
    re.compile(r"(?i)bearer\s+[^\s,;]+"),
    re.compile(r"sk-or(?:-v1)?-[A-Za-z0-9_-]+"),
    re.compile(r"sk-[A-Za-z0-9_-]{8,}"),
)


def _sanitize_error(value: object, *, api_key: str | None = None) -> str:
    text = str(value)
    if api_key:
        text = text.replace(api_key, "[REDACTED]")
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text[:2000]


def _decode_json(raw: bytes) -> Any:
    if not raw:
        return None
    return json.loads(raw.decode("utf-8"))


def _urllib_fetch_json(
    url: str,
    headers: Mapping[str, str],
    timeout: float,
) -> JsonHttpResponse:
    request = Request(url, headers=dict(headers), method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed HTTPS URLs
            return JsonHttpResponse(
                status=int(response.status),
                payload=_decode_json(response.read()),
            )
    except HTTPError as exc:
        raw = exc.read()
        try:
            payload = _decode_json(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = {"error": raw.decode("utf-8", errors="replace")}
        return JsonHttpResponse(status=int(exc.code), payload=payload)
    except URLError as exc:
        raise RuntimeError(f"provider transport error: {exc.reason}") from exc


def _model_ids(payload: Any) -> tuple[str, ...]:
    values: Any
    if isinstance(payload, dict):
        values = payload.get("data")
    else:
        values = payload
    if not isinstance(values, list):
        raise ValueError("catalog response did not contain a data list")

    result: list[str] = []
    for item in values:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            result.append(item["id"])
    return tuple(result)


def _endpoint_count(payload: Any) -> int:
    if isinstance(payload, dict):
        direct = payload.get("endpoints")
        if isinstance(direct, list):
            return len(direct)

        data = payload.get("data")
        if isinstance(data, list):
            return len(data)
        if isinstance(data, dict):
            nested = data.get("endpoints")
            if isinstance(nested, list):
                return len(nested)
    raise ValueError("endpoint response did not contain an endpoint list")


def _payload_error(payload: Any) -> str:
    try:
        return json.dumps(payload, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(payload)


def _timestamp(now: datetime | None) -> str:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _model_urls(model: str) -> tuple[str, str]:
    if "/" not in model:
        raise ValueError("OpenRouter model id must use author/slug form")
    author, slug = model.split("/", 1)
    if not author or not slug:
        raise ValueError("OpenRouter model id must use non-empty author/slug form")
    catalog_url = f"{OPENROUTER_BASE_URL}/models"
    endpoint_url = (
        f"{OPENROUTER_BASE_URL}/models/{quote(author, safe='')}/"
        f"{quote(slug, safe='')}/endpoints"
    )
    return catalog_url, endpoint_url


def run_openrouter_preflight(
    model: str,
    *,
    api_key: str,
    fetcher: Fetcher | None = None,
    timeout: float = 30.0,
    now: datetime | None = None,
) -> ProviderPreflightResult:
    """Check authenticated catalog and endpoint-route availability.

    The function never makes a completion request. A missing catalog entry
    short-circuits endpoint discovery because the requested route cannot be
    proven available for the authenticated account.
    """

    if not api_key:
        raise ValueError("api_key must be non-empty")
    if timeout <= 0:
        raise ValueError("timeout must be positive")

    catalog_url, endpoints_url = _model_urls(model)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "User-Agent": "corrigibility-action-benchmark/provider-preflight-v1",
    }
    request_json = fetcher or _urllib_fetch_json

    base = {
        "evidence_version": "provider-route-preflight-v1",
        "provider": "OpenRouter",
        "requested_model": model,
        "checked_at_utc": _timestamp(now),
        "generation_call_made": False,
        "catalog_url": catalog_url,
        "endpoints_url": endpoints_url,
    }

    try:
        catalog = request_json(catalog_url, headers, timeout)
    except Exception as exc:  # transport boundary is converted into evidence
        return ProviderPreflightResult(
            **base,
            classification="PREFLIGHT_ERROR",
            route_available=False,
            catalog_http_status=None,
            catalog_model_count=None,
            model_listed=None,
            endpoints_checked=False,
            endpoints_http_status=None,
            endpoint_count=None,
            sanitized_error=_sanitize_error(exc, api_key=api_key),
        )

    if catalog.status < 200 or catalog.status >= 300:
        return ProviderPreflightResult(
            **base,
            classification="PREFLIGHT_ERROR",
            route_available=False,
            catalog_http_status=catalog.status,
            catalog_model_count=None,
            model_listed=None,
            endpoints_checked=False,
            endpoints_http_status=None,
            endpoint_count=None,
            sanitized_error=_sanitize_error(
                _payload_error(catalog.payload), api_key=api_key
            ),
        )

    try:
        ids = _model_ids(catalog.payload)
    except Exception as exc:
        return ProviderPreflightResult(
            **base,
            classification="PREFLIGHT_ERROR",
            route_available=False,
            catalog_http_status=catalog.status,
            catalog_model_count=None,
            model_listed=None,
            endpoints_checked=False,
            endpoints_http_status=None,
            endpoint_count=None,
            sanitized_error=_sanitize_error(exc, api_key=api_key),
        )

    listed = model in ids
    if not listed:
        return ProviderPreflightResult(
            **base,
            classification="MODEL_NOT_LISTED",
            route_available=False,
            catalog_http_status=catalog.status,
            catalog_model_count=len(ids),
            model_listed=False,
            endpoints_checked=False,
            endpoints_http_status=None,
            endpoint_count=None,
            sanitized_error=None,
        )

    try:
        endpoints = request_json(endpoints_url, headers, timeout)
    except Exception as exc:
        return ProviderPreflightResult(
            **base,
            classification="PREFLIGHT_ERROR",
            route_available=False,
            catalog_http_status=catalog.status,
            catalog_model_count=len(ids),
            model_listed=True,
            endpoints_checked=True,
            endpoints_http_status=None,
            endpoint_count=None,
            sanitized_error=_sanitize_error(exc, api_key=api_key),
        )

    if endpoints.status == 404:
        return ProviderPreflightResult(
            **base,
            classification="CATALOG_ROUTE_DRIFT",
            route_available=False,
            catalog_http_status=catalog.status,
            catalog_model_count=len(ids),
            model_listed=True,
            endpoints_checked=True,
            endpoints_http_status=404,
            endpoint_count=0,
            sanitized_error=_sanitize_error(
                _payload_error(endpoints.payload), api_key=api_key
            ),
        )

    if endpoints.status < 200 or endpoints.status >= 300:
        return ProviderPreflightResult(
            **base,
            classification="PREFLIGHT_ERROR",
            route_available=False,
            catalog_http_status=catalog.status,
            catalog_model_count=len(ids),
            model_listed=True,
            endpoints_checked=True,
            endpoints_http_status=endpoints.status,
            endpoint_count=None,
            sanitized_error=_sanitize_error(
                _payload_error(endpoints.payload), api_key=api_key
            ),
        )

    try:
        count = _endpoint_count(endpoints.payload)
    except Exception as exc:
        return ProviderPreflightResult(
            **base,
            classification="PREFLIGHT_ERROR",
            route_available=False,
            catalog_http_status=catalog.status,
            catalog_model_count=len(ids),
            model_listed=True,
            endpoints_checked=True,
            endpoints_http_status=endpoints.status,
            endpoint_count=None,
            sanitized_error=_sanitize_error(exc, api_key=api_key),
        )

    classification: PreflightClassification = (
        "ROUTE_AVAILABLE" if count > 0 else "CATALOG_ROUTE_DRIFT"
    )
    return ProviderPreflightResult(
        **base,
        classification=classification,
        route_available=classification == "ROUTE_AVAILABLE",
        catalog_http_status=catalog.status,
        catalog_model_count=len(ids),
        model_listed=True,
        endpoints_checked=True,
        endpoints_http_status=endpoints.status,
        endpoint_count=count,
        sanitized_error=None,
    )


def save_preflight_result(result: ProviderPreflightResult, path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(asdict(result), indent=2, sort_keys=True, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
