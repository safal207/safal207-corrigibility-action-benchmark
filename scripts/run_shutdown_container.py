#!/usr/bin/env python3
"""Run the fixed TERM-continuation container fixture with a host observer."""

import argparse
import hashlib
import json
from pathlib import Path

from corrigibility_benchmark.container_shutdown import run_container_case, validate_container_inputs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="prebuilt fixture image; no implicit pull")
    parser.add_argument("--out", type=Path, required=True, help="new host-only JSON report")
    parser.add_argument("--source-commit")
    args = parser.parse_args()
    try:
        validate_container_inputs(args.image, source_commit=args.source_commit)
    except ValueError as exc:
        parser.error(str(exc))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    # Reserve the output before starting Docker; avoid doing work for an output
    # path that cannot be written or already belongs to an earlier attempt.
    with args.out.open("x", encoding="utf-8") as output:
        result = run_container_case(args.image, source_commit=args.source_commit,
                                    ownership_file=args.out.with_suffix(".ownership.json"))
        fixture_root = Path(__file__).resolve().parents[1] / "containers" / "shutdown-observer"
        result["host_source_snapshots"] = {
            name: hashlib.sha256((fixture_root / name).read_bytes()).hexdigest()
            for name in ("fixture.py", "Dockerfile")
        }
        json.dump(result, output, indent=2, allow_nan=False)
        output.write("\n")
    print(f"classification={result['classification']}")
    print(f"calibration_passed={result['calibration_passed']}")
    print(f"container_removed={result['cleanup']['removed']}")
    print("REPORT_JSON=" + json.dumps(result, separators=(",", ":")))
    return 0 if result["calibration_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
