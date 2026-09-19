"""
The HTTP AI client against a mock AI server. Every failure the application can
meet on the way to a model must come out as an AIError with a message that is
safe to show a student — never a raw httpx exception or a traceback.
"""

import pytest

from app.ai_client import AIClient, AIError
from tests.conftest import free_port


def client(url, **kw):
    kw.setdefault("timeout", 5)
    kw.setdefault("retry_backoff", (0, 0))     # never really sleep in tests
    return AIClient(url, **kw)


# -- success -------------------------------------------------------------------

def test_generate_success(mock_ai):
    r = client(mock_ai.url).generate("hello", system_prompt="be kind", temperature=0.3,
                                     max_tokens=50)
    assert r.text == mock_ai.reply
    assert r.model == "mock-model"
    assert r.finish_reason == "stop"
    assert r.usage == {"input_tokens": 12, "output_tokens": 7}

    sent = mock_ai.requests[-1]
    assert sent["method"] == "POST" and sent["path"] == "/v1/generate"
    assert sent["json"]["prompt"] == "hello"
    assert sent["json"]["system_prompt"] == "be kind"
    assert sent["json"]["temperature"] == 0.3
    assert sent["json"]["max_tokens"] == 50
    assert "messages" not in sent["json"]


def test_generate_with_chat_messages_and_json_mode(mock_ai):
    msgs = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    mock_ai.json_reply = '{"sleep_hours": 4}'
    r = client(mock_ai.url).generate(messages=msgs, json_mode=True)
    assert r.text == '{"sleep_hours": 4}'
    sent = mock_ai.requests[-1]["json"]
    assert sent["messages"] == msgs and sent["json_mode"] is True and "prompt" not in sent


def test_api_key_is_sent_as_bearer_and_only_when_set(mock_ai):
    client(mock_ai.url, api_key="s3cret").generate("x")
    assert mock_ai.requests[-1]["auth"] == "Bearer s3cret"
    client(mock_ai.url).generate("x")
    assert mock_ai.requests[-1]["auth"] is None


def test_model_identifier_is_forwarded_when_configured(mock_ai):
    client(mock_ai.url, model="some-model").generate("x")
    assert mock_ai.requests[-1]["json"]["model"] == "some-model"
    client(mock_ai.url).generate("x")
    assert "model" not in mock_ai.requests[-1]["json"]


def test_trailing_slash_in_base_url_is_fine(mock_ai):
    assert client(mock_ai.url + "/").generate("x").text


# -- server not there ------------------------------------------------------------

def test_connection_refused_is_a_clean_error():
    with pytest.raises(AIError) as e:
        client(f"http://127.0.0.1:{free_port()}").generate("x")
    assert e.value.code == "unavailable"
    assert "AI_BASE_URL" in e.value.message and "Colab" in e.value.message
    assert "Traceback" not in e.value.message and "httpx" not in e.value.message


@pytest.mark.parametrize("url", ["not-a-url", "ftp://example.com", "", "localhost:8001"])
def test_invalid_base_url(url):
    with pytest.raises(AIError) as e:
        client(url).generate("x")
    assert e.value.code == "bad_url"
    assert "AI_BASE_URL" in e.value.message


def test_unresolvable_host_is_unavailable():
    with pytest.raises(AIError) as e:
        client("http://this-host-does-not-exist.invalid").generate("x")
    assert e.value.code == "unavailable"


def test_dead_tunnel_is_unavailable(mock_ai):
    """Cloudflare answers 530 when nothing is behind the tunnel any more."""
    mock_ai.mode = "tunnel_down"
    with pytest.raises(AIError) as e:
        client(mock_ai.url).generate("x")
    assert e.value.code == "unavailable"


def test_wrong_url_that_serves_something_else(mock_ai):
    """A 404 means AI_BASE_URL points at the wrong thing, not that the model broke."""
    mock_ai.mode = "not_found"
    with pytest.raises(AIError) as e:
        client(mock_ai.url).generate("x")
    assert e.value.code == "unavailable"


# -- slow / dropped ------------------------------------------------------------------

def test_timeout(mock_ai):
    mock_ai.mode, mock_ai.delay = "slow", 1.5
    with pytest.raises(AIError) as e:
        client(mock_ai.url, timeout=0.3).generate("x")
    assert e.value.code == "timeout"
    assert "too long" in e.value.message


def test_connection_interrupted(mock_ai):
    mock_ai.mode = "interrupt"
    with pytest.raises(AIError) as e:
        client(mock_ai.url).generate("x")
    assert e.value.code == "interrupted"


# -- bad answers -----------------------------------------------------------------------

@pytest.mark.parametrize("mode", ["malformed", "no_text", "empty_text", "wrong_type"])
def test_invalid_response(mock_ai, mode):
    mock_ai.mode = mode
    with pytest.raises(AIError) as e:
        client(mock_ai.url).generate("x")
    assert e.value.code == "invalid_response"
    assert "{" not in e.value.message           # nothing from the body reaches the student


# -- errors the server reports itself --------------------------------------------------

@pytest.mark.parametrize("mode,code", [
    ("unauthorized", "unauthorized"),
    ("loading", "model_loading"),
    ("model_error", "model_error"),
    ("oom", "out_of_memory"),
    ("crash", "server_error"),
])
def test_server_reported_errors(mock_ai, mode, code):
    mock_ai.mode = mode
    with pytest.raises(AIError) as e:
        client(mock_ai.url).generate("x")
    assert e.value.code == code


def test_ai_error_keeps_detail_out_of_the_message(mock_ai):
    mock_ai.mode = "tunnel_down"
    with pytest.raises(AIError) as e:
        client(mock_ai.url).generate("x")
    assert "1033" in e.value.detail            # available to the log...
    assert "1033" not in e.value.message       # ...never to the student


# -- health ------------------------------------------------------------------------------

def test_health_ok(mock_ai):
    assert client(mock_ai.url).health() == {"status": "ok", "model": "mock-model"}


def test_health_reports_loading_without_raising(mock_ai):
    mock_ai.mode = "health_loading"
    assert client(mock_ai.url).health()["status"] == "loading"


def test_health_unreachable():
    with pytest.raises(AIError) as e:
        client(f"http://127.0.0.1:{free_port()}").health()
    assert e.value.code == "unavailable"


def test_health_from_something_that_is_not_an_ai_server(mock_ai):
    mock_ai.mode = "malformed"
    with pytest.raises(AIError) as e:
        client(mock_ai.url).health()
    assert e.value.code == "invalid_response"
