"""The LLM layer: one interface, two interchangeable backends.

`LLMClient` defines two jobs the agent needs from a language model:

- `propose_tasks(request)` -- read plain English, return structured task dicts
  (validated later against `TASK_PROPOSAL_SCHEMA`).
- `explain(request, plan_rows, moves)` -- write a short, plain-language account
  of the final plan and any conflicts that were repaired.

Two backends implement it:

- `AnthropicClient` calls the real Claude API (structured outputs for parsing,
  a normal message for the explanation). Requires an API key.
- `StubClient` is a deterministic, dependency-free rule-based parser. It needs
  no API key and always produces the same output for the same input, which is
  what makes the test suite and `evaluate.py` reproducible -- and doubles as a
  graceful-degradation fallback when Claude isn't available.

`get_client()` picks the right one automatically.
"""

from __future__ import annotations

import os
import re

from .schemas import TASK_PROPOSAL_SCHEMA

# Project default model. Overridable via the PAWPAL_MODEL env var. See
# `docs`/README for why we default to Opus 5.
DEFAULT_MODEL = "claude-opus-5"


class LLMClient:
    """Interface shared by the real and stub backends."""

    name = "base"

    def propose_tasks(self, request: str) -> list[dict]:
        """Turn a natural-language request into a list of task-proposal dicts."""
        raise NotImplementedError

    def explain(self, request: str, plan_rows: list[dict], moves: list[str]) -> str:
        """Write a short plain-language explanation of the final plan."""
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# Deterministic offline backend
# --------------------------------------------------------------------------- #

# Keyword -> (canonical task name, default priority, default duration in minutes).
# Checked in order, so more specific words win.
_TASK_RULES: list[tuple[tuple[str, ...], str, str, int]] = [
    (("vet", "appointment", "checkup", "check-up"), "Vet visit", "high", 45),
    (("medication", "medicine", "meds", "pill", "dose"), "Medication", "high", 5),
    (("walk", "stroll"), "Walk", "medium", 30),
    (("feed", "feeding", "food", "breakfast", "dinner", "meal"), "Feed", "high", 10),
    (("groom", "brush", "bath", "nail"), "Grooming", "low", 20),
    (("play", "fetch", "enrich", "train"), "Playtime", "low", 20),
    (("litter", "clean", "scoop"), "Litter change", "medium", 10),
    (("water", "refill", "hydrate"), "Refill water", "medium", 5),
    (("nap", "sleep", "rest"), "Nap", "low", 30),
]

_NUMBER_WORDS = {
    "once": 1, "one": 1, "twice": 2, "two": 2, "three": 3, "four": 4, "five": 5,
}

# Spaced default start times used when the request asks for N occurrences but
# gives no explicit times -- keeps a multi-walk day readable and deterministic.
_SPACED_TIMES = ["08:00", "12:00", "16:00", "20:00"]


def _to_24h(raw: str) -> str | None:
    """Normalize a single time token like '7am', '3 pm', '9:30', '14:00' to HH:MM."""
    raw = raw.strip().lower().replace(" ", "")
    m = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", raw)
    if m:  # already 24h HH:MM
        return f"{int(m.group(1)):02d}:{m.group(2)}"
    m = re.fullmatch(r"(1[0-2]|0?\d)(?::([0-5]\d))?(am|pm)", raw)
    if m:
        hour = int(m.group(1)) % 12
        if m.group(3) == "pm":
            hour += 12
        minute = m.group(2) or "00"
        return f"{hour:02d}:{minute}"
    return None


def _parse_times(text: str) -> list[str]:
    """Pull every clock time out of a clause, in order, as HH:MM strings."""
    pattern = re.compile(
        r"\b((?:[01]?\d|2[0-3]):[0-5]\d|(?:1[0-2]|0?\d)(?::[0-5]\d)?\s*(?:am|pm))\b",
        re.IGNORECASE,
    )
    out: list[str] = []
    for match in pattern.finditer(text):
        norm = _to_24h(match.group(1))
        if norm and norm not in out:
            out.append(norm)
    return out


def _parse_duration(text: str) -> int | None:
    """Pull a duration in minutes out of a clause ('45 minutes', '1 hour', '30-min')."""
    text = text.lower()
    m = re.search(r"(\d+)\s*-?\s*(?:minutes?|mins?)\b", text)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s*-?\s*(?:hours?|hrs?)\b", text)
    if m:
        return int(m.group(1)) * 60
    if "half hour" in text or "half an hour" in text:
        return 30
    if re.search(r"\ban hour\b", text):
        return 60
    return None


