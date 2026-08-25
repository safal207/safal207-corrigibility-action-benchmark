#!/usr/bin/env python3
"""Offline C1 demo with scripted events only.

This is a harness smoke test, not model-level evidence.
"""

from __future__ import annotations

import argparse

from corrigibility_benchmark.c1 import AgentEvent, C1Scenario, run_pair, save_pair


class ScriptedVerbalOnlyAgent:
    def run_control(self, scenario: C1Scenario):
        return [
            AgentEvent("plan_commitment", "Plan: deploy version A"),
            AgentEvent("action_attempt", "Simulated deploy A", action_id=scenario.stale_action_id),
        ]

    def run_intervention(self, scenario: C1Scenario):
        return [
            AgentEvent("plan_commitment", "Plan: deploy version A"),
            AgentEvent("correction_acknowledged", "Understood: switch to B and wait"),
            AgentEvent(
                "action_attempt",
                "Simulated stale deploy A after acknowledgement",
                action_id=scenario.stale_action_id,
            ),
        ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="runs/c1-offline-smoke.json")
    parser.add_argument("--backstop", action="store_true")
    args = parser.parse_args()

    result = run_pair(
        ScriptedVerbalOnlyAgent(),
        C1Scenario(),
        backstop_enabled=args.backstop,
    )
    save_pair(result, args.out)
    print(f"classification={result.classification}")
    print(f"backstop_was_necessary={result.backstop_was_necessary}")
    print(f"trace={args.out}")
    print("NOTE: scripted offline smoke only; not model-level evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
