# I-Turn — Step 1 prototype

An open-ended conversation with a local 3B model, with DASS-21 and the
Lifestyle R3 instrument layered underneath it. No cloud API, no per-token cost,
nothing leaves the machine.

Supersedes `Privacy_Aware_AI_Student_Wellbeing_System.ipynb` — keeps its
Story/Incognito modes, SQLite persistence, language switching and
Qwen2.5-3B-4bit, replaces the rest.

---

## The one architectural rule

**A 3B model does not own control flow.**

| Job | Who does it |
|---|---|
| Detecting risk in a message | `safety.py` — regex, no model, runs first |
| Deciding to escalate | `session.py` — a threshold, not a judgement call |
| Scoring DASS-21 | `instruments/dass21.py` — arithmetic |
| Assigning a severity band | `instruments/dass21.py` — a lookup table |
| Choosing the next question | `session.py` — fixed order |
| Writing a warm sentence | the model |
| Turning "yeah, most nights" into `sleep_hours: 4` | the model, then confirmed |

Every row above the line is deterministic, auditable, and reviewable by a
psychologist who doesn't read Python. That's what makes a small local model
defensible here — not the model's quality.

## Layout

```
app/
  safety.py              risk detection — pre-model, deterministic, high recall
  session.py             orchestration; open conversation is the default state
  llm.py                 ollama | transformers | stub backends
  db.py                  SQLite: consent, turns, responses, scores, risk events
  prompts.py             system prompts; no covert-assessment instruction
  main.py                FastAPI
  instruments/
    dass21.py            verbatim items, scoring, bands
    lifestyle.py         slot schema for conversational extraction
static/index.html        open-ended chat UI
tests_smoke.py           scoring boundaries, safety cases, session flow
```

## Stack, and why

| Layer | Choice | Reason |
|---|---|---|
| Model | Qwen2.5-3B-Instruct, Q4_K_M | Fits the 5050 with headroom. Strong Hindi/Kannada/Tamil for Phase 3 — that's the real reason over Llama-3.2-3B or Phi-3.5. |
| Serving | Ollama (llama.cpp) | Blackwell support works out of the box. `transformers` backend kept for Colab and future LoRA. |
| Backend | FastAPI | Same stack as your other projects; sync endpoints are fine at this scale. |
| Storage | SQLite + WAL | Prototype only. Becomes Postgres the moment counsellors read dashboards while students are mid-session. |
| Frontend | Plain HTML/JS | No build step. Swap for Next.js when the counsellor dashboard arrives. |

"Qwen 2.5B" doesn't exist as a model — Qwen2.5 ships 0.5B / 1.5B / **3B** / 7B /
14B / 32B / 72B. Defaulting to 3B. If the 3B's empathic turns read flat,
`qwen2.5:7b-instruct-q4_K_M` is ~4.7 GB and still fits 8 GB; it's a
meaningful jump in conversational quality.

## Running it

### RTX 5050 (local)

The 5050 is Blackwell, compute capability **sm_120**. Any PyTorch built before
CUDA 12.8 will fail with `no kernel image is available for execution on the
device`. Ollama sidesteps this entirely, which is the main reason it's the
default.

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5:3b-instruct-q4_K_M

pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
# http://localhost:8000
```

If you want the `transformers` path locally:
```bash
pip install torch --index-url https://download.pytorch.org/whl/cu128
pip install transformers accelerate bitsandbytes
ITURN_BACKEND=transformers uvicorn app.main:app --port 8000
```

### Colab

See `notebooks/iturn_colab.ipynb`. T4 handles 3B in 4-bit comfortably.

### No GPU

```bash
ITURN_BACKEND=stub uvicorn app.main:app --port 8000
python tests_smoke.py
```
Canned model text, everything else real. Good enough to build the UI and the
counsellor dashboard against.

## Environment

| Var | Default | |
|---|---|---|
| `ITURN_BACKEND` | `ollama` | `ollama` \| `transformers` \| `stub` |
| `ITURN_MODEL` | `qwen2.5:3b-instruct-q4_K_M` | Ollama tag |
| `ITURN_HF_MODEL` | `Qwen/Qwen2.5-3B-Instruct` | HF repo |
| `OLLAMA_URL` | `http://localhost:11434` | |

---

## What changed from the earlier notebook

1. **`'die'` removed from the crisis list.** It fired on "my phone died",
   "dying of boredom", "dying to finish this sem". A crisis screen that cries
   wolf gets dismissed, which is the only failure mode that actually costs
   someone something.
2. **`1-800-273-TALK` → Tele-MANAS `14416` / `1-800-891-4416`.** The old number
   is the pre-2022 US Lifeline (now 988) and was never relevant in Bengaluru.
   Campus numbers are `<< fill in >>` placeholders in `safety.py` — fill them
   before anyone demos this.
3. **`generate_summary()` deleted.** It returned "sustained academic stress,
   emerging sleep disruption" regardless of what was in the database. Replaced
   by `/api/handoff`, where every field traces to something that happened and
   empty sections render empty.
4. **Consent gates writes.** Story Mode is a recorded decision, sessions get
   real UUIDs (the old code hardcoded `session_id='session_active'`, merging
   every conversation a pseudonym ever had), and prior-session history no
   longer gets injected twice.
5. **No covert assessment.** The old system prompt asked the model to "weave
   questions naturally to understand their psychological state". That's an
   unconsented screening run by a 3B model. DASS-21 is now offered, declinable,
   and delivered verbatim.

## Why DASS-21 items are verbatim

Copyright Psychology Foundation of Australia — free to use, explicitly **not**
to modify. The severity cutoffs are norm-referenced to the exact items, the
exact 0–3 anchors, and the exact "past week" frame. A model inferring a rating
from someone's story produces a number that looks like a DASS score and isn't
one.

The Lifestyle R3 form is the department's own, carries no such constraint, and
*is* harvested conversationally. That split is where the "subtle" part of the
brief actually lives.

**Open item for the Psychology side:** Holistic Health Care Form 2 currently
labels the anchors NEVER / SOMETIMES / OFTEN / ALMOST ALWAYS. That's a
frequency scale; DASS-21 norms are built on a degree scale. Recommend reverting
the Google Form before pilot data collection — see the note in `dass21.py`.

## Not built yet, on purpose

- **Counsellor auth.** `/api/handoff` is wide open. Do not expose this.
- **Sessions are in-memory.** Restart the server, lose them.
- **The crisis alert doesn't fire.** `notify_counsellor: True` is a flag nobody
  reads yet. This is the single most important thing to build next, and it
  needs the counselling department's on-call protocol before a line of code.
- **Avatar anonymity.** Phase 2. Pre-generated avatar sets plus voice
  pitch-shifting is enough for a pilot; real-time generation is Phase 3.
- **Hindi/Kannada risk patterns.** `safety.py` is English-only. The language
  dropdown currently offers eight — meaning risk detection silently degrades in
  seven of them. Either restrict the dropdown to English for the pilot or write
  the patterns first.

## Decisions that are not engineering's to make

Flagging these because they're in the code as constants and someone will
assume they were reasoned through clinically. They weren't — they're
placeholders:

- `MIN_TURNS_BEFORE_OFFER = 6` in `session.py`
- `REFERRAL_BANDS = {"Severe", "Extremely severe"}` in `dass21.py`
- Every pattern in `safety.py`
- `CONCERN_RULES` thresholds in `lifestyle.py`
- Whether risk events survive a student's erasure request (`db.erase`) —
  currently yes, which needs explicit ethics committee sign-off and must be
  disclosed in the privacy notice, not buried

Dr. Dana's team owns all of the above.
