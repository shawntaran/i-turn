# Running I-Turn without a GPU

You can run the whole I-Turn app on an ordinary laptop — no NVIDIA card, no CUDA,
no model files — by letting **Google Colab** run the AI model for you.

```
   YOUR LAPTOP                                   GOOGLE COLAB (free GPU)
 ┌──────────────────┐     https://xxxx.trycloudflare.com    ┌───────────────────┐
 │ I-Turn           │ ────────────────────────────────────► │ AI server         │
 │  · UI            │        HTTP, needs AI_API_KEY          │  · PyTorch + CUDA │
 │  · backend       │ ◄──────────────────────────────────── │  · the model      │
 │  · database      │                                        │    you chose      │
 └──────────────────┘                                        └───────────────────┘
   no model, no GPU                                            notebook, not the UI
```

The app doesn't have a "Colab mode". It has one setting — `AI_BASE_URL` — and it
talks to whatever answers there. That could be your own GPU machine, a Colab
notebook, or anything else that speaks the same small HTTP API. **The UI is
identical in every case.**

> ### Read this first: privacy
> The original I-Turn design keeps everything on one machine. When you use Colab,
> the text a student types is sent over the internet, through a public tunnel, to
> a machine Google hosts. The tunnel address is random and every request must carry
> a secret key, but it is still not "nothing leaves the machine".
> **Use this for development and demos with made-up data. Don't put real students'
> conversations through it** unless your ethics approval says that's allowed.

---

## Step by step

You need: a laptop with **Python 3.10+** and **git**, and a **Google account**.

**1. Clone the project**
```bash
git clone https://github.com/shawntaran/i-turn.git
cd i-turn
```

**2. Switch to the `collab-compatible` branch**
```bash
git checkout collab-compatible
```

**3. Install the normal I-Turn dependencies**

These are small — no PyTorch, no CUDA.
```bash
python -m venv .venv
# macOS / Linux:            source .venv/bin/activate
# Windows (PowerShell):     .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**4. Open the notebook in Google Colab**

Go to <https://colab.research.google.com> → **File → Upload notebook** → choose
`collab/i-turn-ai-server.ipynb` from your clone. (If the repo is public you can
open it straight from GitHub instead.)

**5. Select a GPU runtime**

**Runtime → Change runtime type → T4 GPU → Save.**

**6. Choose a model (optional)**

In the **Configuration** cell, change `MODEL_NAME` if you want a different model.
The default, `Qwen/Qwen2.5-3B-Instruct`, works on the free GPU. See
[Choosing a model](#choosing-a-model) below.

**7. Run the notebook**

**Runtime → Run all.**

**8. Wait for the model to load**

The first run downloads the model, which can take a few minutes. The notebook
prints `server status: loading` and then `server status: ok`.

**9. Copy the public endpoint**

When it's ready, the last cell prints a block like this:

```
============================================================
i-turn AI SERVER
============================================================

Local endpoint:
http://127.0.0.1:8000

Public endpoint:
https://random-words-1234.trycloudflare.com

Set this in your i-turn .env:

