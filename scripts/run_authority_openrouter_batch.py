#!/usr/bin/env python3
"""Run a preregistered authority-resolution batch through OpenRouter."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from pathlib import Path

from corrigibility_benchmark.authority_batch import (
    load_authority_manifest,
    run_authority_batch,
)
from corrigibility_benchmark.openrouter_authority import OpenRouterAuthorityAdapter


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not os.getenv("OPENROUTER_API_KEY"):
        raise SystemExit("OPENROUTER_API_KEY is not set. No model call was made.")
    manifest = load_authority_manifest(args.manifest)
    summary = run_authority_batch(
        manifest,
        adapter_factory=lambda model, temperature, retries: OpenRouterAuthorityAdapter(
            model=model,
            temperature=temperature,
            max_retries=retries,
        ),
        output_dir=args.out_dir,
    )
    print(f"batch_id={summary.batch_id}")
    print(f"requested_model={summary.requested_model}")
    print(f"temperature={summary.temperature}")
    print(f"sdk_max_retries={summary.sdk_max_retries}")
    print(f"inter_arm_delay_seconds={summary.inter_arm_delay_seconds}")
    print(f"total_arms={summary.total_arms}")
    print(f"counts={json.dumps(summary.counts, sort_keys=True)}")
    print("counterexample_arms=" + ",".join(summary.counterexample_arms))
    print("indeterminate_arms=" + ",".join(summary.indeterminate_arms))
    for record in summary.records:
        print(f"arm={record.arm_id} classification={record.classification}")
    (args.out_dir / "batch-summary.pretty.json").write_text(
        json.dumps(asdict(summary), indent=2, sort_keys=True, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    print(f"evidence_dir={args.out_dir}")
    print("NOTE: authority decisions are simulated; no external effect was executed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
