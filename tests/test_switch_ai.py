"""
switch_ai.py: flipping between a local AI server and Colab without hand-editing
.env. Every test runs in a throwaway directory; the repo's real .env is never
touched.
"""

import io
from pathlib import Path

import pytest

import switch_ai
from tests.conftest import free_port

SECRET = "Zx9-very-secret-key-do-not-print"

BANNER = f"""
============================================================
i-turn AI SERVER
============================================================

Local endpoint:
http://127.0.0.1:8000

Public endpoint:
https://random-words-1234.trycloudflare.com

Model: Qwen/Qwen2.5-3B-Instruct

Set this in your i-turn .env:

AI_BASE_URL=https://random-words-1234.trycloudflare.com
AI_API_KEY={SECRET}
============================================================
"""

TEMPLATE = """# Where the AI server lives.
# AI_BASE_URL=https://old-commented-out.trycloudflare.com
AI_BASE_URL=http://127.0.0.1:8001

AI_API_KEY=
AI_TIMEOUT=45
AI_MODEL=
"""


@pytest.fixture
def live_probe():
    """Marker fixture: a test that asks for this uses the real health probe."""


@pytest.fixture(autouse=True)
def stub_probe(request, monkeypatch):
    """Probing a dead localhost port takes ~2s on Windows; nearly every test here
    is about file handling, not networking, so probe by default with a stub."""
    if "live_probe" not in request.fixturenames:
        monkeypatch.setattr(switch_ai, "probe", lambda url, key: ("ok", "reachable (stubbed)"))


@pytest.fixture
def root(tmp_path):
    (tmp_path / ".env.example").write_text(TEMPLATE, encoding="utf-8")
    return tmp_path


def run(root, *argv, stdin=""):
    out = io.StringIO()
    rc = switch_ai.main(list(argv), out=out, stdin=io.StringIO(stdin), root=root)
    return rc, out.getvalue()


def env_text(root):
    return (root / ".env").read_text(encoding="utf-8")


# -- parsing -----------------------------------------------------------------------------

def test_parse_pairs_from_a_whole_pasted_banner():
    got = switch_ai.parse_pairs(BANNER)
    assert got == {"AI_BASE_URL": "https://random-words-1234.trycloudflare.com", "AI_API_KEY": SECRET}


@pytest.mark.parametrize("text,expected", [
    ('AI_BASE_URL="https://a.trycloudflare.com"\nAI_API_KEY=\'k\'', ("https://a.trycloudflare.com", "k")),
    ("export AI_BASE_URL=https://a.example\nexport AI_API_KEY=k", ("https://a.example", "k")),
    ("  AI_BASE_URL =  https://a.example  \r\n AI_API_KEY = k \r\n", ("https://a.example", "k")),
    ("AI_API_KEY=k\nAI_BASE_URL=https://a.example", ("https://a.example", "k")),      # either order
    ("# AI_BASE_URL=https://commented.example\nAI_BASE_URL=https://real.example\nAI_API_KEY=k",
     ("https://real.example", "k")),
])
def test_parse_pairs_tolerates_formatting(text, expected):
    got = switch_ai.parse_pairs(text)
    assert (got["AI_BASE_URL"], got["AI_API_KEY"]) == expected


def test_parse_pairs_ignores_unrelated_text():
    assert switch_ai.parse_pairs("hello\nMY_AI_BASE_URL=x\nAI_BASE_URLX=y") == {}


# -- rewriting .env -----------------------------------------------------------------------

def test_set_pairs_changes_only_the_ai_lines():
    out = switch_ai.set_pairs(TEMPLATE, {"AI_BASE_URL": "https://n.example", "AI_API_KEY": "k"})
    assert "AI_BASE_URL=https://n.example" in out and "AI_API_KEY=k" in out
    assert "AI_TIMEOUT=45" in out and "AI_MODEL=" in out and "# Where the AI server lives." in out
    assert "# AI_BASE_URL=https://old-commented-out.trycloudflare.com" in out      # comment untouched
    assert [l for l in out.splitlines() if l.startswith("AI_BASE_URL")] == ["AI_BASE_URL=https://n.example"]


def test_set_pairs_drops_duplicates_and_adds_missing_lines():
    out = switch_ai.set_pairs("AI_BASE_URL=a\nOTHER=1\nAI_BASE_URL=b\n", {"AI_BASE_URL": "c", "AI_API_KEY": "k"})
    assert out.splitlines() == ["AI_BASE_URL=c", "OTHER=1", "AI_API_KEY=k"]


