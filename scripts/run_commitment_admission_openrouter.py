#!/usr/bin/env python3
"""Run a preregistered commitment-admission batch through OpenRouter."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from pathlib import Path

from corrigibility_benchmark.admission_batch import (
    load_admission_manifest,
    run_admission_batch,
)
from corrigibility_benchmark.openrouter_admission import OpenRouterAdmissionAdapter


DEFAULT_OUTPUT = Path("live-artifacts/commitment-admission")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not os.getenv("OPENROUTER_API_KEY"):
        raise SystemExit(
            "OPENROUTER_API_KEY is not set. No live model call was made."
        )

    manifest = load_admission_manifest(args.manifest)
    summary = run_admission_batch(
        manifest,
        adapter_factory=lambda model, temperature, retries: (
            OpenRouterAdmissionAdapter(
                model=model,
                temperature=temperature,
                max_retries=retries,
            )
        ),
        output_dir=args.out_dir,
    )

    print(f"batch_id={summary.batch_id}")
    print(f"requested_model={summary.requested_model}")
    print(f"temperature={summary.temperature}")
    print(f"sdk_max_retries={summary.sdk_max_retries}")
    print(
        "inter_scenario_delay_seconds="
        f"{summary.inter_scenario_delay_seconds}"
    )
    print(f"total_scenarios={summary.total_scenarios}")
    print(f"counts={json.dumps(summary.counts, sort_keys=True)}")
    print(
        "unsafe_admission_scenarios="
        + ",".join(summary.unsafe_admission_scenarios)
    )
    print(
        "indeterminate_scenarios="
        + ",".join(summary.indeterminate_scenarios)
    )
    for record in summary.records:
        print(
            f"scenario={record.scenario_id} "
            f"classification={record.classification}"
        )

    (args.out_dir / "batch-summary.pretty.json").write_text(
        json.dumps(asdict(summary), indent=2, sort_keys=True, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    print(f"evidence_dir={args.out_dir}")
    print("NOTE: admission decisions are simulated; no external effect was executed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
