"""PawPal+ Copilot: the agentic AI layer on top of the PawPal scheduler.

This package turns a plain-English pet-care request into a validated,
conflict-free daily plan. It is a *thin, transparent* agent: an LLM proposes
tasks, but the deterministic `Scheduler` in `pawpal_system.py` is the oracle
that decides whether the day is actually conflict-free -- the model never gets
to make that call itself.

Public entry points:
- `PlannerAgent`   -- the plan -> check -> repair -> explain loop.
- `get_client`     -- picks the real Claude client or the offline stub.
"""

from .planner_agent import PlannerAgent, PlanResult, AgentStep
from .llm_client import LLMClient, StubClient, AnthropicClient, get_client

__all__ = [
    "PlannerAgent",
    "PlanResult",
    "AgentStep",
    "LLMClient",
    "StubClient",
    "AnthropicClient",
    "get_client",
]