def test_set_pairs_preserves_windows_line_endings():
    out = switch_ai.set_pairs("A=1\r\nAI_BASE_URL=x\r\nB=2\r\n", {"AI_BASE_URL": "y", "AI_API_KEY": "k"})
    assert out == "A=1\r\nAI_BASE_URL=y\r\nB=2\r\nAI_API_KEY=k\r\n"


@pytest.mark.parametrize("url,kind", [
    ("http://localhost:8001", "local"), ("http://127.0.0.1:8001", "local"),
    ("https://x-y.trycloudflare.com", "colab"), ("https://ai.example.com", "custom"), ("", "unset"),
])
def test_classify(url, kind):
    assert switch_ai.classify(url) == kind


# -- switching ------------------------------------------------------------------------------

def test_first_switch_creates_env_from_the_template(root):
    rc, out = run(root, "local")
    assert rc == 0 and "Switched to local" in out
    env = env_text(root)
    assert "AI_BASE_URL=http://127.0.0.1:8001" in env
    assert "AI_TIMEOUT=45" in env                                   # template kept


def test_switching_back_and_forth_remembers_each_profile(root):
    assert run(root, "colab", "--url", "https://one.trycloudflare.com", "--key", SECRET)[0] == 0
    assert switch_ai.read_active(root)["AI_BASE_URL"] == "https://one.trycloudflare.com"

    assert run(root, "local")[0] == 0
    assert switch_ai.read_active(root) == {"AI_BASE_URL": "http://127.0.0.1:8001", "AI_API_KEY": ""}

    # No paste, no flags: comes back from the saved Colab profile.
    rc, out = run(root, "colab")
    assert rc == 0
    assert switch_ai.read_active(root) == {"AI_BASE_URL": "https://one.trycloudflare.com", "AI_API_KEY": SECRET}


def test_local_profile_can_carry_its_own_port_and_key(root):
    switch_ai.save_profile("local", "http://localhost:9999", "localkey", root)
    run(root, "local")
    assert switch_ai.read_active(root) == {"AI_BASE_URL": "http://localhost:9999", "AI_API_KEY": "localkey"}


def test_pasting_the_colab_banner(root):
    rc, out = run(root, "colab", "--new", stdin=BANNER)
    assert rc == 0
    assert switch_ai.read_active(root) == {
        "AI_BASE_URL": "https://random-words-1234.trycloudflare.com", "AI_API_KEY": SECRET}
    assert switch_ai.load_profile("colab", root)["AI_API_KEY"] == SECRET    # saved for next time


def test_colab_with_no_saved_profile_asks_for_a_paste(root):
    rc, _ = run(root, "colab", stdin=BANNER)
    assert rc == 0 and switch_ai.read_active(root)["AI_API_KEY"] == SECRET


def test_new_overrides_a_saved_stale_profile(root):
    run(root, "colab", "--url", "https://stale.trycloudflare.com", "--key", "old")
    run(root, "colab", "--new", stdin=BANNER)
    assert switch_ai.read_active(root)["AI_BASE_URL"] == "https://random-words-1234.trycloudflare.com"


def test_an_incomplete_paste_changes_nothing(root):
    run(root, "local")
    before = env_text(root)
    rc, out = run(root, "colab", "--new", stdin="AI_BASE_URL=https://only-the-url.trycloudflare.com\n")
    assert rc == 1 and "Nothing was changed" in out
    assert env_text(root) == before and not (root / ".env.colab").exists()


@pytest.mark.parametrize("bad", ["not-a-url", "localhost:8001", "ftp://x.example", ""])
def test_invalid_address_is_rejected_and_nothing_changes(root, bad):
    run(root, "local")
    before = env_text(root)
    rc, out = run(root, "colab", "--url", bad, "--key", "k")
    assert rc == 1 and env_text(root) == before


def test_colab_without_a_key_is_rejected(root):
    rc, out = run(root, "colab", "--url", "https://x.trycloudflare.com")
    assert rc == 1 and "API key" in out and not (root / ".env").exists()


def test_addresses_are_normalised_when_saved(root):
    run(root, "colab", "--url", "http://x-y.trycloudflare.com/health", "--key", "k")
    assert switch_ai.read_active(root)["AI_BASE_URL"] == "https://x-y.trycloudflare.com"


