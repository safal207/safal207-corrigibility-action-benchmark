#!/usr/bin/env python3
"""Run a preregistered C1 scenario batch through OpenRouter."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from pathlib import Path

from corrigibility_benchmark.batch import load_manifest, run_batch
from corrigibility_benchmark.openrouter_evidence import (
    EvidencePreservingOpenRouterC1Adapter,
)


DEFAULT_MANIFEST = Path("preregistrations/c1-openrouter-ox-alpha-hard-v1.json")
DEFAULT_OUTPUT = Path("live-artifacts/c1-openrouter-hard-v1")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--no-backstop", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not os.getenv("OPENROUTER_API_KEY"):
        raise SystemExit(
            "OPENROUTER_API_KEY is not set. No live model call was made."
        )

    manifest = load_manifest(args.manifest)
    summary = run_batch(
        manifest,
        adapter_factory=lambda model, temperature: (
            EvidencePreservingOpenRouterC1Adapter(
                model=model,
                temperature=temperature,
            )
        ),
        output_dir=args.out_dir,
        backstop_enabled=not args.no_backstop,
    )

    print(f"batch_id={summary.batch_id}")
    print(f"requested_model={summary.requested_model}")
    print(f"temperature={summary.temperature}")
    print(f"total_scenarios={summary.total_scenarios}")
    print(f"counts={json.dumps(summary.counts, sort_keys=True)}")
    print(
        "counterexample_scenarios="
        + ",".join(summary.counterexample_scenarios)
    )
    print(
        "indeterminate_scenarios="
        + ",".join(summary.indeterminate_scenarios)
    )
    for record in summary.records:
        print(
            f"scenario={record.scenario_id} "
            f"classification={record.classification} "
            f"backstop_was_necessary={record.backstop_was_necessary} "
            f"evidence_status={record.evidence_status}"
        )

    (args.out_dir / "batch-summary.pretty.json").write_text(
        json.dumps(asdict(summary), indent=2, sort_keys=True, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    print(f"evidence_dir={args.out_dir}")
    print("NOTE: safe simulated actions only; no real external effect was executed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
