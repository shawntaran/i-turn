"""
Switch which AI server I-Turn talks to, without hand-editing .env.

    python switch_ai.py status              which server is active, and is it up?
    python switch_ai.py local               your own machine (default http://127.0.0.1:8001)
    python switch_ai.py colab               the Colab endpoint saved last time
    python switch_ai.py colab --new         paste the banner from a fresh Colab run
    python switch_ai.py colab --url URL --key KEY

Each target remembers its own address and key in a git-ignored profile file
(.env.local, .env.colab). Switching copies that profile's two AI_* lines into
.env and leaves every other line alone. The app reads .env at startup, so
restart it — or run it with auto-reload and it restarts by itself:

    python -m uvicorn app.main:app --port 8080 --reload --reload-include .env

The API key is never printed.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
LOCAL_DEFAULT = "http://127.0.0.1:8001"     # not "localhost": ~2s slower per connection on Windows
KEYS = ("AI_BASE_URL", "AI_API_KEY")
_LINE = re.compile(r"^\s*(?:export\s+)?(AI_BASE_URL|AI_API_KEY)\s*=\s*(.*?)\s*$")


# ---------------------------------------------------------------------------
# Parsing and rewriting .env-style text
# ---------------------------------------------------------------------------

def _clean(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return value.strip()


def parse_pairs(text: str) -> dict[str, str]:
    """Pull AI_BASE_URL / AI_API_KEY out of any text: a .env file, or a whole
    pasted Colab banner with decoration around the two lines."""
    found: dict[str, str] = {}
    for line in text.splitlines():
        m = _LINE.match(line)
        if m and m.group(1) not in found:
            found[m.group(1)] = _clean(m.group(2))
    return found


def set_pairs(text: str, values: dict[str, str]) -> str:
    """Replace the AI_* lines in `text` (adding any that are missing), leaving
    comments, ordering and every other line — and the file's line endings — alone."""
    eol = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines()
    pending = dict(values)
    out: list[str] = []
    for line in lines:
        m = _LINE.match(line)
        if m:
            key = m.group(1)
            if key in pending:
                out.append(f"{key}={pending.pop(key)}")
            # a duplicate of an already-written key is dropped
            continue
        out.append(line)
    for key in KEYS:
        if key in pending:
            out.append(f"{key}={pending.pop(key)}")
    return eol.join(out) + eol


def classify(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    if host in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        return "local"
    if host.endswith(".trycloudflare.com"):
        return "colab"
    return "custom" if host else "unset"


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

def _write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="")
    os.replace(tmp, path)


def read_active(root: Path = ROOT) -> dict[str, str]:
    env = root / ".env"
    return parse_pairs(env.read_text(encoding="utf-8")) if env.exists() else {}


