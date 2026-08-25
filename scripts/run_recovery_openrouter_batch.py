#!/usr/bin/env python3
"""Run a preregistered latest-intent recovery batch through OpenRouter."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from corrigibility_benchmark.openrouter_recovery import OpenRouterRecoveryAdapter
from corrigibility_benchmark.recovery_batch import (
    load_recovery_manifest,
    run_recovery_batch,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    if not os.getenv("OPENROUTER_API_KEY"):
        raise SystemExit("OPENROUTER_API_KEY is not set; no model call was made")

    manifest = load_recovery_manifest(args.manifest)
    summary = run_recovery_batch(
        manifest,
        adapter_factory=lambda model, temperature, retries: OpenRouterRecoveryAdapter(
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
    print(f"counterexample_arms={','.join(summary.counterexample_arms)}")
    print(f"indeterminate_arms={','.join(summary.indeterminate_arms)}")
    for record in summary.records:
        print(f"arm={record.arm_id} classification={record.classification}")
    print(f"evidence_dir={args.out_dir}")
    print("NOTE: recovery decisions are simulated; no external effect was executed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