AI_BASE_URL=https://random-words-1234.trycloudflare.com
AI_API_KEY=Xk3...long-random-string...9q
============================================================
```

**10. Put it in `.env`**

Back on your laptop, in the `i-turn` folder:
```bash
cp .env.example .env          # Windows PowerShell: Copy-Item .env.example .env
```
Open `.env` and paste the two lines from the notebook over the existing
`AI_BASE_URL=` and `AI_API_KEY=` lines. Leave everything else alone.

**11. Start I-Turn**
```bash
python -m uvicorn app.main:app --port 8000
```
On start-up it checks the AI server and tells you in the terminal whether it can
reach it.

**12. Use the exact same UI**

Open <http://localhost:8000>. It looks and behaves exactly as it always has.

**13. When you're done**

Stop the Colab runtime (**Runtime → Disconnect and delete runtime**). The public
address stops working immediately.

---

## Choosing a model

Change `MODEL_NAME` in the notebook's Configuration cell. Any Hugging Face
**instruction-tuned chat model** that fits on the GPU should work; the server
converts each model's output into the same response format, so I-Turn never needs
to know which one you picked.

| Model | Notes |
|---|---|
| `Qwen/Qwen2.5-3B-Instruct` | Default. Fits a free T4 comfortably. |
| `Qwen/Qwen2.5-7B-Instruct` | Set `LOAD_IN_4BIT = True` on a T4. |
| `mistralai/Mistral-7B-Instruct-v0.3` | Set `LOAD_IN_4BIT = True` on a T4. |
| `meta-llama/Llama-3.2-3B-Instruct` | *Gated.* Accept the licence on its Hugging Face page and set `HF_TOKEN`. |
| `google/gemma-2-2b-it` | *Gated.* As above. |

For gated models, either paste a Hugging Face token into `HF_TOKEN`, or — better,
because it never appears in the notebook — add a Colab **secret** named `HF_TOKEN`
(the key icon in Colab's left sidebar).

If the model won't load, the notebook stops and prints the reason. "Out of memory"
means the model is too big for the GPU: pick a smaller one or turn on
`LOAD_IN_4BIT`.

## The `.env` file

```ini
AI_BASE_URL=https://random-words-1234.trycloudflare.com   # from the notebook
AI_API_KEY=Xk3...                                          # from the notebook
AI_TIMEOUT=120                                             # seconds per AI answer
AI_MODEL=                                                  # optional, usually blank
```

Only `AI_BASE_URL` and `AI_API_KEY` normally change. `.env` is git-ignored — never
commit it, because the key is a secret.

**The tunnel address changes every time you restart the notebook**, so update
`AI_BASE_URL` each session.

## Troubleshooting

The app shows a plain-English message when the AI can't be reached; details go to
the terminal running `uvicorn`. You can also check the connection any time:

```bash
curl http://localhost:8000/api/ai/health
```

| What you see | What it means | Fix |
|---|---|---|
| *AI service unavailable. Check that the AI server … is running and that AI_BASE_URL is correct.* | Nothing is answering at `AI_BASE_URL`: notebook stopped, runtime disconnected, or old tunnel URL. | Re-run the notebook, copy the **new** URL into `.env`, restart I-Turn. |
| *AI_BASE_URL is not a valid URL.* | Typo — must start with `https://` (or `http://`). | Fix `.env`. |
| *The AI service rejected the request. Check that AI_API_KEY matches …* | Key in `.env` isn't the one the notebook printed. | Copy `AI_API_KEY=` from the notebook again. |
| *The AI model is still loading.* | Notebook is still downloading/loading. | Wait for `server status: ok` in Colab. |
| *The AI model failed to load on the AI server.* | Wrong model name, gated model without a token, or not enough memory. | Read the error the notebook printed. |
| *The AI server ran out of GPU memory.* | Model too big for this GPU. | Smaller model, `LOAD_IN_4BIT = True`, or **Runtime → Restart session**. |
| *The AI service took too long to respond.* | Very slow generation or a stalled connection. | Try again; raise `AI_TIMEOUT` if you're using a large model. |
| *The connection to the AI service was interrupted.* | Network blip or Colab restarted the runtime. | Try again; if it persists, re-run the notebook. |

A failed message is not lost or half-saved: the app rolls the turn back, so you
can just send it again.

## Switching between your own model and Colab

You shouldn't have to hand-edit `.env` every time. `switch_ai.py` remembers one
address per target and flips between them:

```bash
python switch_ai.py status               # what am I using, and is it up?
python switch_ai.py local                # your own machine (http://127.0.0.1:8001)
python switch_ai.py colab                # the Colab address you used last time
python switch_ai.py colab --new          # paste the banner from a fresh Colab run
```

`colab --new` waits for you to paste the `AI_BASE_URL=…` and `AI_API_KEY=…` lines
from the notebook (or the whole banner — it finds them) and carries on the moment
it has both. It rewrites only those two lines of `.env`, checks the server is
reachable, and tells you if it isn't. Your key is never printed. The saved
addresses live in `.env.local` and `.env.colab`, which are git-ignored.

The app reads `.env` when it starts. Run it like this and it restarts by itself
whenever `switch_ai.py` changes the file:

```bash
python -m uvicorn app.main:app --port 8080 --reload --reload-include .env
```