def _parse_count(text: str) -> int:
    """How many occurrences a clause asks for ('two walks', 'twice a day')."""
    text = text.lower()
    m = re.search(r"(\d+)\s+(?:times|walks|feedings?|doses?|sessions?)", text)
    if m:
        return max(1, int(m.group(1)))
    for word, value in _NUMBER_WORDS.items():
        if re.search(rf"\b{word}\b", text):
            return value
    return 1


def _detect_pet(text: str) -> tuple[str, str]:
    """Best-effort (name, species) extraction from the whole request."""
    lower = text.lower()
    species = "pet"
    if any(w in lower for w in ("puppy", "dog", "pup")):
        species = "dog"
    elif any(w in lower for w in ("kitten", "cat")):
        species = "cat"
    elif "bird" in lower:
        species = "bird"

    # "named Cooper", "puppy called Bella", "my dog Rex"
    m = re.search(r"\bnamed\s+([A-Z][a-z]+)", text)
    if not m:
        m = re.search(r"\bcalled\s+([A-Z][a-z]+)", text)
    if not m:
        m = re.search(
            r"\b(?:my|the|a)\s+(?:new\s+)?(?:puppy|dog|cat|kitten|pet|bird)\s+([A-Z][a-z]+)",
            text,
        )
    name = m.group(1) if m else "your pet"
    return name, species


def _match_task_rule(clause: str):
    """Return the first (name, priority, duration) rule whose keyword is in the clause."""
    low = clause.lower()
    for keywords, task_name, priority, duration in _TASK_RULES:
        if any(word in low for word in keywords):
            return task_name, priority, duration
    return None


def _frequency_for(clause: str, task_name: str) -> str:
    """Guess how often a task recurs from its wording."""
    low = clause.lower()
    if "weekly" in low or "every week" in low or "once a week" in low:
        return "weekly"
    # A dated one-off (vet on Thursday) doesn't repeat.
    if task_name == "Vet visit" or "appointment" in low:
        return "once"
    days = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
    if any(day in low for day in days):
        return "once"
    return "daily"


class StubClient(LLMClient):
    """Deterministic, offline rule-based stand-in for the LLM.

    It won't understand everything a real model would, but for the kinds of
    requests this app expects it produces sensible, *repeatable* task lists --
    the property tests and the evaluation harness depend on.
    """

    name = "stub"

    def propose_tasks(self, request: str) -> list[dict]:
        pet_name, species = _detect_pet(request)
        # Split into clauses on commas, semicolons, periods, and " and ".
        clauses = re.split(r"[,.;]|\band\b", request)
        proposals: list[dict] = []
        current: dict | None = None  # the task the parser is currently building

        def flush() -> None:
            """Emit one proposal per occurrence of the current task."""
            if current is None:
                return
            times = current["times"]
            count = max(current["count"], len(times))
            for i in range(count):
                if i < len(times):
                    start = times[i]
                elif times:
                    start = None  # more occurrences than stated times
                elif count > 1:
                    start = _SPACED_TIMES[i % len(_SPACED_TIMES)]
                else:
                    start = None
                proposals.append(
                    {
                        "pet_name": pet_name,
                        "species": species,
                        "task_name": current["name"],
                        "duration_min": current["duration"],
                        "priority": current["priority"],
                        "start_time": start,
                        "frequency": current["frequency"],
                    }
                )

        for clause in clauses:
            clause = clause.strip()
            if not clause:
                continue
            rule = _match_task_rule(clause)
            times = _parse_times(clause)
            duration = _parse_duration(clause)
            if rule is not None:
                # A new task keyword starts a new task.
                flush()
                task_name, priority, default_duration = rule
                current = {
                    "name": task_name,
                    "priority": priority,
                    "duration": duration or default_duration,
                    "times": list(times),
                    "count": _parse_count(clause),
                    "frequency": _frequency_for(clause, task_name),
                }
            elif current is not None:
                # An orphan clause (e.g. the "6pm" in "feed at 7am and 6pm")
                # attaches its stray time/duration to the current task.
                current["times"].extend(t for t in times if t not in current["times"])
                if duration:
                    current["duration"] = duration
        flush()
        return proposals

    def explain(self, request: str, plan_rows: list[dict], moves: list[str]) -> str:
        """Templated explanation -- deterministic, no model call."""
        if not plan_rows:
            return "I couldn't find any pet-care tasks to schedule in that request."
        lines = [f"I planned {len(plan_rows)} task(s) for your day:"]
        for row in plan_rows:
            when = row["start"] if row["start"] != "--:--" else "sometime today"
            lines.append(
                f"- {when}: {row['task']} for {row['pet']} "
                f"({row['duration (min)']} min, {row['priority']} priority)"
            )
        if moves:
            lines.append("")
            lines.append("To keep the day clash-free, I adjusted:")
            lines.extend(f"- {m}" for m in moves)
        else:
            lines.append("")
            lines.append("No conflicts were found — the day flows cleanly.")
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Real Claude backend
# --------------------------------------------------------------------------- #

