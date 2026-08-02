"""Guardrails: the checks that sit on either side of the language model.

The LLM is the least trustworthy component in the system, so we never let its
output flow straight into the scheduler. There are three guards here:

1. `validate_request`  -- an *input* guard. Reject empty/oversized/junk requests
   before spending an API call on them.
2. `validate_and_build_tasks` -- an *output* guard. Every proposed task must
   survive being constructed as a real `Task` (which enforces non-empty names
   and positive durations) with a valid time, priority, and frequency. Anything
   that fails is dropped and logged, never silently accepted.
3. A lightweight *grounding* check inside (2): a task whose words don't appear
   anywhere in the original request is flagged as a possible hallucination.

The deterministic Scheduler (`detect_conflicts`) is the fourth, load-bearing
guardrail, but it lives in the planner because it also drives the repair loop.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pawpal_system import Priority, Task
from .schemas import FREQUENCIES

MAX_REQUEST_CHARS = 2000

_PRIORITY_MAP = {"low": Priority.LOW, "medium": Priority.MEDIUM, "high": Priority.HIGH}
_HHMM = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d$")

# Small stopword set so the grounding check doesn't flag generic task words as
# ungrounded just because the exact display name isn't a substring.
_GROUNDING_HINTS = {
    "Walk": ("walk", "stroll"),
    "Feed": ("feed", "food", "meal", "breakfast", "dinner"),
    "Vet visit": ("vet", "appointment", "checkup"),
    "Medication": ("med", "medic", "pill", "dose"),
    "Grooming": ("groom", "brush", "bath", "nail"),
    "Playtime": ("play", "fetch", "enrich", "train"),
    "Litter change": ("litter", "clean", "scoop"),
    "Refill water": ("water", "refill", "hydrate"),
    "Nap": ("nap", "sleep", "rest"),
}


@dataclass
class BuiltTask:
    """A validated Task plus the pet it belongs to (needed to rebuild the tree)."""

    task: Task
    pet_name: str
    species: str


def validate_request(text: str) -> tuple[bool, str]:
    """Input guardrail. Returns (ok, reason)."""
    if text is None or not text.strip():
        return False, "The request is empty. Tell me about your pet's care tasks."
    stripped = text.strip()
    if len(stripped) > MAX_REQUEST_CHARS:
        return False, (
            f"That request is very long ({len(stripped)} characters). "
            f"Please keep it under {MAX_REQUEST_CHARS}."
        )
    if not re.search(r"[A-Za-z]", stripped):
        return False, "I couldn't read any words in that request."
    return True, ""


def _is_grounded(task_name: str, pet_name: str, request_lc: str) -> bool:
    """True if the task or its pet is traceable to the request text."""
    if pet_name.casefold() in request_lc:
        return True
    hints = _GROUNDING_HINTS.get(task_name, (task_name.casefold(),))
    return any(hint in request_lc for hint in hints)


def validate_and_build_tasks(
    proposals: list[dict], request: str
) -> tuple[list[BuiltTask], list[dict], list[str]]:
    """Output guardrail.

    Returns (built, rejected, warnings):
    - `built`     -- proposals that became valid Tasks.
    - `rejected`  -- dropped proposals, each `{"proposal": ..., "reason": ...}`.
    - `warnings`  -- non-fatal notes (defaulted frequency, possible hallucination).
    """
    built: list[BuiltTask] = []
    rejected: list[dict] = []
    warnings: list[str] = []
    request_lc = request.casefold()

    for proposal in proposals:
        if not isinstance(proposal, dict):
            rejected.append({"proposal": proposal, "reason": "not an object"})
            continue

        name = str(proposal.get("task_name", "")).strip()
        pet_name = str(proposal.get("pet_name", "")).strip() or "your pet"
        species = str(proposal.get("species", "")).strip() or "pet"

        # Priority.
        prio_raw = str(proposal.get("priority", "")).strip().lower()
        priority = _PRIORITY_MAP.get(prio_raw)
        if priority is None:
            rejected.append({"proposal": proposal, "reason": f"bad priority {prio_raw!r}"})
            continue

        # Duration must be a positive integer (Task enforces > 0 too, but we want
        # a clean reason rather than a raw exception).
        try:
            duration = int(proposal.get("duration_min"))
        except (TypeError, ValueError):
            rejected.append({"proposal": proposal, "reason": "duration not a number"})
            continue

        # Start time: null/blank is fine (unscheduled); otherwise must be HH:MM.
        start = proposal.get("start_time")
        if start in (None, "", "null"):
            start = None
        else:
            start = str(start).strip()
            if not _HHMM.match(start):
                rejected.append(
                    {"proposal": proposal, "reason": f"bad start_time {start!r}"}
                )
                continue

        # Frequency: default to daily with a warning rather than rejecting.
        freq = str(proposal.get("frequency", "daily")).strip().lower()
        if freq not in FREQUENCIES:
            warnings.append(f"Unknown frequency {freq!r} for '{name}' — defaulted to daily.")
            freq = "daily"

        # The Task constructor is itself a guardrail: it rejects empty names and
        # non-positive durations. Let it have the final say.
        try:
            task = Task(
                name=name,
                duration=duration,
                priority=priority,
                start_time=start,
                frequency=freq,
            )
        except ValueError as exc:
            rejected.append({"proposal": proposal, "reason": str(exc)})
            continue

        # Grounding / anti-hallucination check (non-fatal).
        if not _is_grounded(name, pet_name, request_lc):
            warnings.append(
                f"'{name}' for {pet_name} doesn't obviously match your request — "
                "please double-check it."
            )

        built.append(BuiltTask(task=task, pet_name=pet_name, species=species))

    return built, rejected, warnings
