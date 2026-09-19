"""
Tunnel-shaped failures: blips that should heal, failures that must not be
retried, addresses typed wrongly, and text that isn't ASCII.
"""

import logging

import pytest

from app.ai_client import AIClient, AIError, normalise_base_url
from tests.conftest import free_port


def client(url, **kw):
    kw.setdefault("timeout", 5)
    kw.setdefault("retry_backoff", (0, 0))
    return AIClient(url, **kw)


def generate_calls(mock):
    return [r for r in mock.requests if r["path"] == "/v1/generate"]


# -- blips are retried, and heal ------------------------------------------------------

@pytest.mark.parametrize("blip", ["tunnel_down", "bad_gateway", "interrupt"])
def test_a_brief_tunnel_blip_is_invisible_to_the_student(mock_ai, blip):
    mock_ai.script = [blip, "ok"]
    r = client(mock_ai.url).generate("x")
    assert r.text == mock_ai.reply
    assert len(generate_calls(mock_ai)) == 2


def test_two_blips_in_a_row_still_recover(mock_ai):
    mock_ai.script = ["tunnel_down", "interrupt", "ok"]
    assert client(mock_ai.url).generate("x").text == mock_ai.reply
    assert len(generate_calls(mock_ai)) == 3


def test_gives_up_after_the_configured_retries(mock_ai):
    mock_ai.mode = "tunnel_down"
    with pytest.raises(AIError) as e:
        client(mock_ai.url, retries=2).generate("x")
    assert e.value.code == "unavailable"
    assert len(generate_calls(mock_ai)) == 3            # 1 try + 2 retries


def test_retries_can_be_switched_off(mock_ai):
    mock_ai.mode = "tunnel_down"
    with pytest.raises(AIError):
        client(mock_ai.url, retries=0).generate("x")
    assert len(generate_calls(mock_ai)) == 1


def test_health_check_also_rides_out_a_blip(mock_ai):
    mock_ai.script = ["tunnel_down", "ok"]
    assert client(mock_ai.url).health()["status"] == "ok"


# -- failures that must NOT be retried (they would only repeat, or waste time) ----------

@pytest.mark.parametrize("mode", [
    "unauthorized", "loading", "model_error", "oom", "not_found",
    "malformed", "no_text", "gateway_timeout", "rate_limited", "crash",
])
def test_non_transient_failures_are_not_retried(mock_ai, mode):
    mock_ai.mode = mode
    with pytest.raises(AIError):
        client(mock_ai.url).generate("x")
    assert len(generate_calls(mock_ai)) == 1


def test_a_timeout_is_not_retried(mock_ai):
    """The student has already waited the full timeout once."""
    mock_ai.mode, mock_ai.delay = "slow", 1.0
    with pytest.raises(AIError) as e:
        client(mock_ai.url, timeout=0.2).generate("x")
    assert e.value.code == "timeout"
    assert len(generate_calls(mock_ai)) == 1


def test_connection_refused_is_not_retried():
    import time
    c = client(f"http://127.0.0.1:{free_port()}", retries=5)
    start = time.time()
    with pytest.raises(AIError) as e:
        c.generate("x")
    assert e.value.code == "unavailable"
    assert time.time() - start < 8                      # one attempt, not six


def test_real_backoff_delays_are_used_between_retries(mock_ai, monkeypatch):
    slept = []
    monkeypatch.setattr("app.ai_client.time.sleep", slept.append)
    mock_ai.mode = "tunnel_down"
    with pytest.raises(AIError):
        AIClient(mock_ai.url, timeout=5).generate("x")   # default backoff
    assert slept == [1.0, 3.0]


# -- Cloudflare-specific status codes ---------------------------------------------------

def test_cloudflare_524_is_a_timeout_not_an_outage(mock_ai):
    mock_ai.mode = "gateway_timeout"
    with pytest.raises(AIError) as e:
        client(mock_ai.url).generate("x")
    assert e.value.code == "timeout" and "too long" in e.value.message


def test_429_is_reported_as_busy(mock_ai):
    mock_ai.mode = "rate_limited"
    with pytest.raises(AIError) as e:
        client(mock_ai.url).generate("x")
    assert e.value.code == "busy" and "busy" in e.value.message


