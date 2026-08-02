"""The agent loop: plan -> check its own work -> fix -> explain.

`PlannerAgent.plan(request)` runs the whole pipeline:

  input guardrail
      -> LLM proposes tasks           (plan)
      -> output guardrail validates    (build real Tasks, drop bad ones)
      -> Scheduler.detect_conflicts    (CHECK — the deterministic oracle)
      -> bounded repair loop           (FIX — move the loser to a free slot)
      -> LLM explains the final plan   (explain)

The key design idea: the language model proposes, but it never gets to *decide*
whether the day is conflict-free. That verdict comes only from the rule-based
`Scheduler`, so the agent can't hallucinate a clean schedule. Every step is
appended to a transparent log (returned to the UI and written to a log file).
"""

from __future__ import annotations

import logging
import os

from pawpal_system import Owner, Pet, Scheduler, Task
from .guardrails import BuiltTask, validate_and_build_tasks, validate_request
from .llm_client import LLMClient, get_client
from .schemas import AgentStep, PlanResult

DEFAULT_LOG_PATH = "agent_runs.log"


def _build_logger(log_path: str) -> logging.Logger:
    """A module logger that appends structured run records to a file."""
    logger = logging.getLogger("pawpal.agent")
    logger.setLevel(logging.INFO)
    # Avoid stacking a new handler every time PlannerAgent is constructed.
    already = any(
        isinstance(h, logging.FileHandler)
        and getattr(h, "_pawpal_path", None) == os.path.abspath(log_path)
        for h in logger.handlers
    )
    if not already:
        try:
            handler = logging.FileHandler(log_path, encoding="utf-8")
            handler._pawpal_path = os.path.abspath(log_path)  # type: ignore[attr-defined]
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            logger.addHandler(handler)
        except OSError:
            pass  # a read-only filesystem shouldn't break planning
    return logger


