# I-Turn — Step 1 prototype

An open-ended conversation with a 3B model, with DASS-21 and the
Lifestyle R3 instrument layered underneath it. No commercial AI API, no
per-token cost.

The model does **not** run inside the app. The app is an HTTP client; the model
runs in a separate AI server at `AI_BASE_URL` — on your own GPU, or in a Google
Colab notebook so a laptop with no GPU can run everything else. See
[COLLABORATION.md](COLLABORATION.md). "Nothing leaves the machine" holds only
when that server is local.

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
app/                     the application — no model, no torch, no CUDA
  safety.py              risk detection — pre-model, deterministic, high recall
  session.py             orchestration; open conversation is the default state
  ai_client.py           HTTP client for the AI server; every failure -> AIError
  llm.py                 reply() / extract() on top of ai_client
  db.py                  SQLite: consent, turns, responses, scores, risk events
  prompts.py             system prompts; no covert-assessment instruction
  main.py                FastAPI
  instruments/
    dass21.py            verbatim items, scoring, bands
    lifestyle.py         slot schema for conversational extraction
static/index.html        open-ended chat UI
switch_ai.py             flip .env between your local AI server and Colab
ai_server/
  server.py              the AI server: HTTP contract + engines (transformers | ollama | stub)
collab/
  i-turn-ai-server.ipynb Colab notebook that runs ai_server/server.py behind a tunnel
  build_notebook.py      regenerates the notebook from ai_server/server.py
tests/                   pytest; mock AI server, no GPU needed
.env.example             AI_BASE_URL and friends
COLLABORATION.md         how to run the app with no GPU
```

## Stack, and why

| Layer | Choice | Reason |
|---|---|---|
| Model | Qwen2.5-3B-Instruct, Q4_K_M | Fits the 5050 with headroom. Strong Hindi/Kannada/Tamil for Phase 3 — that's the real reason over Llama-3.2-3B or Phi-3.5. |
| Serving | `ai_server/` over HTTP, engine `ollama` or `transformers` | The app only knows a URL. Ollama sidesteps Blackwell CUDA wheel problems locally; `transformers` is what runs in Colab and leaves room for LoRA. |
| Backend | FastAPI | Same stack as your other projects; sync endpoints are fine at this scale. |
| Storage | SQLite + WAL | Prototype only. Becomes Postgres the moment counsellors read dashboards while students are mid-session. |
| Frontend | Plain HTML/JS | No build step. Swap for Next.js when the counsellor dashboard arrives. |

"Qwen 2.5B" doesn't exist as a model — Qwen2.5 ships 0.5B / 1.5B / **3B** / 7B /
14B / 32B / 72B. Defaulting to 3B. If the 3B's empathic turns read flat,
`qwen2.5:7b-instruct-q4_K_M` is ~4.7 GB and still fits 8 GB; it's a
meaningful jump in conversational quality.

## Running it

Two processes: the **AI server** (holds the model) and the **app** (UI, backend,
database). Only `AI_BASE_URL` says where the first one is.

```bash
pip install -r requirements.txt          # the app: no torch, no CUDA
cp .env.example .env                     # then set AI_BASE_URL (and AI_API_KEY)
python -m uvicorn app.main:app --port 8000         # http://localhost:8000
```

### No GPU — model in Google Colab

Open `collab/i-turn-ai-server.ipynb` in Colab, pick a GPU runtime, run all, and
copy the `AI_BASE_URL` / `AI_API_KEY` it prints into `.env`. Full walkthrough in
[COLLABORATION.md](COLLABORATION.md).

### RTX 5050 (local) — model on this machine

The 5050 is Blackwell, compute capability **sm_120**. Any PyTorch built before
CUDA 12.8 will fail with `no kernel image is available for execution on the
device`. Ollama sidesteps this entirely, so it is the easy local route:

```bash
ollama pull qwen2.5:3b-instruct-q4_K_M
AI_ENGINE=ollama MODEL_NAME=qwen2.5:3b-instruct-q4_K_M python -m ai_server.server
# .env:  AI_BASE_URL=http://127.0.0.1:8001
```

Or load the weights directly (needs CUDA 12.8 wheels):
```bash
pip install torch --index-url https://download.pytorch.org/whl/cu128
pip install -r ai_server/requirements.txt
AI_ENGINE=transformers MODEL_NAME=Qwen/Qwen2.5-3B-Instruct python -m ai_server.server
```

### Switching between them

```bash
python switch_ai.py status | local | colab [--new]
```
Remembers each target's address and key and rewrites only the two AI lines of
`.env`. See [COLLABORATION.md](COLLABORATION.md#switching-between-your-own-model-and-colab).

### No model at all

```bash
AI_ENGINE=stub python -m ai_server.server
```
Canned model text, everything else real. Good enough to build the UI and the
counsellor dashboard against.

### Reading a counsellor briefing (development)

```bash
curl -H "Authorization: Bearer $ITURN_COUNSELLOR_TOKEN" \
  "http://localhost:8080/api/counsellor/<pseudonym>/<session_id>?text=true"
```
Story-mode sessions only: Incognito keeps nothing on disk to brief from.

### Tests

```bash
pip install -r requirements-dev.txt
pytest
```
No GPU, model, Colab or credentials needed.

## Environment

The app (`.env`, see `.env.example`):

| Var | Default | |
|---|---|---|
| `AI_BASE_URL` | `http://127.0.0.1:8001` | Where the AI server is. The only thing that changes between local and Colab. |
| `AI_API_KEY` | *(empty)* | Bearer key, if the AI server requires one. The Colab notebook generates one. |
| `AI_TIMEOUT` | `120` | Seconds to wait for one AI answer. |
| `AI_MODEL` | *(empty)* | Optional, advisory model identifier sent with requests. |
| `ITURN_COUNSELLOR_TOKEN` | *(empty)* | Bearer token for the counsellor / report / handoff / session-list / erase routes. Unset = those routes answer 503. |
| `ITURN_ENABLE_DOCS` | *(empty)* | `1` publishes `/docs`; off by default. |

The AI server (environment, see the docstring in `ai_server/server.py`):
`AI_ENGINE`, `MODEL_NAME`, `AI_API_KEY`, `HOST`, `PORT`, `LOAD_IN_4BIT`, `OLLAMA_URL`.

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

- **Counsellor login.** The routes that read or delete stored data (`/api/counsellor/*`,
  `/api/handoff/*`, `/api/report/*`, `/api/sessions/*`, `DELETE /api/data/*`) now need
  a shared bearer token (`ITURN_COUNSELLOR_TOKEN`) and answer 503 without one. That is a
  stopgap, not a login: one shared secret, no per-counsellor identity, no audit log of who
  opened what. Students still have no secret of their own, so "delete my data" is
  counsellor-mediated for now.
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