# -- addresses typed wrongly ------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("https://x.trycloudflare.com", "https://x.trycloudflare.com"),
    ("https://x.trycloudflare.com/", "https://x.trycloudflare.com"),
    ("  https://x.trycloudflare.com \r\n", "https://x.trycloudflare.com"),
    ('"https://x.trycloudflare.com"', "https://x.trycloudflare.com"),
    ("'https://x.trycloudflare.com'", "https://x.trycloudflare.com"),
    ("https://x.trycloudflare.com/health", "https://x.trycloudflare.com"),
    ("https://x.trycloudflare.com/v1/generate", "https://x.trycloudflare.com"),
    ("https://x.trycloudflare.com/v1/generate/", "https://x.trycloudflare.com"),
    ("https://x.trycloudflare.com/v1", "https://x.trycloudflare.com"),
    ("https://x.trycloudflare.com/HEALTH", "https://x.trycloudflare.com"),
    ("http://x.trycloudflare.com", "https://x.trycloudflare.com"),       # never send the key in clear
    ("HTTP://X.TRYCLOUDFLARE.COM", "https://X.TRYCLOUDFLARE.COM"),
    ("http://localhost:8001/", "http://localhost:8001"),                 # local http is left alone
    ("http://192.168.1.20:8001", "http://192.168.1.20:8001"),
    ("https://example.com/proxy/health", "https://example.com/proxy"),
    ("", ""),
])
def test_normalise_base_url(raw, expected):
    assert normalise_base_url(raw) == expected


def test_a_pasted_endpoint_path_still_works_end_to_end(mock_ai):
    assert client(mock_ai.url + "/v1/generate").generate("x").text == mock_ai.reply
    assert client(mock_ai.url + "/health").health()["status"] == "ok"


@pytest.mark.parametrize("key", ['"abc123"', "'abc123'", "  abc123\r\n", "abc123"])
def test_api_key_is_cleaned_of_quotes_and_whitespace(mock_ai, key):
    client(mock_ai.url, api_key=key).generate("x")
    assert mock_ai.requests[-1]["auth"] == "Bearer abc123"


def test_warns_when_the_key_would_travel_in_clear_text(caplog):
    with caplog.at_level(logging.WARNING, logger="iturn.ai"):
        AIClient("http://ai.example.com", api_key="secret")
    assert "unencrypted" in caplog.text

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="iturn.ai"):
        AIClient("http://localhost:8001", api_key="secret")       # loopback: fine
        AIClient("https://ai.example.com", api_key="secret")      # https: fine
        AIClient("http://ai.example.com", api_key="")             # no key, nothing to leak
    assert "unencrypted" not in caplog.text


@pytest.mark.parametrize("bad", [0, -5, float("nan"), float("inf"), None, "soon"])
def test_a_nonsense_timeout_falls_back_to_the_default(bad):
    assert AIClient("http://localhost:1", timeout=bad).timeout == 120.0


def test_bad_AI_TIMEOUT_in_the_environment(monkeypatch):
    from app.ai_client import from_env
    for value in ("abc", "0", "-3", ""):
        monkeypatch.setenv("AI_TIMEOUT", value)
        assert from_env().timeout == 120.0
    monkeypatch.setenv("AI_TIMEOUT", "30")
    assert from_env().timeout == 30.0


# -- text that is not ASCII ---------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "मुझे नींद नहीं आती",                # Hindi
    "எனக்கு தூக்கம் வரவில்லை",            # Tamil
    "ನನಗೆ ನಿದ್ರೆ ಬರುತ್ತಿಲ್ಲ",             # Kannada
    "can't sleep 😔 — “quotes” & <tags> \"double\" \\ backslash",
    "line one\nline two\n\ttabbed",
    "x" * 20000,
])
def test_text_round_trips_exactly(mock_ai, text):
    mock_ai.mode = "echo"
    assert client(mock_ai.url).generate(messages=[{"role": "user", "content": text}]).text == text
    assert client(mock_ai.url).generate(text).text == text


def test_client_survives_many_calls_and_reuses_connections(mock_ai):
    c = client(mock_ai.url)
    for _ in range(50):
        assert c.generate("x").text
    assert len(generate_calls(mock_ai)) == 50


def test_client_is_safe_to_share_between_threads(mock_ai):
    import concurrent.futures as cf
    c = client(mock_ai.url)
    with cf.ThreadPoolExecutor(8) as ex:
        results = list(ex.map(lambda _: c.generate("x").text, range(40)))
    assert results == [mock_ai.reply] * 40