class PlannerAgent:
    """Turns a request into a validated, conflict-free plan with an audit trail."""

    def __init__(
        self,
        client: LLMClient | None = None,
        max_repairs: int = 8,
        day_start: str = "08:00",
        day_end: str = "20:00",
        log_path: str = DEFAULT_LOG_PATH,
    ):
        self.client = client or get_client()
        self.max_repairs = max_repairs
        self.day_start = day_start
        self.day_end = day_end
        self.logger = _build_logger(log_path)

    # -- helpers ----------------------------------------------------------- #

    def _log(self, result: PlanResult, stage: str, message: str, level: str = "info") -> None:
        result.steps.append(AgentStep(stage=stage, message=message, level=level))
        record = f"[{result.backend}] {stage}: {message}"
        self.logger.warning(record) if level != "info" else self.logger.info(record)

    @staticmethod
    def _assemble(built: list[BuiltTask]) -> Owner:
        """Rebuild an Owner -> Pet -> Task tree from validated tasks."""
        owner = Owner("You")
        pets: dict[str, Pet] = {}
        for item in built:
            key = item.pet_name.casefold()
            pet = pets.get(key)
            if pet is None:
                pet = Pet(item.pet_name, item.species)
                pets[key] = pet
                owner.add_pet(pet)
            pet.add_task(item.task)
        return owner

    @staticmethod
    def _pick_task_to_move(a: Task, b: Task) -> Task:
        """Of a conflicting pair, choose the one to reschedule.

        Keep the higher-priority task where it is; move the lower-priority one.
        On a priority tie, move whichever starts later (its slot is more
        negotiable); on a full tie, move `b`.
        """
        if a.priority < b.priority:  # Priority is an IntEnum, HIGH=0 (more important)
            return b
        if b.priority < a.priority:
            return a
        if (a.start_minutes or 0) >= (b.start_minutes or 0):
            return a
        return b

    def _rows(self, tasks: list[Task]) -> list[dict]:
        """Display rows for the UI/CLI, in the plan's sorted order."""
        return [
            {
                "start": t.start_time or "--:--",
                "task": t.name,
                "pet": t.pet.name if t.pet else "-",
                "duration (min)": t.duration,
                "priority": t.priority.name.lower(),
            }
            for t in tasks
        ]

    # -- main entry point -------------------------------------------------- #

    def plan(self, request: str) -> PlanResult:
        result = PlanResult(request=request, backend=self.client.name)

        # 1. Input guardrail.
        ok, reason = validate_request(request)
        if not ok:
            result.ok = False
            result.error = reason
            self._log(result, "input-guardrail", f"rejected request: {reason}", "warning")
            return result
        self._log(result, "input-guardrail", "request accepted")

        # 2. LLM proposes tasks (wrapped: an API failure degrades gracefully).
        try:
            proposals = self.client.propose_tasks(request)
        except Exception as exc:  # noqa: BLE001 - we want to catch any backend error
            result.ok = False
            result.error = f"The planner backend failed: {exc}"
            self._log(result, "parse", f"backend error: {exc}", "error")
            return result
        self._log(result, "parse", f"model proposed {len(proposals)} task(s)")

        # 3. Output guardrail: validate + build real Tasks.
        built, rejected, warnings = validate_and_build_tasks(proposals, request)
        result.rejected = rejected
        result.warnings = warnings
        for r in rejected:
            self._log(result, "validate", f"dropped a proposal: {r['reason']}", "warning")
        for w in warnings:
            self._log(result, "validate", w, "warning")
        if not built:
            result.ok = False
            result.error = "No valid pet-care tasks could be extracted from that request."
            self._log(result, "validate", "no valid tasks after guardrails", "warning")
            return result
        self._log(result, "validate", f"{len(built)} task(s) passed the guardrails")

        # 4. Assemble the tree and hand it to the deterministic oracle.
        owner = self._assemble(built)
        scheduler = Scheduler.from_owner(owner)

        # 5. Bounded repair loop. The oracle finds conflicts; we move the loser
        #    to the earliest free slot; repeat until clean or we run out of tries.
        for _ in range(self.max_repairs):
            conflicts = scheduler.detect_conflicts()
            if not conflicts:
                break
            a, b = conflicts[0]
            mover = self._pick_task_to_move(a, b)
            keeper = b if mover is a else a
            slot = scheduler.find_next_available_slot(
                mover.duration,
                day_start=self.day_start,
                day_end=self.day_end,
                on_date=mover.due_date,
            )
            if slot is None:
                msg = (
                    f"Couldn't fit '{mover.name}' anywhere between "
                    f"{self.day_start} and {self.day_end} — leaving the conflict flagged."
                )
                self._log(result, "repair", msg, "warning")
                break
            old = mover.start_time
            mover.start_time = slot
            move_msg = (
                f"Moved '{mover.name}' from {old} to {slot} so it no longer "
                f"clashes with '{keeper.name}' ({keeper.start_time})."
            )
            result.moves.append(move_msg)
            self._log(result, "repair", move_msg)

        # Final verdict from the oracle — never from the model.
        final_conflicts = scheduler.detect_conflicts()
        result.conflicts_remaining = len(final_conflicts)
        verdict = (
            "oracle confirms the day is conflict-free"
            if not final_conflicts
            else f"{len(final_conflicts)} conflict(s) could not be resolved"
        )
        self._log(result, "verify", verdict, "info" if not final_conflicts else "warning")

        # 6. Produce the final plan + a plain-language explanation.
        plan_tasks = scheduler.generate_plan()  # pending tasks, sorted into the day
        result.plan_tasks = plan_tasks
        result.plan = self._rows(plan_tasks)
        try:
            result.explanation = self.client.explain(request, result.plan, result.moves)
        except Exception as exc:  # noqa: BLE001 - explanation is best-effort
            result.explanation = StubExplanationFallback(request, result.plan, result.moves)
            self._log(result, "explain", f"model explanation failed, used fallback: {exc}", "warning")
        else:
            self._log(result, "explain", "wrote plain-language explanation")

        return result


def StubExplanationFallback(request: str, plan_rows: list[dict], moves: list[str]) -> str:
    """Deterministic explanation used if a real model's explain() call fails."""
    from .llm_client import StubClient

    return StubClient().explain(request, plan_rows, moves)
