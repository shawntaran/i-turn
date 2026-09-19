"""
Environment loading, in one place.

A `.env` file at the repository root is read once; real environment variables
win over it. Both the AI client and the API layer call load_env() so neither
depends on the other having run first.
"""

from __future__ import annotations

from pathlib import Path

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
_loaded = False


def load_env() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    try:
        from dotenv import load_dotenv
        load_dotenv(_ENV_FILE, override=False)
    except ImportError:  # python-dotenv is a convenience, not a requirement
        pass
