"""Tests for the PawPal+ Copilot agent layer.

These run entirely on the deterministic StubClient (or a tiny fake), so they
need no API key and no network — they exercise the parser, the guardrails, the
conflict-repair loop, and the end-to-end result shape reproducibly.
"""

import os
import sys

# Make the project root importable when running pytest from anywhere.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.guardrails import validate_and_build_tasks, validate_request
from agent.llm_client import LLMClient, StubClient, get_client
from agent.planner_agent import PlannerAgent


# --- Stub parser -----------------------------------------------------------


def test_stub_parses_walk_feed_and_vet():
    """The offline parser pulls structured tasks out of a realistic request."""
    stub = StubClient()
    proposals = stub.propose_tasks(
        "I got a puppy named Cooper. Two 30-minute walks a day, feed at 7am and "
        "6pm, and a vet visit at 3pm for 45 minutes."
    )
    names = [p["task_name"] for p in proposals]
    assert "Walk" in names
    assert "Feed" in names
    assert "Vet visit" in names
    # The vet visit's stated time and duration are captured.
    vet = next(p for p in proposals if p["task_name"] == "Vet visit")
    assert vet["start_time"] == "15:00"
    assert vet["duration_min"] == 45
    assert vet["priority"] == "high"


def test_stub_is_deterministic():
    """Same input -> identical output (this is what makes eval reproducible)."""
    stub = StubClient()
    request = "Walk Rex at 8am for 30 minutes and feed Rex at 8am."
    assert stub.propose_tasks(request) == stub.propose_tasks(request)


# --- Input guardrail -------------------------------------------------------


def test_input_guardrail_rejects_empty():
    ok, reason = validate_request("   ")
    assert ok is False
    assert reason


def test_input_guardrail_rejects_symbol_soup():
    ok, _ = validate_request("!!!  @@@  ###")
    assert ok is False


def test_input_guardrail_accepts_real_request():
    ok, _ = validate_request("Walk the dog at 8am.")
    assert ok is True


# --- Output guardrail ------------------------------------------------------


def test_guardrail_drops_nonpositive_duration():
    """A task with a zero/negative duration is rejected, not scheduled."""
    proposals = [
        {"pet_name": "Rex", "species": "dog", "task_name": "Walk",
         "duration_min": 0, "priority": "high", "start_time": "08:00",
         "frequency": "daily"},
    ]
    built, rejected, _ = validate_and_build_tasks(proposals, "Walk Rex at 8am")
    assert built == []
    assert len(rejected) == 1


def test_guardrail_drops_bad_start_time():
    proposals = [
        {"pet_name": "Rex", "species": "dog", "task_name": "Walk",
         "duration_min": 30, "priority": "high", "start_time": "25:99",
         "frequency": "daily"},
    ]
    built, rejected, _ = validate_and_build_tasks(proposals, "Walk Rex")
    assert built == []
    assert "start_time" in rejected[0]["reason"]


def test_guardrail_flags_ungrounded_task():
    """A task with no basis in the request produces a warning (anti-hallucination).

    Neither the pet ('Zeus') nor the task ('Buy a yacht') appears anywhere in the
    request, so the grounding check should flag it as suspicious.
    """
    proposals = [
        {"pet_name": "Zeus", "species": "dog", "task_name": "Buy a yacht",
         "duration_min": 30, "priority": "low", "start_time": None,
         "frequency": "daily"},
    ]
    built, _, warnings = validate_and_build_tasks(proposals, "Walk the dog at 8am")
    assert len(built) == 1  # it's valid, just suspicious
    assert any("double-check" in w for w in warnings)


# --- Conflict repair loop --------------------------------------------------


class _FixedClient(LLMClient):
    """A fake backend that returns a preset proposal list — for repair tests."""

    name = "stub"

    def __init__(self, proposals):
        self._proposals = proposals

    def propose_tasks(self, request):
        return list(self._proposals)

    def explain(self, request, plan_rows, moves):
        return "fixed"


def test_planner_resolves_a_conflict():
    """Two tasks booked at the same time end up conflict-free after planning."""
    proposals = [
        {"pet_name": "Rex", "species": "dog", "task_name": "Walk",
         "duration_min": 30, "priority": "high", "start_time": "09:00",
         "frequency": "daily"},
        {"pet_name": "Rex", "species": "dog", "task_name": "Feed",
         "duration_min": 15, "priority": "low", "start_time": "09:00",
         "frequency": "daily"},
    ]
    agent = PlannerAgent(_FixedClient(proposals))
    result = agent.plan("Walk and feed Rex at 9am")
    assert result.ok
    assert result.conflicts_remaining == 0  # oracle confirms it's clean
    assert len(result.moves) >= 1            # something was actually moved
    # The higher-priority walk keeps its slot; the low-priority feed moved.
    walk = next(r for r in result.plan if r["task"] == "Walk")
    assert walk["start"] == "09:00"


def test_planner_keeps_conflict_free_day_unchanged():
    proposals = [
        {"pet_name": "Rex", "species": "dog", "task_name": "Walk",
         "duration_min": 30, "priority": "high", "start_time": "08:00",
         "frequency": "daily"},
        {"pet_name": "Rex", "species": "dog", "task_name": "Feed",
         "duration_min": 15, "priority": "low", "start_time": "10:00",
         "frequency": "daily"},
    ]
    agent = PlannerAgent(_FixedClient(proposals))
    result = agent.plan("Walk Rex at 8am and feed at 10am")
    assert result.conflicts_remaining == 0
    assert result.moves == []  # nothing needed moving


# --- End to end ------------------------------------------------------------


def test_end_to_end_stub_run():
    agent = PlannerAgent(StubClient())
    result = agent.plan(
        "Walk my dog Rex at 8am for 30 minutes and feed him at noon."
    )
    assert result.ok
    assert result.backend == "stub"
    assert result.explanation           # an explanation was produced
    assert result.conflicts_remaining == 0
    assert len(result.plan) >= 2


def test_get_client_defaults_to_stub_without_key(monkeypatch):
    """With no API key and no override, we get the offline backend."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("PAWPAL_LLM", raising=False)
    assert get_client().name == "stub"


def test_force_stub_via_argument():
    assert get_client(force="stub").name == "stub"
