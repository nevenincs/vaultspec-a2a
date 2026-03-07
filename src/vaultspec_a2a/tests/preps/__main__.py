"""Run preps scenarios: python -m vaultspec_a2a.tests.preps"""

import sys


SCENARIOS = {
    "solo_coder": "Single coder agent (pipeline)",
    "pipeline_team": "Planner + coder + reviewer (pipeline)",
    "plan_approval": "Plan approval interrupt + human resume",
    "autonomous": "Fully autonomous team (no interrupts)",
}


def main() -> None:
    print("Available preps scenarios:\n")
    for name, desc in SCENARIOS.items():
        print(f"  python -m vaultspec_a2a.tests.preps.{name}    — {desc}")
    print()
    if len(sys.argv) > 1:
        print(f"Run: python -m vaultspec_a2a.tests.preps.{sys.argv[1]}")


if __name__ == "__main__":
    main()
