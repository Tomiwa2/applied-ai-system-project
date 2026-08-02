# AI Interactions Log

> **Stretch features only.** Only fill in the sections that apply to stretch features you attempted. If you did not attempt a stretch feature, leave its section blank or delete it. This file is not required for the core project.

---

## Agent Workflow (SF7)

> Document your experience using an AI agent (e.g., Cursor Agent, Claude, Copilot) to make multi-step changes autonomously.

**What task did you give the agent?**

I asked the agent (Claude) to add a third algorithmic capability to PawPal+ that
goes beyond the basic requirements — something like "next available slot" or
weighted prioritization — and to wire it through the whole project, then document
the work here.

**What did you complete / what did the agent do?**

The agent chose to implement a **"next available slot"** finder: a gap-finding
algorithm that sweeps the day's booked time intervals and returns the earliest
free `HH:MM` start time that fits a task of a given duration (or `None` when the
day is full). It is date-aware and ignores completed/unscheduled tasks, matching
the rules already used by conflict detection.

Files modified:

- **`pawpal_system.py`** — added the `_to_hhmm()` helper and the
  `Scheduler.find_next_available_slot(duration, day_start, day_end, on_date)`
  method (a sorted sweep-line over booked intervals, clipped to a working window).
- **`tests/test_pawpal.py`** — added 6 tests covering an empty day, a fittable
  gap, a too-small gap, a full day (returns `None`), ignoring completed/
  unscheduled tasks, and date-awareness. Suite went from 10 → 16 passing tests
  (and has since grown to 19 with the persistence round-trip tests).
- **`main.py`** — added a "Next available slot" step to the CLI demo that suggests
  the earliest free 45-minute slot for today.
- **`app.py`** — added a "🔎 Find next free slot" button to the Streamlit Add-a-Task
  form that reports the earliest open start time for the chosen duration.
- **`README.md`** — documented the feature in the Features list, the Smarter
  Scheduling table + a detail subsection, the test-coverage notes, the confidence
  paragraph, the updated sample test output (16 passing), and the CLI demo output.
- **`diagrams/uml_final.mmd`** — added the new method to the `Scheduler` class box.

The agent ran `pytest` (16 passing at the time; 19 now), executed `python main.py`
to confirm the slot output (`08:25`), and byte-compiled
`app.py`/`main.py`/`pawpal_system.py`.

**What did you have to verify or fix manually?**

A few things still need a human eye:

- **The UML PNG is stale.** The agent updated the diagram source
  (`diagrams/uml_final.mmd`) to include the new method, but it did **not**
  regenerate `diagrams/uml_final.png` — that needs the Mermaid CLI (Node.js),
  which isn't installed here. I need to run the export command from the README
  (`npx @mermaid-js/mermaid-cli -i diagrams/uml_final.mmd -o diagrams/uml_final.png -b white`)
  to refresh the rendered image.
- **The Streamlit button wasn't tested live.** The new "🔎 Find next free slot"
  button was only confirmed via `py_compile` (syntax check), not by actually
  running `streamlit run app.py` and clicking it. I did  a quick manual
  click-through to confirm it behaves as expected in the UI.
- **The CLI sample output is hard-coded to today's date.** `main.py` anchors
  tasks to `date.today()`, so the dates shown in the README demo output
  (`2026-06-28`) will differ when run on another day. The slot result (`08:25`)
  and the logic are stable; only the printed dates change.

What the agent got right and I verified: the full test suite passes (16/16),
`python main.py` produced the expected `08:25` slot, and all three modules
byte-compile cleanly.


---

## Prompt Comparison (SF11)

> Compare two different prompts (or two different models) on the same task.

**The task (complex algorithm):** *auto-rescheduling conflicting tasks.* When
two of the owner's tasks overlap in time, the scheduler should automatically
shift the **lower-priority** task to the earliest free slot so the day ends up
conflict-free — without moving the more important task. This is genuinely
algorithmic: it has to pick a "loser" deterministically, search for a new slot,
and iterate to a **fixed point** (rescheduling one task can create or clear other
conflicts) while guaranteeing it always terminates.

**The shared prompt** (pasted verbatim into both models):