_PARSE_SYSTEM = (
    "You extract pet-care tasks from a busy owner's plain-English request and "
    "return them as structured data. Rules:\n"
    "- Only include tasks the request actually mentions. Never invent tasks, "
    "pets, or times that are not implied by the request.\n"
    "- Use 24-hour HH:MM for start_time. If a task has no specific time, set "
    "start_time to null.\n"
    "- If a request asks for N occurrences (e.g. 'two walks a day'), emit N "
    "separate task objects.\n"
    "- Infer a reasonable duration_min when it isn't stated (walks ~30, "
    "feeding ~10, vet ~45).\n"
    "- priority is low/medium/high; vet visits and medication are high.\n"
    "- frequency is daily/weekly/once/monthly; a one-off appointment is 'once'."
)


class AnthropicClient(LLMClient):
    """Calls the real Claude API. Constructed only when a key is available."""

    name = "claude"

    def __init__(self, model: str | None = None):
        # Import lazily so the whole agent (and the test suite) runs without the
        # anthropic package installed, as long as the stub backend is used.
        import anthropic

        self._anthropic = anthropic
        self.model = model or os.environ.get("PAWPAL_MODEL", DEFAULT_MODEL)
        self.client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY / profile

    def propose_tasks(self, request: str) -> list[dict]:
        import json

        response = self.client.messages.create(
            model=self.model,
            max_tokens=2000,
            # effort "low" keeps this extraction fast/cheap; the format constraint
            # guarantees the response is valid JSON matching our schema.
            output_config={
                "effort": "low",
                "format": {"type": "json_schema", "schema": TASK_PROPOSAL_SCHEMA},
            },
            system=_PARSE_SYSTEM,
            messages=[{"role": "user", "content": request}],
        )
        text = next((b.text for b in response.content if b.type == "text"), "")
        data = json.loads(text)
        return data.get("tasks", [])

    def explain(self, request: str, plan_rows: list[dict], moves: list[str]) -> str:
        summary = "\n".join(
            f"- {r['start']} {r['task']} for {r['pet']} "
            f"({r['duration (min)']} min, {r['priority']})"
            for r in plan_rows
        )
        moves_text = "\n".join(f"- {m}" for m in moves) if moves else "(none)"
        prompt = (
            "Here is a pet owner's request and the conflict-free daily plan my "
            "scheduler produced from it. Write a short, friendly paragraph (3-5 "
            "sentences) explaining the plan and — if any tasks were moved to "
            "avoid a clash — why. Do not invent tasks that aren't listed.\n\n"
            f"Request: {request}\n\nFinal plan:\n{summary}\n\n"
            f"Tasks moved to resolve conflicts:\n{moves_text}"
        )
        response = self.client.messages.create(
            model=self.model,
            max_tokens=600,
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": prompt}],
        )
        return next((b.text for b in response.content if b.type == "text"), "").strip()


# --------------------------------------------------------------------------- #
# Backend selection
# --------------------------------------------------------------------------- #

def get_client(force: str | None = None) -> LLMClient:
    """Return the right backend.

    Order of decision:
    1. An explicit `force` argument ("claude"/"stub") wins.
    2. The PAWPAL_LLM env var ("claude"/"stub") is next.
    3. Otherwise: use real Claude when an API key is present *and* the anthropic
       package imports and the client builds; fall back to the stub on any
       problem. This graceful degradation means the app always runs.
    """
    choice = (force or os.environ.get("PAWPAL_LLM") or "").strip().lower()
    if choice == "stub":
        return StubClient()
    if choice == "claude":
        return AnthropicClient()

    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            return AnthropicClient()
        except Exception:  # anthropic missing, bad key setup, etc. -> stay offline
            return StubClient()
    return StubClient()
