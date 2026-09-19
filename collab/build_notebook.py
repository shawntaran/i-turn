"""
Builds collab/i-turn-ai-server.ipynb.

The notebook embeds ai_server/server.py verbatim (as a %%writefile cell) so it is
self-contained: someone can open just the notebook in Colab, with no clone of
this repository. Generating it from the real file means the server a developer
runs in Colab is byte-for-byte the server the test suite exercises.

    python collab/build_notebook.py           # regenerate the notebook
    python collab/build_notebook.py --check   # exit 1 if it is out of date

tests/test_notebook.py runs the --check, so editing ai_server/server.py without
rebuilding fails the suite.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER_SRC = ROOT / "ai_server" / "server.py"
NOTEBOOK = ROOT / "collab" / "i-turn-ai-server.ipynb"

# ---------------------------------------------------------------------------
# Cell sources. Only CONFIG is meant to be edited by the user.
# ---------------------------------------------------------------------------

INTRO = """\
# I-Turn AI server (Google Colab)

This notebook runs **only the AI model**, behind a small HTTP API. The I-Turn
app itself (UI, backend, database) runs on your laptop and talks to this
notebook over the internet through a tunnel. The app needs no GPU, no CUDA and
no model weights.

```
  your laptop                                       this Colab runtime
  ┌────────────────────┐   https://xxxx.trycloudflare.com   ┌──────────────────┐
  │ I-Turn UI + backend│ ─────────────────────────────────► │ AI server + model│
  └────────────────────┘        AI_BASE_URL / AI_API_KEY     └──────────────────┘
```

**Steps**

1. **Runtime → Change runtime type → GPU** (a free T4 is enough for a 3B model).
2. Optionally change the model in the *Configuration* cell.
3. **Runtime → Run all.** Loading the model takes a few minutes the first time.
4. Copy the two lines printed at the bottom (`AI_BASE_URL=…` and `AI_API_KEY=…`)
   into the `.env` file of your I-Turn checkout, then start I-Turn as usual.

> **Privacy.** While this is running, whatever the app sends to the model
> travels over a public tunnel to a Google-hosted machine. Use it with test
> data, not with real students' conversations, unless your ethics approval
> covers it. The tunnel URL is unguessable and every request needs the API key,
> but stop the runtime when you're done.
"""

CONFIG_MD = """\
## 1 · Configuration

This is the only cell you should need to edit.

**Choosing a model.** Set `MODEL_NAME` to any Hugging Face instruction-tuned
chat model that fits the GPU. The server normalises whatever the model produces
into the same API response, so I-Turn doesn't care which one you pick.

| Model | Notes |
|---|---|
| `Qwen/Qwen2.5-3B-Instruct` | default; fits a free T4 comfortably |
| `Qwen/Qwen2.5-7B-Instruct` | set `LOAD_IN_4BIT = True` on a T4 |
| `mistralai/Mistral-7B-Instruct-v0.3` | set `LOAD_IN_4BIT = True` on a T4 |
| `meta-llama/Llama-3.2-3B-Instruct` | gated: accept the licence on Hugging Face, then set `HF_TOKEN` |
| `google/gemma-2-2b-it` | gated: as above |

`HF_TOKEN` can also be stored as a Colab **secret** named `HF_TOKEN` (key icon in
the left sidebar) so it never appears in the notebook.
"""

CONFIG = '''\
#@title Configuration
MODEL_NAME = "Qwen/Qwen2.5-3B-Instruct"  #@param {type:"string"}
PORT = 8000                              #@param {type:"integer"}
LOAD_IN_4BIT = False                     #@param {type:"boolean"}
API_KEY = ""                             #@param {type:"string"}
HF_TOKEN = ""                            #@param {type:"string"}
# API_KEY: leave empty and a random one is generated and printed for you.
# HF_TOKEN: only for gated models (Llama, Gemma); or use a Colab secret.
'''

IMPL_MD = """\
## 2 · Implementation