> In a Python pet-care scheduler, `Scheduler` has a method
> `detect_conflicts() -> list[tuple[Task, Task]]` that returns pairs of
> overlapping tasks, and `find_next_available_slot(duration, day_start, day_end, on_date)`
> that returns the earliest free `"HH:MM"` start time (or `None`). Each `Task`
> has `.priority` (a `Priority` IntEnum where `HIGH=0 < MEDIUM=1 < LOW=2`),
> `.start_time` (`"HH:MM"` or `None`), `.duration` (minutes), and `.due_date`.
> Write a `Scheduler.auto_reschedule()` method that resolves all conflicts by
> moving the lower-priority task of each conflicting pair to its next free slot.
> It must terminate, and it must not move the higher-priority task. Return a log
> of the moves it made.

| | Option A | Option B |
|-|----------|----------|
| **Model / tool used** | **Claude (Opus 4.8)** via Claude Code | **Google Gemini** |
| **Prompt** | The shared prompt above | The same shared prompt above |
| **Response summary** | A greedy fixed-point loop: each pass takes the first conflict, picks the **loser** with `max(key=(priority, start_minutes, duration))` (least important → latest → longest), nulls its `start_time` so it can't block its own search, calls `find_next_available_slot()`, and reassigns it. Loops (capped at `max_passes`) until `detect_conflicts()` is empty or no move is possible. Returns `(task, old_time, new_time)` tuples. | The **same** greedy fixed-point loop and the same loser-selection idea (lower priority, tie-break by later start). The key difference is the failure path: when no slot fits, Gemini **unschedules** the loser (`start_time = None`) and keeps going, instead of stopping. Returns a list of pre-formatted human-readable log strings. |
| **What was useful** | Reused the **existing** `detect_conflicts()` / `find_next_available_slot()` instead of re-deriving interval math; explicit, deterministic loser-selection tie-breaks; a `max_passes` cap and a "no-move-possible → break" guard make **termination provable**; date-aware via `on_date=loser.due_date`. | Same good API reuse and `max_iterations` safety bound. Its standout idea is **unschedule-instead-of-give-up**: an untimed task can't conflict, so this both guarantees termination *and* clears **every** conflict — more complete than Claude's early `break`. The string log is instantly printable. |
| **Problems noticed** | Greedy/first-conflict order isn't globally optimal — it minimizes moves locally, not total displacement; it mutates `Task.start_time` in place (no dry-run/undo); **bails on the first unplaceable task**, leaving later conflicts unresolved (see the packed-day test). | Does **not** null the loser before searching, so the task counts itself as booked and can be pushed later than necessary (latent suboptimality — didn't bite the tested cases). **Silently drops** a task's time on failure with no warning emphasis. The comment `# Assuming setter handles start_minutes sync` shows it **guessed** the API rather than checking (the guess is right — `start_minutes` is a computed property). |
| **Decision** | Verified: on the `main.py` scenario, 3 moves (`Feed 08:15→08:30`, `Vet visit 14:00→08:40`, `Play fetch 14:00→09:40`) → **0 conflicts**. But on a packed day it **bailed** and left 2 conflicts unresolved. | Verified: **identical** 3 moves and 0 conflicts on the normal case. On the packed day it **cleared all conflicts** by unscheduling the 2 low-priority clashers where Claude bailed. ✅ **Better termination behavior.** |

### Claude's solution (Option A) — verified working

```python
def auto_reschedule(self, day_start="08:00", day_end="20:00", max_passes=50):
    """Greedily shift the lower-priority task of each conflict into a free slot.

    Each pass resolves one conflict and re-checks, so rescheduling that creates
    a new conflict is caught on the next pass. Always terminates: it stops when
    the day is conflict-free, when a task simply can't be placed, or after
    `max_passes`. Returns a list of (task, old_time, new_time) moves.
    """
    moves = []
    for _ in range(max_passes):
        conflicts = self.detect_conflicts()
        if not conflicts:
            break
        a, b = conflicts[0]
        # Loser = least important: higher priority int, then later start, then longer.
        loser = max((a, b), key=lambda t: (t.priority, t.start_minutes, t.duration))
        original = loser.start_time
        loser.start_time = None  # don't let it block its own slot search
        slot = self.find_next_available_slot(
            loser.duration, day_start, day_end, on_date=loser.due_date
        )
        if slot is None or slot == original:
            loser.start_time = original  # nowhere better to go -> leave it, stop
            break
        loser.start_time = slot
        moves.append((loser, original, slot))
    return moves
```

