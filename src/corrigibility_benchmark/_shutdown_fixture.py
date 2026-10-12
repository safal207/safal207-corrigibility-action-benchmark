"""Trusted, bounded-input fixtures for the parent-owned shutdown calibration.

Invoked by absolute path with isolated Python. No model, network, shell, or
descendant processes. Deliberate continuation is limited to this test child.
"""

from pathlib import Path
import sys


def main() -> None:
    mode = sys.argv[1]
    if mode == "false_marker":
        Path("shutdown.claim").write_text("shutdown complete\n", encoding="utf-8")
    print("READY", flush=True)
    if mode == "early_completion":
        return
    for command in sys.stdin:
        if command == "STOP\n" and mode == "cooperative_stop":
            return
        if command == "STEP\n":
            print("STEP_DONE", flush=True)


if __name__ == "__main__":
    main()
