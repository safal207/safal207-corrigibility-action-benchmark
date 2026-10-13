#!/usr/bin/env python3
"""Run six real, trusted subprocess fixtures; no provider credentials needed."""

from __future__ import annotations

import argparse
from pathlib import Path

from corrigibility_benchmark.shutdown_observer import (
    CASES,
    calibration_passed,
    run_shutdown_case,
    save_shutdown_results,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="new JSON file; never overwritten")
    args = parser.parse_args()
    results = [run_shutdown_case(case) for case in CASES]
    save_shutdown_results(results, args.out)
    for result in results:
        print(f"{result.case}={result.classification} cleanup={result.cleanup.action}")
    passed = calibration_passed(results)
    print(f"calibration_passed={passed}")
    print(f"trace={args.out}")
    print("NOTE: trusted child-process calibration; no model-level or hostile-containment claim")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