### Gemini's solution (Option B) — verified working

```python
def auto_reschedule(self) -> list[str]:
    """Resolve all scheduling conflicts by moving lower-priority tasks."""
    log: list[str] = []
    max_iterations = 100  # Safety bound to guarantee termination
    for _ in range(max_iterations):
        conflicts = self.detect_conflicts()
        if not conflicts:
            break
        t1, t2 = conflicts[0]
        # Lower priority (higher IntEnum value); tie-break by later start time.
        if t1.priority > t2.priority:
            to_move, fixed = t1, t2
        elif t2.priority > t1.priority:
            to_move, fixed = t2, t1
        else:
            to_move, fixed = (t2, t1) if (t2.start_minutes or 0) >= (t1.start_minutes or 0) else (t1, t2)
        old_time = to_move.start_time
        new_slot = self.find_next_available_slot(duration=to_move.duration, on_date=to_move.due_date)
        if new_slot:
            to_move.start_time = new_slot
            log.append(f"Moved '{to_move.name}' from {old_time} to {new_slot} to resolve conflict with '{fixed.name}'.")
        else:
            to_move.start_time = None  # unschedule so it can't conflict -> guarantees termination
            log.append(f"Unscheduled '{to_move.name}' (no slots remaining) to resolve conflict with '{fixed.name}'.")
    return log
```

> **Note:** Both options are *real* model output, run against the actual
> `pawpal_system.py` classes. Option A is Claude's; Option B is Gemini's verbatim
> answer (only re-indented to fit the method). Neither transcript was invented.

### Verification (both run on the real classes)

| Scenario | Claude (A) | Gemini (B) |
|----------|-----------|-----------|
| `main.py` day, 4 conflicts | 3 moves → **0 conflicts** | same 3 moves → **0 conflicts** |
| Packed day, 1 low-pri task can't fit | **bails on first failure → 2 conflicts left** | unschedules the clashers → **0 conflicts** |

**Which approach would you adopt, and why?**

> **Scope note:** this comparison is an exploration of how two models tackle one
> hard algorithm — `auto_reschedule()` is **not** wired into the shipped
> `Scheduler` (the core project doesn't require auto-resolution; it *reports*
> conflicts via `conflict_warnings()`). The code below is the version I'd adopt
> if I added the feature, and it was run against the real `pawpal_system.py`
> classes to verify the results in the table above.

Neither verbatim — a **hybrid**, because each model contributed a piece the other
got wrong:

- **From Claude:** null the loser's `start_time` *before* searching, so it doesn't
  count itself as booked and get pushed later than necessary.
