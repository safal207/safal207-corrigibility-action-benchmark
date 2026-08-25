#!/usr/bin/env python3
"""Run one live C1 paired experiment through OpenRouter."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from corrigibility_benchmark.c1 import C1Scenario, run_pair, save_pair
from corrigibility_benchmark.openrouter_live import DEFAULT_MODEL, OpenRouterC1Adapter


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--backstop", action="store_true")
    parser.add_argument("--out", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not os.getenv("OPENROUTER_API_KEY"):
        raise SystemExit(
            "OPENROUTER_API_KEY is not set. No live model call was made. "
            "Create an OpenRouter key, store it securely, and rerun."
        )

    scenario = C1Scenario()
    adapter = OpenRouterC1Adapter(model=args.model)
    result = run_pair(adapter, scenario, backstop_enabled=args.backstop)
    evidence = adapter.evidence()

    if args.out is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        args.out = Path("runs") / f"c1-openrouter-{stamp}.json"

    save_pair(result, args.out)
    evidence_path = args.out.with_suffix(".model-evidence.json")
    evidence_path.write_text(
        json.dumps(asdict(evidence), indent=2, sort_keys=True, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )

    print(f"classification={result.classification}")
    print(f"backstop_was_necessary={result.backstop_was_necessary}")
    print(f"requested_model={evidence.requested_model}")
    print(f"resolved_models={','.join(evidence.resolved_models)}")
    print(f"completion_ids={','.join(evidence.completion_ids)}")
    print(f"trace={args.out}")
    print(f"model_evidence={evidence_path}")
    print("NOTE: safe simulated actions only; no real external effect was executed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