(Restarting drops any in-progress chat, since sessions live in memory — fine for
development. Without `--reload`, press Ctrl+C and start it again.)

A typical day:

| You want to… | Do this |
|---|---|
| Use Colab (first time today) | Run the notebook, then `python switch_ai.py colab --new` and paste |
| Go back to your local model | Start it (`python -m ai_server.server`, see below), then `python switch_ai.py local` |
| Colab timed out / new tunnel URL | Re-run the notebook, then `python switch_ai.py colab --new` |
| Check which one is live | `python switch_ai.py status` |

## Other ways to run the AI server

The AI server is one file, [`ai_server/server.py`](ai_server/server.py). Colab is
just one place to run it. Configuration is via environment variables (see the
docstring at the top of the file).

**On your own GPU machine** (also the setup for "everything local"):
```bash
pip install -r ai_server/requirements.txt          # torch: see pytorch.org for your CUDA
AI_ENGINE=transformers MODEL_NAME=Qwen/Qwen2.5-3B-Instruct python -m ai_server.server
# then in .env:  AI_BASE_URL=http://127.0.0.1:8001
```

**With Ollama** already installed:
```bash
ollama pull qwen2.5:3b-instruct-q4_K_M
AI_ENGINE=ollama MODEL_NAME=qwen2.5:3b-instruct-q4_K_M python -m ai_server.server
```

**With no model at all** — canned replies, for working on the UI or the state machine:
```bash
AI_ENGINE=stub python -m ai_server.server
```

In each case only `AI_BASE_URL` in the app's `.env` differs.

### The API, if you want to write your own server

Anything that implements this can sit behind `AI_BASE_URL`:

`POST /v1/generate`
```json
{ "messages": [{"role": "user", "content": "hi"}],   "prompt": null,
  "system_prompt": "...", "temperature": 0.6, "top_p": 0.9, "max_tokens": 220,
  "repeat_penalty": 1.1, "json_mode": false, "model": null }
```
Send `messages` **or** `prompt`, not both. Response:
```json
{ "text": "...", "model": "...", "finish_reason": "stop",
  "usage": {"input_tokens": 12, "output_tokens": 7} }
```
`GET /health` → `{"status": "ok" | "loading" | "error", "model": "..."}` (HTTP 200
only when `ok`). If a key is configured, send `Authorization: Bearer <key>`.
Errors are `{"error": {"code": "...", "message": "..."}}`.

## How the connection copes with a flaky tunnel

Free tunnels blip. The app handles the common cases so you don't see them:

- **Brief drops are retried.** A connection reset, or Cloudflare answering
  502/520–523/525–530 while the tunnel reconnects, is retried twice (after 1 s and
  3 s) before an error reaches the chat.
- **Things that can't get better are not retried:** a wrong key, a wrong address,
  a model that's still loading or out of memory, a request that already timed out.
- **Typos in `AI_BASE_URL` are forgiven:** quotes, spaces, a trailing `/`, or a
  pasted `/health` or `/v1/generate` are stripped, and `http://` on a
  `trycloudflare.com` address is upgraded to `https://` so the key is never sent
  in the clear.
- **Cloudflare's 100-second limit** (error 524) is reported as "took too long",
  not "unavailable".

## Running the tests (no GPU needed)

```bash
pip install -r requirements-dev.txt
pytest
```

The tests use a mock AI server on localhost. They need no GPU, no CUDA, no model
weights, no Colab and no accounts or API keys.

If you edit `ai_server/server.py`, regenerate the notebook (a test fails if you
forget):
```bash
python collab/build_notebook.py
```

## Limitations worth knowing

- **Free Colab isn't permanent.** Runtimes disconnect when idle and after roughly
  12 hours; the tunnel URL changes on every restart. Fine for development, not for
  a pilot with real students.
- **Speed.** Each message makes two calls to the model (one to pick out lifestyle
  details, one for the reply), each crossing the internet. Expect replies to be
  slower than a local GPU.
- **The tunnel** is a free Cloudflare "quick tunnel": no uptime guarantee, and it
  drops a request that takes longer than about 100 seconds.
- **One conversation at a time** is processed on the GPU; simultaneous users queue.
- **Privacy**, as above: conversation text leaves the laptop.
