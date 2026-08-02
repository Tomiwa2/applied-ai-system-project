"""Reliability harness for PawPal+ Copilot.

Runs the agent against a fixed battery of scenarios and checks that each one
upholds the properties we care about — the day comes out conflict-free, the
input guardrail rejects junk, the requested fixed appointment survives, and so
on. It runs on the deterministic *stub* backend on purpose, so the results are
100% reproducible and need no API key or network. This is the "evaluation
script that tests sample inputs" required by the rubric.

    python evaluate.py

Exits 0 if every check passes, 1 otherwise (handy for CI).
"""

import sys

# Windows consoles default to cp1252, which can't encode the ✅/❌ status glyphs.
# Force UTF-8 so the report prints cleanly (mirrors formatting.py's approach).
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):  # pragma: no cover - non-standard stdout
    pass

from agent import PlannerAgent
from agent.llm_client import StubClient


def _has_task(result, needle: str) -> bool:
    needle = needle.casefold()
    return any(needle in row["task"].casefold() for row in result.plan)


def _task_at(result, needle: str, time: str) -> bool:
    needle = needle.casefold()
    return any(
        needle in row["task"].casefold() and row["start"] == time for row in result.plan
    )


# Each scenario is (name, request, check(result) -> list[(label, passed)]).
SCENARIOS = [
    (
        "New puppy: two walks, feeding, fixed vet time",
        "I just got a puppy named Cooper. He needs two 30-minute walks a day, "
        "feeding at 7am and 6pm, and a vet visit at 3pm for 45 minutes.",
        lambda r: [
            ("request accepted", r.ok),
            ("produced >= 4 tasks", len(r.plan) >= 4),
            ("vet visit kept at 15:00", _task_at(r, "vet", "15:00")),
            ("final plan is conflict-free", r.conflicts_remaining == 0),
        ],
    ),
    (
        "Direct overlap must be repaired",
        "Walk the dog Rex at 9am for 30 minutes and feed Rex at 9am.",
        lambda r: [
            ("request accepted", r.ok),
            ("both tasks scheduled", len(r.plan) >= 2),
            ("repair loop resolved the clash", r.conflicts_remaining == 0),
            ("at least one task was moved", len(r.moves) >= 1),
        ],
    ),
    (
        "Empty request is rejected by the input guardrail",
        "   ",
        lambda r: [
            ("rejected (ok is False)", r.ok is False),
            ("gave a reason", bool(r.error)),
            ("no tasks leaked through", len(r.plan) == 0),
        ],
    ),
    (
        "Nonsense request produces no tasks",
        "asdf qwerty zxcv 123 !!!",
        lambda r: [
            ("no pet-care tasks extracted", len(r.plan) == 0),
        ],
    ),
    (
        "Single unscheduled task still plans cleanly",
        "Please groom my cat Mochi at some point today.",
        lambda r: [
            ("request accepted", r.ok),
            ("grooming task present", _has_task(r, "groom")),
            ("conflict-free", r.conflicts_remaining == 0),
        ],
    ),
    (
        "Three same-time tasks all get de-conflicted",
        "Walk Rex at 10am for 30 minutes, feed Rex at 10am, and give Rex "
        "medication at 10am.",
        lambda r: [
            ("request accepted", r.ok),
            ("three tasks scheduled", len(r.plan) >= 3),
            ("all conflicts resolved", r.conflicts_remaining == 0),
        ],
    ),
]


def main() -> int:
    # Deterministic backend -> reproducible evaluation.
    agent = PlannerAgent(StubClient())
    total = passed = 0
    print("PawPal+ Copilot — reliability evaluation (stub backend)\n" + "=" * 55)

    for name, request, check in SCENARIOS:
        result = agent.plan(request)
        checks = check(result)
        scenario_ok = all(ok for _, ok in checks)
        print(f"\n{'PASS' if scenario_ok else 'FAIL'}  {name}")
        for label, ok in checks:
            total += 1
            passed += 1 if ok else 0
            print(f"    [{'x' if ok else ' '}] {label}")

    print("\n" + "=" * 55)
    print(f"Checks passed: {passed}/{total}")
    all_ok = passed == total
    print("RESULT:", "ALL CHECKS PASSED ✅" if all_ok else "SOME CHECKS FAILED ❌")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