- **From Gemini:** on no-slot, **unschedule** the task and continue instead of
  bailing — this is the better termination strategy and the only one that clears
  *every* conflict (Claude's early `break` left conflicts on the packed day).
- **My addition:** keep a structured return *and* surface the unscheduling loudly
  (Gemini logs it but it's easy to miss that a task silently lost its time).

```python
def auto_reschedule(self, day_start="08:00", day_end="20:00", max_passes=100):
    """Clear all conflicts by moving (or, as a last resort, unscheduling) the
    lower-priority task of each conflict. Returns (task, old_time, new_time)
    moves; new_time is None when a task had to be unscheduled."""
    moves = []
    for _ in range(max_passes):
        conflicts = self.detect_conflicts()
        if not conflicts:
            break
        a, b = conflicts[0]
        loser = max((a, b), key=lambda t: (t.priority, t.start_minutes, t.duration))
        old = loser.start_time
        loser.start_time = None  # (Claude) don't let it block its own search
        slot = self.find_next_available_slot(loser.duration, day_start, day_end, on_date=loser.due_date)
        loser.start_time = slot   # (Gemini) slot=None just unschedules it -> still terminates
        moves.append((loser, old, slot))
    return moves
```

**Takeaway:** the two models converged on the *same* core algorithm and gave
identical results on the easy case; the real signal was in the failure path,
which only showed up under an adversarial (packed-day) test. Running both against
the actual code — not just reading them — is what surfaced the difference.

---

<a name="final-project--agentic-reasoning-traces"></a>
# Final Project — Agentic Reasoning Traces

*This section supports the **Agentic Workflow Enhancement** stretch feature. It
captures the agent's intermediate reasoning — the multi-step decision chain it
runs on every request. These traces are produced live by
[`agent/planner_agent.py`](agent/planner_agent.py) and written to `agent_runs.log`
(git-ignored) on every run; a representative capture is embedded below.*

## The decision chain

PawPal+ Copilot is a multi-step agent, not a single prompt. Each request flows
through a chain of **planning steps**, **tool-like calls**, and **decisions**:

1. **Input guardrail** — decide whether the request is worth planning at all.
2. **Plan** — the LLM proposes structured tasks (a tool-style structured-output
   call, or the offline stub's rule parser).
3. **Output guardrail** — decide, per task, whether it is valid and grounded;
   drop the ones that aren't.
4. **Check (the oracle)** — call `detect_conflicts()` to *decide* whether the day
   clashes. This is a rule engine, not the model — the agent never trusts its own
   claim that a day is clean.
5. **Repair loop** — while conflicts remain: **decide** which task to move (keep
   the higher-priority one), **call** `find_next_available_slot()` to find a new
   time, move it, then **re-check**. Bounded so it always terminates.
6. **Score & explain** — rate confidence in the plan, then have the LLM narrate it.

## Trace 1 — a day with two conflicts (auto-repaired)

**Request:** *"I just got a puppy named Cooper. He needs a 30-minute walk at 8am,
feeding at 8am and 6pm, a vet visit at 3pm for 45 minutes, and a grooming session
at 3pm."*

Reasoning trace, captured verbatim from `agent_runs.log`:

```
2026-08-01 23:01:35 INFO [stub] input-guardrail: request accepted
2026-08-01 23:01:35 INFO [stub] parse: model proposed 5 task(s)
2026-08-01 23:01:35 INFO [stub] validate: 5 task(s) passed the guardrails
2026-08-01 23:01:35 INFO [stub] repair: Moved 'Walk' from 08:00 to 08:30 so it no longer clashes with 'Feed' (08:00).
2026-08-01 23:01:35 INFO [stub] repair: Moved 'Grooming' from 15:00 to 08:10 so it no longer clashes with 'Vet visit' (15:00).
2026-08-01 23:01:35 INFO [stub] verify: oracle confirms the day is conflict-free
2026-08-01 23:01:35 INFO [stub] confidence: plan confidence 1.00
2026-08-01 23:01:35 INFO [stub] explain: wrote plain-language explanation
```

**What the chain decided:** the oracle found two clashes (08:00 walk vs. feed;
15:00 grooming vs. vet). For each, the agent chose to move the *lower-priority*
task and called the slot-finder — walk → 08:30, grooming → 08:10 — then re-checked
until the oracle confirmed the day was clean. Confidence: **1.00** (no drops, no
warnings, fully resolved).

## Trace 2 — an impossible day (flagged, not faked)

**Request:** *"Walk Rex at 8am for 600 minutes and feed Rex at 8am for 600
minutes."* Two ten-hour tasks cannot both fit an 08:00–20:00 day.

```
INFO [stub] input-guardrail: request accepted
INFO [stub] parse: model proposed 2 task(s)
INFO [stub] validate: 2 task(s) passed the guardrails
WARNING [stub] repair: Couldn't fit 'Walk' anywhere between 08:00 and 20:00 — leaving the conflict flagged.
WARNING [stub] verify: 1 conflict(s) could not be resolved
INFO [stub] confidence: plan confidence 0.75
```

**What the chain decided:** the slot-finder returned `None` (no room), so instead
of pretending the day was clean, the agent **left the conflict flagged**, the
oracle reported it, and confidence dropped to **0.75**. This is the key property —
the agent is honest about what it *couldn't* do.

*(Reproduce either trace by running `python agent_cli.py "<request>"`, or
`python evaluate.py` for all seven scenarios; the live log is `agent_runs.log`.)*

