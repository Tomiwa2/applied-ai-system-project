# PawPal+ Project Reflection

## 1. System Design

**a. Initial design**

- Briefly describe your initial UML design.
- What classes did you include, and what responsibilities did you assign to each?

My initial UML design has four classes, split between data objects (Owner, Pet, and Task) that hold state and a service object (Scheduler) that does work:

- **Owner** — represents a pet owner. It holds the owner's `name` and a list of
  their `pets`, and is responsible for managing that collection through
  `add_pet()` and `get_pets()`.

- **Pet** — represents a single pet. It holds the pet's `name`, `species`, and a
  list of care `tasks`, and is responsible for managing its own tasks via
  `add_task()` and `get_tasks()`.

- **Task** — represents one unit of pet care. It holds the task's `name`,
  `duration` (in minutes), and `priority`, and is responsible for describing and
  updating itself through `display_info()` and `update_details()`.

- **Scheduler** — the one behavior-focused class. It takes a list of
  `tasks_to_schedule` and an `available_time` budget, and is responsible for the
  scheduling logic: ordering tasks with `sort_tasks()` and producing a workable
  plan that fits the time budget with `generate_plan()`.

The responsibilities follow a clear ownership chain — an Owner owns Pets, a Pet
owns Tasks — while the Scheduler stays separate so the scheduling logic is
decoupled from the data it operates on.

**b. Design changes**

- Did your design change during implementation?
- If yes, describe at least one change and why you made it.

Yes, my design changed in a few ways once I started implementing and reviewing
the skeleton:

- **`priority` went from a plain string to a `Priority` enum.** Originally Task
  stored `priority` as a string like `"high"`. The problem is that sorting
  strings is alphabetical, so `"high"`, `"low"`, `"medium"` would sort in the
  wrong order and a typo like `"hgh"` would silently break the scheduler. I
  introduced a `Priority(IntEnum)` (HIGH=0, MEDIUM=1, LOW=2) so the scheduler can
  sort by real importance and invalid values are impossible.