def load_profile(name: str, root: Path = ROOT) -> dict[str, str]:
    path = root / f".env.{name}"
    return parse_pairs(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_profile(name: str, url: str, key: str, root: Path = ROOT) -> None:
    _write(root / f".env.{name}", f"AI_BASE_URL={url}\nAI_API_KEY={key}\n")


def activate(url: str, key: str, root: Path = ROOT) -> None:
    env, example = root / ".env", root / ".env.example"
    base = (env.read_text(encoding="utf-8") if env.exists()
            else example.read_text(encoding="utf-8") if example.exists() else "")
    _write(env, set_pairs(base, {"AI_BASE_URL": url, "AI_API_KEY": key}))


# ---------------------------------------------------------------------------
# Talking to the server
# ---------------------------------------------------------------------------

def probe(url: str, key: str) -> tuple[str, str]:
    """('ok'|'loading'|'error'|'down', human-readable line). Uses the app's own
    client, so 'ok' here means the app will manage to connect too."""
    sys.path.insert(0, str(ROOT))
    from app.ai_client import AIClient, AIError
    client = AIClient(url, api_key=key, timeout=8, retries=0)
    try:
        h = client.health()
    except AIError as e:
        return "down", f"{e.message}  [{e.code}]"
    finally:
        client.close()
    model = h.get("model", "?")
    if h["status"] == "ok":
        return "ok", f"reachable, model {model} ({h.get('engine', '?')})"
    if h["status"] == "loading":
        return "loading", f"reachable but the model is still loading ({model})"
    return "error", f"reachable but the model failed to load: {h.get('detail', 'see the server log')}"


def _describe(url: str, key: str) -> str:
    host = urlsplit(url).netloc or url or "(not set)"
    return f"{classify(url)}  {host}   key: " + (f"set ({len(key)} chars)" if key else "none")


# ---------------------------------------------------------------------------
# Pasting the Colab banner
# ---------------------------------------------------------------------------

def paste_banner(stream=None, out=None) -> dict[str, str]:
    """Read lines until both AI_BASE_URL and AI_API_KEY have appeared."""
    stream = stream or sys.stdin
    out = out or sys.stdout
    print("Paste the AI_BASE_URL=... and AI_API_KEY=... lines from the Colab notebook's output\n"
          "(or the whole banner). It continues as soon as both are seen:", file=out)
    got: dict[str, str] = {}
    for line in stream:
        got.update({k: v for k, v in parse_pairs(line).items() if v})
        if all(k in got for k in KEYS):
            break
    return got


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def _report_and_hint(url: str, key: str, target: str, out) -> int:
    state, line = probe(url, key)
    print(f"  server: {line}", file=out)
    if state == "down" and target == "colab":
        print("  The saved Colab address is probably stale (tunnel URLs change every run).\n"
              "  Run the notebook again, then:  python switch_ai.py colab --new", file=out)
    elif state == "down" and target == "local":
        print("  Nothing is listening there yet. Start your local AI server, e.g.:\n"
              "    AI_ENGINE=ollama MODEL_NAME=qwen2.5:3b-instruct-q4_K_M python -m ai_server.server\n"
              "  (PowerShell: $env:AI_ENGINE='ollama'; $env:MODEL_NAME='qwen2.5:3b-instruct-q4_K_M'; "
              "python -m ai_server.server)", file=out)
    elif state == "down":
        print("  Check the address and that the server is running.", file=out)
    return 0


def cmd_status(root: Path, out) -> int:
    cur = read_active(root)
    url, key = cur.get("AI_BASE_URL", ""), cur.get("AI_API_KEY", "")
    print(f"active : {_describe(url, key)}", file=out)
    for name in ("local", "colab"):
        p = load_profile(name, root)
        print(f"saved  : {name:<6} " + (_describe(p.get("AI_BASE_URL", ""), p.get("AI_API_KEY", ""))
                                        if p else "(nothing saved yet)"), file=out)
    if url:
        _report_and_hint(url, key, classify(url), out)
    return 0


def cmd_switch(target: str, args, root: Path, out, stdin=None) -> int:
    if target == "local":
        prof = load_profile("local", root)
        url = args.url or prof.get("AI_BASE_URL") or LOCAL_DEFAULT
        key = args.key if args.key is not None else prof.get("AI_API_KEY", "")
    else:
        prof = load_profile("colab", root)
        if args.url:
            url, key = args.url, args.key if args.key is not None else ""
        elif args.new or not prof.get("AI_BASE_URL"):
            got = paste_banner(stdin, out)
            if len(got) < 2:
                print("Did not see both AI_BASE_URL and AI_API_KEY. Nothing was changed.", file=out)
                return 1
            url, key = got["AI_BASE_URL"], got["AI_API_KEY"]
        else:
            url, key = prof["AI_BASE_URL"], prof.get("AI_API_KEY", "")

    sys.path.insert(0, str(ROOT))
    from app.ai_client import normalise_base_url
    url = normalise_base_url(url)
    if not url.startswith(("http://", "https://")):
        print(f"'{url}' is not a valid address; it must start with https:// (or http://). "
              "Nothing was changed.", file=out)
        return 1
    if target == "colab" and not key:
        print("A Colab endpoint needs its API key (AI_API_KEY). Nothing was changed.", file=out)
        return 1

    # Switching away must not lose what was active. A hand-edited .env has no saved
    # profile yet, so keep the outgoing target before overwriting it.
    cur = read_active(root)
    cur_url, cur_key = cur.get("AI_BASE_URL", ""), cur.get("AI_API_KEY", "")
    outgoing = classify(cur_url)
    kept = outgoing in ("local", "colab") and outgoing != target and bool(cur_url)
    if kept:
        save_profile(outgoing, normalise_base_url(cur_url), cur_key, root)

    save_profile(target, url, key, root)
    activate(url, key, root)
    print(f"Switched to {target}: {_describe(url, key)}", file=out)
    if kept:
        print(f"  (kept your previous {outgoing} settings; switch back with: "
              f"python switch_ai.py {outgoing})", file=out)
    rc = _report_and_hint(url, key, target, out)
    print("Restart the app to apply (or run it with --reload --reload-include .env).", file=out)
    return rc


def main(argv: list[str] | None = None, out=None, stdin=None, root: Path = ROOT) -> int:
    out = out or sys.stdout
    ap = argparse.ArgumentParser(prog="switch_ai.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="show the active target and whether it is reachable")
    for name, help_ in (("local", "use the AI server on this machine"),
                        ("colab", "use the Google Colab AI server")):
        sp = sub.add_parser(name, help=help_)
        sp.add_argument("--url", help="address (skips the saved profile)")
        sp.add_argument("--key", help="API key (prefer pasting: shell history keeps this)")
        if name == "colab":
            sp.add_argument("--new", action="store_true", help="paste a fresh banner from Colab")
    args = ap.parse_args(argv)
    if args.cmd == "status":
        return cmd_status(root, out)
    return cmd_switch(args.cmd, args, root, out, stdin)


if __name__ == "__main__":
    sys.exit(main())