Nothing below needs editing. It installs dependencies, starts the AI server,
loads the model, opens a tunnel and prints the values to put in your `.env`.
"""

INSTALL = """\
# torch and CUDA are preinstalled in Colab; only the serving/model libraries are needed.
!pip install -q -U fastapi "uvicorn[standard]" httpx pydantic "transformers>=4.44" accelerate bitsandbytes
"""

GPU_CHECK = '''\
import torch

if not torch.cuda.is_available():
    raise RuntimeError(
        "No GPU is attached to this runtime. Use Runtime -> Change runtime type -> GPU, "
        "then Runtime -> Run all again."
    )
print("GPU:", torch.cuda.get_device_name(0),
      f"({torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB)")
'''

START_SERVER = '''\
import errno, json, os, secrets, socket, subprocess, sys, time, urllib.error, urllib.request

LOAD_TIMEOUT_MIN = 30


def _stop(proc):
    if proc is not None and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()


def _port_in_use(port):
    # Free only if the connection is actively refused; anything else (accepted,
    # or a busy listener that stops answering) means something is already there.
    with socket.socket() as sock:
        sock.settimeout(4)                    # Windows can take ~2s to report a refusal
        return sock.connect_ex(("127.0.0.1", port)) not in (errno.ECONNREFUSED, 10061)


_stop(globals().get("server_proc"))          # so this cell can be re-run safely
for _ in range(8):                            # give the old one a moment to release the port
    if not _port_in_use(PORT):
        break
    time.sleep(0.5)
else:
    raise RuntimeError(
        f"Port {PORT} is already in use, probably by an earlier run of this notebook. "
        "Change PORT in the Configuration cell, or use Runtime -> Restart session and run again.")

AI_API_KEY = API_KEY.strip() or secrets.token_urlsafe(24)
env = {
    **os.environ,
    "AI_ENGINE": "transformers",
    "MODEL_NAME": MODEL_NAME,
    "HOST": "127.0.0.1",
    "PORT": str(PORT),
    "AI_API_KEY": AI_API_KEY,
    "LOAD_IN_4BIT": "1" if LOAD_IN_4BIT else "0",
}
hf_token = HF_TOKEN.strip()
if not hf_token:
    try:
        from google.colab import userdata
        hf_token = userdata.get("HF_TOKEN") or ""
    except Exception:
        pass
if hf_token:
    env["HF_TOKEN"] = hf_token

server_proc = subprocess.Popen(
    [sys.executable, "ai_server.py"], env=env,
    stdout=open("ai_server.log", "w"), stderr=subprocess.STDOUT,
)


def local_health():
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}/health", headers={"Authorization": f"Bearer {AI_API_KEY}"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:      # 503 while loading / failed still carries a status body
        try:
            return json.load(e)
        except Exception:
            return None
    except Exception:
        return None


def _log_tail():
    return open("ai_server.log").read()[-3000:]


print(f"Starting the AI server and loading {MODEL_NAME} (first run downloads the weights)...")
deadline, last = time.time() + LOAD_TIMEOUT_MIN * 60, None
while time.time() < deadline:
    if server_proc.poll() is not None:
        print(_log_tail())
        raise RuntimeError("The AI server process exited. The log above says why.")
    h = local_health()
    status = (h or {}).get("status")
    if isinstance(h, dict) and isinstance(h.get("error"), dict) and h["error"].get("code") == "unauthorized":
        raise RuntimeError("Something else is answering on this port with a different API key. "
                           "Change PORT, or Runtime -> Restart session, and run again.")
    if status != last:
        print(f"[{time.strftime('%H:%M:%S')}] server status: {status or 'starting'}")
        last = status
    if status == "ok":
        break
    if status == "error":
        print(_log_tail())
        raise RuntimeError(f"The model failed to load: {h.get('detail')}")
    time.sleep(3)
else:
    print(_log_tail())
    raise TimeoutError(f"The model did not finish loading within {LOAD_TIMEOUT_MIN} minutes.")

print("Model loaded:", h["model"])
'''

TUNNEL = '''\
import re

# A Cloudflare "quick tunnel": free, no account, gives a public https URL.
CLOUDFLARED = "./cloudflared"
CLOUDFLARED_URL = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64"

if not os.path.exists(CLOUDFLARED):
    for attempt in range(1, 4):
        try:
            urllib.request.urlretrieve(CLOUDFLARED_URL, CLOUDFLARED)
            os.chmod(CLOUDFLARED, 0o755)
            break
        except Exception as e:
            print(f"cloudflared download failed (attempt {attempt}/3): {e}")
            time.sleep(3)
    else:
        raise RuntimeError("Could not download cloudflared from GitHub. Check Colab's internet "
                           "access and re-run this cell.")
print(subprocess.run([CLOUDFLARED, "--version"], capture_output=True, text=True).stdout.strip())

PUBLIC_URL = None
for attempt in range(1, 4):
    _stop(globals().get("tunnel_proc"))
    tunnel_proc = subprocess.Popen(
        [CLOUDFLARED, "tunnel", "--url", f"http://127.0.0.1:{PORT}", "--no-autoupdate"],
        stdout=open("cloudflared.log", "w"), stderr=subprocess.STDOUT,
    )
    for _ in range(45):
        m = re.search(r"https://[a-z0-9-]+\\.trycloudflare\\.com", open("cloudflared.log").read())
        if m:
            PUBLIC_URL = m.group(0)
            break
        if tunnel_proc.poll() is not None:
            break
        time.sleep(1)
    if PUBLIC_URL:
        break
    print(f"No tunnel URL yet (attempt {attempt}/3); trying again...")
    time.sleep(3)

if not PUBLIC_URL:
    print(open("cloudflared.log").read()[-3000:])
    raise RuntimeError("cloudflared did not produce a public URL after 3 tries. The log above "
                       "says why (a 429 means Cloudflare is rate-limiting free tunnels; wait a "
                       "few minutes and re-run this cell).")

# The URL can take a few seconds to start resolving; confirm it reaches the server.
reachable = False
for _ in range(30):
    try:
        req = urllib.request.Request(
            PUBLIC_URL + "/health",
            headers={"Authorization": f"Bearer {AI_API_KEY}", "User-Agent": "i-turn-notebook"})
        with urllib.request.urlopen(req, timeout=10) as r:
            reachable = r.status == 200
        if reachable:
            break
    except Exception:
        pass
    time.sleep(2)
print("Tunnel is reachable from the internet." if reachable else
      "Tunnel URL created but not answering yet; give it a minute before using it.")
'''

BANNER = '''\
def show_banner():
    print("=" * 60)
    print("i-turn AI SERVER")
    print("=" * 60)
    print()
    print("Local endpoint:")
    print(f"http://127.0.0.1:{PORT}")
    print()
    print("Public endpoint:")
    print(PUBLIC_URL)
    print()
    print("Model:", MODEL_NAME)
    print()
    print("Set this in your i-turn .env:")
    print()
    print(f"AI_BASE_URL={PUBLIC_URL}")
    print(f"AI_API_KEY={AI_API_KEY}")
    print("=" * 60)


show_banner()
'''

MONITOR_MD = """\
## 3 · Keep it running (optional)

