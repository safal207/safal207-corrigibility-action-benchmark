#!/usr/bin/env python3
"""Bound cleanup to a host ownership checkpoint; preserve calibration evidence."""

import argparse
import json
from pathlib import Path

from corrigibility_benchmark.container_shutdown import cleanup_checkpoint


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ownership-file", type=Path, required=True)
    args = parser.parse_args()
    result = cleanup_checkpoint(args.ownership_file)
    print("CHECKPOINT_CLEANUP_JSON=" + json.dumps(result, separators=(",", ":")))
    return 0 if result["removed"] and not result["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
