"""Shared data shapes for the agent layer.

Two kinds of things live here:

1. `TASK_PROPOSAL_SCHEMA` -- the JSON Schema the LLM is constrained to when it
   turns a natural-language request into structured task proposals. The offline
   `StubClient` produces the exact same shape, so the rest of the pipeline never
   has to care which backend ran.
2. Small dataclasses (`AgentStep`, `PlanResult`) that carry the agent's result
   and its step-by-step reasoning log to the CLI and UI.
"""

from dataclasses import dataclass, field

# Allowed values, kept in one place so the schema, the stub, and the guardrails
# all agree.
PRIORITIES = ["low", "medium", "high"]
FREQUENCIES = ["daily", "weekly", "once", "monthly"]

# JSON Schema for structured output. Claude is constrained to return exactly this
# shape (see AnthropicClient), so we get parseable JSON instead of prose. Every
# proposed task names the pet it belongs to, so the planner can rebuild the
# Owner -> Pet -> Task tree the Scheduler expects.
TASK_PROPOSAL_SCHEMA = {
    "type": "object",
    "properties": {
        "tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "pet_name": {"type": "string"},
                    "species": {"type": "string"},
                    "task_name": {"type": "string"},
                    "duration_min": {"type": "integer"},
                    "priority": {"type": "string", "enum": PRIORITIES},
                    # start_time is "HH:MM" (24h) or null when the task is
                    # unscheduled ("sometime today").
                    "start_time": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "frequency": {"type": "string", "enum": FREQUENCIES},
                },
                "required": [
                    "pet_name",
                    "species",
                    "task_name",
                    "duration_min",
                    "priority",
                    "start_time",
                    "frequency",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["tasks"],
    "additionalProperties": False,
}


@dataclass
class AgentStep:
    """One entry in the agent's transparent reasoning log."""

    stage: str  # e.g. "input-guardrail", "parse", "validate", "repair", "explain"
    message: str  # human-readable description of what happened
    level: str = "info"  # "info" | "warning" | "error"

    def __str__(self) -> str:
        icon = {"info": "•", "warning": "⚠", "error": "✖"}.get(self.level, "•")
        return f"{icon} [{self.stage}] {self.message}"


@dataclass
class PlanResult:
    """Everything the agent produced for one request.

    `plan` is a list of display dicts (start/task/pet/duration/priority) and
    `plan_tasks` holds the underlying Task objects (so the CLI can reuse the
    existing `formatting.tasks_table`). `steps` is the reasoning log, and
    `conflicts_remaining` is the oracle's final verdict -- 0 means the deterministic
    Scheduler confirmed the day is clash-free.
    """

    request: str
    backend: str  # which LLM backend ran: "claude" or "stub"
    ok: bool = True
    error: str | None = None
    plan: list[dict] = field(default_factory=list)
    plan_tasks: list = field(default_factory=list)
    conflicts_remaining: int = 0
    moves: list[str] = field(default_factory=list)  # human-readable repair actions
    warnings: list[str] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)  # dropped proposals + reasons
    steps: list[AgentStep] = field(default_factory=list)
    explanation: str = ""
