# Model Card — PawPal+ Copilot

*Responsible-AI reflection for the AI 110 final project. This is the graded
reflection document; the README links here rather than duplicating it.*

## System summary

**PawPal+ Copilot** turns a pet owner's plain-English request into a validated,
conflict-free daily care schedule. An LLM (the **Claude API**, or a deterministic
offline **stub** when no API key is present) *proposes* tasks; a rule-based
`Scheduler` then **decides** whether the day conflicts and repairs any clashes.

- **Intended use:** a low-stakes personal planning aid for pet care (walks,
  feeding, grooming, play, and reminders about vet/medication times the owner
  already knows).
- **Not intended for:** medical advice, dosing decisions, or any use where a
  missed or wrong time causes harm. It plans the times the owner gives it; it
  does not decide what care a pet needs.
- **Components:** `agent/` (guardrails, LLM client, planner loop),
  `pawpal_system.py` (the scheduler/oracle), `evaluate.py` (reliability harness),
  `tests/` (32 tests).

---

## 1. Limitations and biases

**Limitations**

- **The offline stub is a keyword parser, not a real understander.** It handles
  common phrasings well and is deterministic (great for testing), but it detects
  a **single pet** per request — a second pet ("…and brush the cat too") is
  mis-attributed to the one pet it found. Unusual wording can yield no tasks.
- **No real dates.** The agent plans a single "today" and leaves `due_date`
  unset, so it ignores "on Thursday." The underlying scheduler is already
  date-aware, so this is a limitation of the agent layer, not the engine.
- **"Conflict-free" ≠ "sensible."** A conflict means only "the owner can't be in
  two places at once" (any time overlap). The system does not model travel time,
  rest between tasks, or task order, so a technically conflict-free plan can still
  be impractical (e.g., it may place grooming at 08:10 simply because that's the
  earliest free gap).
- **The repair heuristic is greedy, not optimal.** It moves the lower-priority
  task to the *earliest* free slot. This always terminates and is easy to explain,
  but it isn't a globally optimal schedule.
- **Backend variability.** With the Claude backend, output quality depends on the
  model and can vary between runs; the stub is reproducible but less capable.
  Results differ depending on which backend is active.

**Biases**

- **Baked-in priority and duration defaults.** Task keywords map to hard-coded
  priorities and durations (vet/medication = high; play/grooming = low; a walk
  defaults to 30 minutes, feeding to 10, a vet visit to 45). These encode *my*
  assumptions about what matters and how long things take. An owner whose
  priorities differ — say, enrichment is critical for their animal — is nudged by
  weights they never chose. The Claude backend can override durations and times
  stated in the request, but the default *priority* ranking still reflects a
  particular, Western, dog-and-cat-centric view of "normal" pet care.
- **Species coverage.** Detection and defaults are tuned for dogs and cats; other
  animals fall back to generic handling.

---

## 2. Could the AI be misused, and how is that prevented?

This is a low-stakes tool, but honestly assessing the risks:

- **Over-reliance for medication timing.** The most real risk is a user trusting
  the schedule for *medication* and a wrong/missed time mattering. **Prevention:**
  the system never invents a medication task (the grounding check drops tasks not
  traceable to the request), the model never decides *what* care is needed (only
  arranges times the owner supplied), and the docs frame it as a planning aid, not
  medical advice. A natural next guard is an explicit "not medical advice"
  disclaimer surfaced on medication tasks.
- **Adversarial or junk input.** A user could paste an enormous or malicious
  string. **Prevention:** the input guardrail caps length (2,000 chars) and
  rejects empty/no-word input *before* any API call; the output guardrail only
  accepts proposals that construct a valid `Task`, so malformed model output can't
  reach the scheduler or the saved `data.json`.
- **Hallucinated tasks.** The model could add tasks the owner never asked for.
  **Prevention:** the grounding / anti-hallucination check flags tasks with no
  basis in the request, and — crucially — the deterministic **oracle**, not the
  model, decides whether the day is conflict-free, so the model cannot fabricate a
  "clean" schedule to look good.
- **API-key / cost abuse.** A leaked key could run up API charges. **Prevention:**
  the key lives only in `.env` (git-ignored; `.env.example` is the tracked
  template), the parse step runs at low effort to limit token use, and the whole
  system runs offline on the stub with no key at all.

---

## 3. What surprised me while testing reliability

- **The scariest failures looked like successes.** Splitting the request on the
  word "and" made *"feed at 7am **and** 6pm"* silently produce only **one**
  feeding — no error, no crash, just a quietly wrong plan. Nothing flagged it; the
  run "passed." That reframed reliability for me: the dangerous bugs aren't the
  ones that throw, they're the ones that return something plausible and wrong.
- **My tests needed testing.** One AI-drafted test asserted a "hallucination"
  warning that never fired — because the test used a pet name that *did* appear in
  the request, so the grounding check correctly considered the task grounded. The
  code was right and the *test's assumption* was wrong. I learned to check the
  premise of a test, not just its green checkmark.
- **A deterministic oracle made reliability provable, not hopeful.** Once
  conflicts were decided by code instead of by the model, "is this plan actually
  clean?" became a hard yes/no I could `assert` in `evaluate.py`. I was surprised
  how well the greedy repair loop then converged — it resolves even three-task
  10 a.m. pile-ups to a conflict-free day.

---

## 4. Collaboration with AI on this project

I used an AI assistant as a design partner and pair-programmer throughout —
sketching the architecture, drafting code and tests, and debugging.

- **One helpful suggestion:** the AI proposed the **"LLM proposes, rules decide"**
  architecture — making the deterministic `Scheduler` the *oracle* so the model
  never asserts a clean day. That single idea is the backbone of the entire
  reliability story and is what lets `evaluate.py` prove correctness rather than
  assume it.

- **One flawed suggestion:** an early AI design had the **LLM itself report**
  whether the schedule had conflicts (return a `conflicts: []` field in its
  output). That is exactly the kind of claim a model can get wrong or hallucinate
  — trusting it would have defeated the whole point. I rejected it and replaced it
  with the rule-based oracle plus the repair loop, so the model never gets to
  assert something the code can verify for certain.

**Takeaway:** the right role for an LLM in a reliable system is **"proposer," not
"decider."** Everything trustworthy about PawPal+ Copilot comes from pairing the
model's flexibility (understanding messy English) with the certainty of code I
could verify. The AI is useful *because* it is fenced in by guardrails and an
oracle — not in spite of them.
