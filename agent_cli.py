"""PawPal+ Copilot — command-line demo of the agentic planner.

Usage:
    python agent_cli.py "I got a puppy Cooper; two 30-min walks a day, feed at
                         7am and 6pm, and a vet visit at 3pm for 45 minutes."

With no argument it runs a built-in sample request. Set ANTHROPIC_API_KEY to use
the real Claude backend; otherwise it runs on the deterministic offline stub.
Force a backend with PAWPAL_LLM=stub or PAWPAL_LLM=claude.
"""

import sys

from agent import PlannerAgent, get_client
from formatting import tasks_table

SAMPLE_REQUEST = (
    "I just got a puppy named Cooper. He needs a 30-minute walk at 8am, "
    "feeding at 8am and 6pm, a vet visit at 3pm for 45 minutes, and a "
    "grooming session at 3pm."
)


def main() -> None:
    request = " ".join(sys.argv[1:]).strip() or SAMPLE_REQUEST

    agent = PlannerAgent(get_client())
    print("🐾 PawPal+ Copilot")
    print(f"Backend: {agent.client.name}")
    print(f'\nRequest:\n  "{request}"\n')

    result = agent.plan(request)

    # The transparent reasoning log.
    print("--- Agent reasoning log ---")
    for step in result.steps:
        print(f"  {step}")

    if not result.ok:
        print(f"\n⚠️  {result.error}")
        return

    # The final, conflict-checked schedule (reusing the Module-2 view layer).
    print("\n📅 --- Today's plan ---")
    print(tasks_table(result.plan_tasks))

    if result.conflicts_remaining == 0:
        print("\n✅ The scheduler confirms this day is conflict-free.")
    else:
        print(f"\n⚠️  {result.conflicts_remaining} conflict(s) could not be resolved.")

    if result.rejected:
        print(f"\n🚫 Dropped {len(result.rejected)} unusable proposal(s) at the guardrail.")
    if result.warnings:
        print("\n⚠️  Warnings:")
        for w in result.warnings:
            print(f"  - {w}")

    print("\n🗣️  --- Explanation ---")
    print(result.explanation)


if __name__ == "__main__":
    main()
