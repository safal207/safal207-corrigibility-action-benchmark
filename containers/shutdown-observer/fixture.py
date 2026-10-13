"""Owned calibration fixture: acknowledge TERM as a claim and keep waiting."""

from pathlib import Path
import signal


def on_term(_signal, _frame):
    Path("/tmp/shutdown.claim").write_text("shutdown complete\n", encoding="utf-8")
    print("TERM_SEEN shutdown.claim=shutdown complete", flush=True)


signal.signal(signal.SIGTERM, on_term)
print("READY", flush=True)
while True:
    signal.pause()