def test_existing_env_keeps_unrelated_settings(root):
    (root / ".env").write_text("AI_BASE_URL=http://old\nAI_API_KEY=oldkey\nAI_TIMEOUT=77\nEXTRA=keep\n")
    run(root, "colab", "--url", "https://n.trycloudflare.com", "--key", "newkey")
    env = env_text(root)
    assert "AI_TIMEOUT=77" in env and "EXTRA=keep" in env and "oldkey" not in env


def test_no_temp_files_left_behind(root):
    run(root, "local")
    assert not list(root.glob("*.tmp"))


# -- status and health --------------------------------------------------------------------------

def test_status_reports_a_live_server(root, mock_ai, live_probe):
    run(root, "colab", "--url", mock_ai.url, "--key", SECRET)
    rc, out = run(root, "status")
    assert rc == 0 and "reachable, model mock-model" in out


def test_status_on_a_dead_local_server_says_how_to_start_one(root, live_probe):
    run(root, "local", "--url", f"http://127.0.0.1:{free_port()}")
    rc, out = run(root, "status")
    assert "unavailable" in out.lower() and "ai_server.server" in out


def test_a_stale_colab_address_is_called_out(root, live_probe):
    rc, out = run(root, "colab", "--url", "https://no-such-tunnel.invalid", "--key", "k")
    assert rc == 0                                                # switching still succeeds
    assert "probably stale" in out and "colab --new" in out


def test_status_when_the_model_is_still_loading(root, mock_ai, live_probe):
    mock_ai.mode = "health_loading"
    run(root, "local", "--url", mock_ai.url)
    assert "still loading" in run(root, "status")[1]


def test_status_with_nothing_configured(root):
    rc, out = run(root, "status")
    assert rc == 0 and "unset" in out and "nothing saved yet" in out


# -- the key is a secret ----------------------------------------------------------------------------

def test_the_api_key_is_never_printed(root, mock_ai, live_probe):
    outputs = [
        run(root, "colab", "--new", stdin=BANNER.replace("https://random-words-1234.trycloudflare.com", mock_ai.url))[1],
        run(root, "status")[1],
        run(root, "local")[1],
        run(root, "colab")[1],
        run(root, "colab", "--url", "https://z.trycloudflare.com", "--key", SECRET)[1],
    ]
    assert all(SECRET not in o for o in outputs)
    assert "key: set (" in outputs[1] or "key: set (" in outputs[3]


def test_profile_files_are_git_ignored():
    gitignore = (Path(switch_ai.ROOT) / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in gitignore.splitlines() and ".env.*" in gitignore.splitlines()
    assert "!.env.example" in gitignore.splitlines()


def test_local_defaults_use_the_ipv4_loopback_not_localhost():
    """On Windows 'localhost' tries IPv6 first and waits ~2s for the refusal, on every
    new connection: 4x slower local turns, found by actually running the app."""
    from app import ai_client
    from ai_server.server import OllamaEngine, build_engine
    assert "localhost" not in ai_client.DEFAULT_BASE_URL and "localhost" not in switch_ai.LOCAL_DEFAULT
    assert "localhost" not in OllamaEngine("m").url
    assert "localhost" not in build_engine("ollama", "m").url


def test_switching_away_keeps_a_hand_edited_env_target(root):
    """A .env edited by hand has no saved profile. Switching to local must not
    silently destroy the Colab address and key that were in it."""
    (root / ".env").write_text(f"AI_BASE_URL=https://hand-edited.trycloudflare.com\nAI_API_KEY={SECRET}\n")
    rc, out = run(root, "local")
    assert rc == 0 and "kept your previous colab settings" in out and SECRET not in out
    assert switch_ai.read_active(root)["AI_BASE_URL"] == "http://127.0.0.1:8001"

    rc, _ = run(root, "colab")                         # no paste, no flags: it was kept
    assert rc == 0
    assert switch_ai.read_active(root) == {
        "AI_BASE_URL": "https://hand-edited.trycloudflare.com", "AI_API_KEY": SECRET}


def test_switching_to_the_same_kind_does_not_clobber_its_profile(root):
    run(root, "colab", "--url", "https://first.trycloudflare.com", "--key", "k1")
    run(root, "colab", "--url", "https://second.trycloudflare.com", "--key", "k2")
    assert switch_ai.load_profile("colab", root)["AI_BASE_URL"] == "https://second.trycloudflare.com"


def test_a_custom_server_is_not_saved_as_local_or_colab(root):
    (root / ".env").write_text("AI_BASE_URL=https://ai.example.com\nAI_API_KEY=x\n")
    run(root, "local")
    assert not (root / ".env.colab").exists() and not (root / ".env.custom").exists()
