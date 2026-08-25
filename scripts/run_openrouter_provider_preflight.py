#!/usr/bin/env python3
"""Run an authenticated OpenRouter route preflight without model generation."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from corrigibility_benchmark.provider_preflight import (
    run_openrouter_preflight,
    save_preflight_result,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--model")
    source.add_argument("--manifest", type=Path)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("provider-preflight.json"),
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument(
        "--require-route",
        action="store_true",
        help="return non-zero after writing evidence unless route is available",
    )
    return parser.parse_args()


def _model_from_args(args: argparse.Namespace) -> str:
    if args.model:
        return str(args.model)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    try:
        value = manifest["provider"]["model_slug"]
    except (KeyError, TypeError) as exc:
        raise SystemExit("manifest provider.model_slug is required") from exc
    if not isinstance(value, str) or not value.strip():
        raise SystemExit("manifest provider.model_slug must be a non-empty string")
    return value


def main() -> int:
    args = parse_args()
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise SystemExit(
            "OPENROUTER_API_KEY is not set. No provider request was made."
        )

    model = _model_from_args(args)
    result = run_openrouter_preflight(
        model,
        api_key=api_key,
        timeout=args.timeout,
    )
    save_preflight_result(result, args.out)

    print(f"classification={result.classification}")
    print(f"requested_model={result.requested_model}")
    print(f"model_listed={result.model_listed}")
    print(f"endpoints_checked={result.endpoints_checked}")
    print(f"endpoint_count={result.endpoint_count}")
    print(f"generation_call_made={result.generation_call_made}")
    print(f"evidence={args.out}")

    if args.require_route and not result.route_available:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