- **I added a link from the Scheduler back to the data.** My first design left
  `Scheduler.tasks_to_schedule` as a loose list with no way to populate it from
  an Owner. I added `Owner.get_all_tasks()` (which flattens every task across all
  of the owner's pets) and a `Scheduler.from_owner()` constructor so the
  scheduler can actually pull the data instead of relying on the caller to wire
  it up by hand.

- **I gave each Task a back-reference to its Pet.** Originally the relationship
  was one-directional (Pet → Task), but the generated plan only returned tasks,
  so it couldn't say *which* pet a task belonged to. Adding a `pet` field lets
  `display_info()` show "Walk (for Rex)" in the final plan.

The biggest driver behind these changes was making the scheduler actually
functional: without a real priority ordering and a way to collect tasks, the two
core methods (`sort_tasks` and `generate_plan`) had nothing meaningful to work
with.

---

## 2. Scheduling Logic and Tradeoffs

**a. Constraints and priorities**

- What constraints does your scheduler consider (for example: time, priority, preferences)?
- How did you decide which constraints mattered most?

My scheduler weighs four constraints, and I deliberately ranked them rather than
treating them equally:

- **Time (the hard constraint).** Each task has a `start_time` and a `duration`,
  which I convert to minutes-since-midnight (`start_minutes`/`end_minutes`).
  Time is the backbone of the day: `sort_tasks()` orders the routine by start
  time, and `detect_conflicts()` uses the start/end range to flag overlaps.

- **The owner's single-resource limit.** The most important *real-world*
  constraint is that one owner can't be in two places at once, so any two timed
  tasks whose ranges overlap — even across different pets — are a conflict. This
  is what `detect_conflicts()` and `conflict_warnings()` exist to enforce.

- **Priority (a soft tie-breaker).** Tasks carry a `Priority` enum
  (HIGH/MEDIUM/LOW). Priority doesn't override the clock; it only breaks ties
  when two tasks compete for the same slot or when ordering unscheduled tasks,
  so a high-priority task surfaces first without rearranging fixed appointments.

- **Recurrence and completion (what belongs in *today's* plan).** `frequency`
  and `due_date` decide whether a task recurs and when its next occurrence
  lands, and `generate_plan()` drops completed tasks so the routine only shows
  what still needs doing.

I decided time mattered most because a daily routine is fundamentally a
timeline: if the clock is wrong, nothing else helps. Priority comes second as a
*tie-breaker* rather than a primary sort, because reordering a fixed 14:00 vet
visit ahead of an 08:00 walk just because it's "higher priority" would produce
an impossible schedule. Preferences (e.g. "morning person," preferred gaps
between tasks) were intentionally left out of scope for this version — they'd be
the natural next constraint to add, layered on top of the time/priority core.

**b. Tradeoffs**

- Describe one tradeoff your scheduler makes.
- Why is that tradeoff reasonable for this scenario?

One clear tradeoff is in how `Scheduler.detect_conflicts()` finds overlapping
tasks: it compares tasks **pairwise** (an O(n²) "check every pair" approach)
rather than using a faster data structure like an interval tree. I kept the
pairwise approach, but added two refinements to keep it honest:

- I sort the timed tasks by start time first, then **break out of the inner
  loop** as soon as a later task starts after the current one ends — since the
  list is sorted, nothing after it can overlap either. This keeps the common
  case closer to linear without changing the simple structure.
- A side effect of reporting *every* overlapping pair is redundancy: if three
  tasks all sit at 14:00, the owner sees three separate warnings (A–B, A–C,
  B–C) instead of one grouped "these three clash" message.

This tradeoff is reasonable here because a pet owner realistically has only a
handful of tasks per day, so the n² cost is negligible and the redundant
warnings are still readable. The simple, explicit loop is far easier to
understand and verify than a balanced interval tree would be, and the
readability matters more than raw speed at this scale. If the app ever scaled
to many pets with recurrence expanded across weeks, an interval-based approach
and de-duplicated warnings would become worth the added complexity.

A related, deliberate choice: conflict detection works on **wall-clock minutes
within a day** plus a same-day date check, rather than full datetime ranges. It
correctly catches overlapping *durations* (not just exact start-time matches —
an 08:00 30-minute walk conflicts with an 08:15 feed), but it assumes every
task fits inside a single day and treats an undated task as "any day," which can
produce a false-positive conflict against a dated one. That's an acceptable
simplification for a single-day pet-care planner.

---

## 3. AI Strategy

*My experience collaborating with an AI coding assistant (Claude Code) while
building PawPal+.*

**a. Which AI assistant features were most effective for building the scheduler?**

The features that helped most were the ones that kept the AI grounded in *my*
actual code rather than generic boilerplate:

- **Whole-repository context.** The assistant read `pawpal_system.py`,
  `main.py`, `app.py`, and the existing tests before changing anything, so its
  suggestions matched my real class names and method signatures instead of
  inventing new ones I'd have to reconcile.
- **Running the code in the loop.** It actually ran `pytest` and `python main.py`
  and used the genuine output. This caught a real bug the moment a generated test
  failed (see below) and meant the sample output in my README is captured, not
  invented.
- **Coordinated multi-file edits.** When I added methods like `filter_tasks()`
  and `conflict_warnings()`, the assistant updated the code, the UML diagram, and
  the README in one pass, so the three never drifted out of sync.
- **Tooling beyond text.** It rendered the Mermaid source to a PNG for the README
  and exercised the scheduler end-to-end, which would have been tedious by hand.

**b. One AI suggestion I rejected or modified to keep my system design clean.**

Early on, the AI leaned toward an **owner-centric design** — putting the
scheduling logic (sorting, conflict detection, plan generation) directly on the
`Owner` class, so the owner would both hold the data *and* do the work. I
rejected that. Folding scheduling into `Owner` would have turned it into a
"god object" that knew about times, priorities, and conflicts on top of just
managing pets, and it would have tangled the data model together with the
algorithm. Instead I kept the `Scheduler` as a separate service class and gave
`Owner` only one bridge method, `get_all_tasks()`, to hand over a flat task
list. The data objects (`Owner`, `Pet`, `Task`) just hold state; the
`Scheduler` is the single "brain." That separation of concerns is what lets me
swap or extend the scheduling logic without touching the data classes.

When wiring the Streamlit UI, the assistant could have reimplemented sorting and
filtering logic directly inside `app.py`. I rejected that and insisted the UI
stay a *thin layer* that calls the existing `Scheduler` methods
(`sort_tasks()`, `filter_tasks()`, `detect_conflicts()`) instead of duplicating
their logic. This kept all scheduling rules in one place (`pawpal_system.py`) so
the UI and the CLI behave identically and there's only one place to fix a bug.

A second, smaller modification: a generated test asserted
`set(conflicts[0]) == {a, b}`. Running it failed because `Task` is an
equality-based dataclass and therefore **unhashable**, so I rewrote the
assertion to use membership checks. That confirmed the value of verifying every
AI suggestion by actually running it.

**c. How separate chat sessions for different phases helped us stay organized.**

I used a different session for each phase — design/UML, core scheduling logic,
the test suite, the Streamlit UI, and documentation. Keeping phases separate
meant each conversation stayed focused on one goal, so the AI's context wasn't
polluted by unrelated earlier discussion and its answers stayed precise. It also
made the work easy to navigate: when I needed to revisit testing or the diagram,
that history was self-contained rather than buried inside one giant thread.

**d. What I learned about being the "lead architect" when working with powerful AI tools.**

The AI is fast and genuinely capable, but the architectural decisions stayed
mine — and they should. I set the core constraints (time as the hard constraint,
priority only as a tie-breaker), I decided where logic belonged (in the
`Scheduler`, not the UI), and at one point I deliberately paused the assistant
mid-edit to have it *describe* proposed UML changes before applying them, so I
approved each one rather than rubber-stamping a batch. My biggest takeaway is
that the AI accelerates *execution*, but direction, naming, tradeoff judgment,
and verification are the architect's job. Treating the AI as a fast collaborator
I supervise — not an autopilot — is what kept the system coherent.

---

## 4. AI Collaboration

**a. How you used AI**

- How did you use AI tools during this project (for example: design brainstorming, debugging, refactoring)?
- What kinds of prompts or questions were most helpful?

I used AI across every phase, but for different kinds of work:

- **Design brainstorming.** Early on I used it to pressure-test my class
  responsibilities — for example, talking through whether scheduling logic
  belonged on `Owner` or in a separate `Scheduler`, and why a `Priority` enum was
  safer than a plain string.
- **Test generation.** I had it draft the `pytest` suite for the highest-risk
  behaviors (sorting, recurrence, conflict detection) and then ran the tests to
  confirm they actually passed.
- **Refactoring and consistency.** When I added methods to the `Scheduler`, I used
  AI to propagate those changes across the code, the UML diagram, and the README
  so they stayed in sync.
- **Debugging and documentation.** I used it to capture real CLI output, render
  the Mermaid diagram to a PNG, and trace a confusing cross-day conflict warning
  back to undated tasks "floating" to any day.

The most helpful prompts were **specific and grounded in my actual files** —
e.g. "what are the most important edge cases to test for a scheduler with sorting
and recurring tasks?" or "does this UML still match the code?" — rather than
vague "write me a scheduler" requests. Asking *why* a change was suggested, and
asking it to explain a tradeoff before applying it, consistently produced better
results than asking it to just make the edit.

**b. Judgment and verification**

- Describe one moment where you did not accept an AI suggestion as-is.
- How did you evaluate or verify what the AI suggested?

When updating the UML diagram, the assistant was ready to apply a batch of edits
directly. I stopped it and asked it to first *list* the proposed changes and the
reason for each, so I could approve them one by one instead of rubber-stamping a
diff. Two of the changes (the `Task → Task` "spawns next occurrence" arrow and
the `Scheduler → Owner` dependency) were genuinely useful; reviewing them
deliberately is what let me confirm they reflected real interactions in my code
rather than noise.

I verified AI output in three ways: (1) **running it** — every test suite and
every `main.py` change was executed, which is how I caught that `Task` was an
unhashable dataclass; (2) **reading it against the source** — I cross-checked
suggested UML and README claims directly against `pawpal_system.py`; and
(3) **checking behavior end-to-end** — I confirmed the generated schedule, the
conflict warnings, and the recurrence date all matched what I expected for the
sample scenario before trusting the output.

---

## 5. Testing and Verification

**a. What you tested**

- What behaviors did you test?
- Why were these tests important?

My `pytest` suite (`tests/test_pawpal.py`, 10 tests, all passing) targets the
three highest-risk areas of the scheduler plus the core data objects:

- **Sorting correctness** — timed tasks come back in chronological order, ties at
  the same time are broken by priority (HIGH first), and unscheduled tasks sort
  last.
- **Recurrence logic** — completing a `daily` task spawns a pending copy dated one
  day later and attaches it to the same pet, while a `once` task never repeats.
- **Conflict detection** — two tasks at the *exact same time* are flagged, while
  back-to-back tasks that only touch at the boundary are **not** flagged, and
  completed tasks are ignored.
- **Data objects** — adding a task to a pet increases its task count, and
  `mark_complete()` flips a task's status.

These behaviors matter because they're exactly where the scheduler is easy to get
subtly wrong: an off-by-one in the overlap math, a string-vs-minutes sort bug, or
a recurrence that lands on the wrong date would all produce a plausible-looking
but incorrect plan. Testing the boundary cases (same-time vs. just-touching) pins
down the rules precisely rather than just checking the happy path.

**b. Confidence**

- How confident are you that your scheduler works correctly?
- What edge cases would you test next if you had more time?

I'm **moderately-to-highly confident (about 4 / 5)**. All 10 tests pass and they
cover the riskiest logic, including the key edge cases I called out. I also ran
`main.py` end-to-end and confirmed the sorted plan, conflict warnings, and
recurrence date all matched what I expected for a realistic multi-pet scenario.

I'm holding back the last point because several behaviors aren't directly tested
yet. With more time I would add:

- **Date-aware conflicts** — confirm a task dated *today* doesn't clash with one
  dated *tomorrow*, and that an **undated** task correctly "floats" to any day
  (the source of the cross-day warning I had to reason about).
- **Filtering** — `filter_tasks()` with each `completed` value, case-insensitive
  `pet_name`, and the two filters combined with AND.
- **Weekly recurrence and undated recurrence** — verify the `+7 day` step and that
  an undated recurring task anchors off today.
- **Input validation** — empty task names and non-positive durations should raise.
- **Multi-task conflicts** — three tasks at the same time should yield all three
  pairwise warnings without the sweep-line early-exit dropping any.

---

## 6. Reflection

**a. What went well**

- What part of this project are you most satisfied with?

I'm most satisfied with the **clean separation between the data model and the
scheduling logic**. Keeping `Owner`, `Pet`, and `Task` as plain state-holders and
putting all the real work in the `Scheduler` made everything downstream easier:
the CLI (`main.py`) and the Streamlit UI (`app.py`) are both thin layers over the
same engine, the test suite can exercise the logic in isolation, and the UML
diagram actually maps one-to-one onto the code. The conflict-detection logic is
the piece I'm proudest of — it's date-aware, handles the exact-same-time case,
and stays readable thanks to the sorted sweep-line early exit.

**b. What you would improve**

- If you had another iteration, what would you improve or redesign?

A few things I'd improve with another iteration:

- **De-duplicate conflict warnings.** Three tasks at the same time currently
  produce three separate pairwise warnings; I'd group them into a single
  "these clash" message so the owner isn't overwhelmed.
- **Tighten the undated-task rule.** Treating an undated task as "any day" can
  create a false-positive conflict against a dated one. I'd either default tasks
  to today's date or make the floating behavior explicit and opt-in.
- **Broaden test coverage.** I'd add the untested edges from Section 5 (filtering,
  weekly/undated recurrence, date-aware conflicts, and input validation) to push
  my confidence from 4/5 to 5/5.
- **Support owner preferences.** The natural next constraint — preferred gaps
  between tasks or "morning person" weighting — layered on top of the existing
  time/priority core.

**c. Key takeaway**

- What is one important thing you learned about designing systems or working with AI on this project?

My biggest takeaway is that **a clear separation of responsibilities is what makes
both the system and the AI collaboration manageable.** Because the design had
clean seams — data objects vs. a scheduling service — I could hand the AI small,
well-scoped tasks ("write tests for the sorter," "wire the UI to these methods")
and verify each one independently, instead of asking it to reason about the whole
app at once. Good architecture didn't just produce cleaner code; it made me a more
effective *director* of the AI, because I always knew exactly where a change
belonged and how to check that it was right.

---

<a name="final-project-reflection--ai-collaboration"></a>
## Final Project Reflection — AI Collaboration

*This section covers the AI 110 final project: extending PawPal+ into
**PawPal+ Copilot**, an agentic AI planner.*

### How I used AI during development

I used an AI assistant as a **design partner and pair-programmer** across the
whole build:

- **Prompting / design.** I described the goal ("let an owner plan a day in
  plain English, but keep the guarantees my scheduler already provides") and we
  worked out the core architecture together: an `LLMClient` interface with two
  backends, guardrails on both sides of the model, and a bounded repair loop.
- **Debugging.** When the offline stub only produced *one* feeding for "feed at
  7am **and** 6pm," the AI helped me trace it to my clause-splitting on the word
  "and," and we redesigned the parser to carry a stray time onto the current
  task.
- **Testing.** The AI drafted property tests (guardrails drop bad durations, the
  repair loop resolves a same-time clash) — and one of *those* tests was itself
  wrong (it used a pet name that appeared in the request, so the grounding check
  correctly considered it grounded), which was a useful reminder to read AI
  output critically rather than trust it.

### One helpful and one flawed AI suggestion

- **Most helpful:** the suggestion to make the deterministic `Scheduler` the
  *oracle* — the LLM proposes tasks, but `detect_conflicts()` alone decides
  whether the day is clash-free. This turned "trust the AI" into "verify the AI
  with code I already had," and it's the backbone of the whole reliability story.
- **Most flawed:** an early version of the plan had the LLM *report* whether the
  schedule had conflicts (asking it to return a `conflicts: []` field). That's
  exactly the kind of claim a model can get wrong or hallucinate. I rejected it
  and replaced it with the rule-based oracle + repair loop, so the model never
  gets to assert something the code can check for certain.

### System limitations & future improvements

- **The offline stub is a rule parser, not an understander.** It handles the
  common phrasings well and is deterministic (which is great for testing), but a
  real request with unusual wording is better served by the Claude backend. In
  particular, the stub attributes every task to a single detected pet, so a
  multi-pet request ("brush the cat too") can mis-assign the second pet.
- **Dates are simplified.** The agent plans a single conflict-free "today" and
  leaves `due_date` unset; the underlying scheduler is already date-aware, so a
  natural next step is resolving "Thursday 3pm" to a real date.
- **Future work:** multi-pet natural-language handling in the stub, a
  **confidence score** per plan (e.g. how much guessing the parser did), and a
  self-critique pass where a second model call reviews the final schedule for
  anything the rules can't catch (unrealistic ordering, missing rest time).

### Key takeaway

The most important thing I learned is that **the right role for an LLM in a
reliable system is "proposer," not "decider."** Everything trustworthy about
PawPal+ Copilot comes from pairing the model's flexibility (understanding messy
English) with the certainty of code I could verify (the scheduler). The AI is
genuinely useful *because* it is fenced in by guardrails and an oracle — not in
spite of them.