The server keeps running after the cells above finish, for as long as this
runtime stays connected. This cell just watches it and reprints the values;
interrupt it (■) when you're done. Colab may disconnect an idle runtime, and the
public URL changes every time the tunnel restarts, so update `AI_BASE_URL` if
you re-run.
"""

MONITOR = '''\
try:
    while True:
        h = local_health()
        tunnel_up = tunnel_proc.poll() is None
        print(f"[{time.strftime('%H:%M:%S')}] server: {(h or {}).get('status', 'DOWN')}"
              f" | tunnel: {'up' if tunnel_up else 'DOWN'}")
        time.sleep(60)
except KeyboardInterrupt:
    show_banner()
'''


def _lines(src: str) -> list[str]:
    return src.splitlines(keepends=True)


def _md(id_: str, src: str) -> dict:
    return {"cell_type": "markdown", "id": id_, "metadata": {}, "source": _lines(src)}


def _code(id_: str, src: str) -> dict:
    return {"cell_type": "code", "id": id_, "metadata": {}, "execution_count": None,
            "outputs": [], "source": _lines(src)}


def build() -> dict:
    server = SERVER_SRC.read_text(encoding="utf-8").replace("\r\n", "\n")
    cells = [
        _md("intro", INTRO),
        _md("config-md", CONFIG_MD),
        _code("config", CONFIG),
        _md("impl-md", IMPL_MD),
        _code("install", INSTALL),
        _code("gpu", GPU_CHECK),
        _code("server-source", "%%writefile ai_server.py\n" + server),
        _code("start-server", START_SERVER),
        _code("tunnel", TUNNEL),
        _code("banner", BANNER),
        _md("monitor-md", MONITOR_MD),
        _code("monitor", MONITOR),
    ]
    return {
        "cells": cells,
        "metadata": {
            "accelerator": "GPU",
            "colab": {"name": "i-turn-ai-server.ipynb", "gpuType": "T4", "provenance": []},
            "kernelspec": {"display_name": "Python 3", "name": "python3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def render() -> str:
    return json.dumps(build(), indent=1, ensure_ascii=False) + "\n"


def main(argv: list[str]) -> int:
    text = render()
    if "--check" in argv:
        current = NOTEBOOK.read_text(encoding="utf-8") if NOTEBOOK.exists() else ""
        if current.replace("\r\n", "\n") != text:
            print(f"{NOTEBOOK.name} is out of date. Run: python collab/build_notebook.py")
            return 1
        print(f"{NOTEBOOK.name} is up to date.")
        return 0
    NOTEBOOK.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {NOTEBOOK}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
