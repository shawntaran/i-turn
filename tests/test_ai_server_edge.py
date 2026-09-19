"""
Edge cases for the AI server: malformed requests, non-ASCII text, and many
callers at once (a single GPU must serve them one at a time, without loss).
"""

import concurrent.futures as cf
import threading
import time

import pytest
import uvicorn
from fastapi.testclient import TestClient

from ai_server.server import Completion, Engine, StubEngine, create_app
from app.ai_client import AIClient
from tests.conftest import free_port, wait_until


class EchoEngine(Engine):
    """Answers with the last message, and records how many calls overlap."""
    name = "echo"

    def __init__(self, delay=0.0):
        super().__init__("echo-model")
        self.delay, self.active, self.peak, self.calls = delay, 0, 0, 0
        self._lock = threading.Lock()

    def generate(self, messages, p):
        with self._lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
            self.calls += 1
        try:
            time.sleep(self.delay)
            return Completion(messages[-1]["content"])
        finally:
            with self._lock:
                self.active -= 1


@pytest.fixture
def live():
    """Factory: run a real uvicorn server around an engine; yields its URL."""
    started = []

    def _live(engine, api_key=""):
        port = free_port()
        server = uvicorn.Server(uvicorn.Config(create_app(engine, api_key=api_key),
                                               host="127.0.0.1", port=port, log_level="warning"))
        t = threading.Thread(target=server.run, daemon=True)
        t.start()
        assert wait_until(lambda: server.started, timeout=10)
        started.append((server, t))
        c = AIClient(f"http://127.0.0.1:{port}", api_key=api_key, timeout=20)
        assert wait_until(lambda: c.health()["status"] == "ok")
        return c

    yield _live
    for server, t in started:
        server.should_exit = True
        t.join(timeout=5)


# -- malformed requests: always a clean 422, never a 500 or a hang ------------------------

@pytest.mark.parametrize("body", [
    {"messages": []},                                           # empty conversation
    {"prompt": ""},                                             # empty prompt
    {"messages": [{"role": "user", "content": ""}]},            # empty message
    {"messages": [{"role": "user"}]},                           # missing content
    {"messages": [{"content": "hi"}]},                          # missing role
    {"messages": "hello"},                                      # wrong type
    {"prompt": 123},
    {"prompt": "x", "temperature": -1},
    {"prompt": "x", "top_p": 0},
    {"prompt": "x", "repeat_penalty": 0.5},
    {"prompt": "x", "max_tokens": 4097},
    {"prompt": "x", "json_mode": "maybe"},
    {"messages": [{"role": "user", "content": "x"}] * 201},     # absurd history length
])
def test_malformed_requests_are_rejected_cleanly(body):
    with TestClient(create_app(StubEngine("s"))) as c:
        assert wait_until(lambda: c.get("/health").status_code == 200)
        r = c.post("/v1/generate", json=body)
        assert r.status_code == 422


@pytest.mark.parametrize("raw", [b"", b"not json", b"[1,2,3]", b"null", b"\xff\xfe"])
def test_garbage_bodies_do_not_crash_the_server(raw):
    with TestClient(create_app(StubEngine("s"))) as c:
        assert wait_until(lambda: c.get("/health").status_code == 200)
        r = c.post("/v1/generate", content=raw, headers={"Content-Type": "application/json"})
        assert r.status_code == 422
        assert c.get("/health").status_code == 200              # still alive afterwards


def test_wrong_http_methods_and_unknown_paths():
    with TestClient(create_app(StubEngine("s"))) as c:
        assert wait_until(lambda: c.get("/health").status_code == 200)
        assert c.get("/v1/generate").status_code == 405
        assert c.post("/health").status_code == 405
        assert c.get("/nope").status_code == 404


# -- text ------------------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["मुझे नींद नहीं आती", "எனக்கு தூக்கம்", "ok 😔", "a\nb\tc", "z" * 5000])
def test_unicode_survives_the_full_client_server_round_trip(live, text):
    c = live(EchoEngine())
    assert c.generate(messages=[{"role": "user", "content": text}]).text == text.strip()


# -- concurrency ---------------------------------------------------------------------------------

def test_simultaneous_requests_are_served_one_at_a_time_without_loss(live):
    engine = EchoEngine(delay=0.05)
    c = live(engine)
    with cf.ThreadPoolExecutor(10) as ex:
        out = list(ex.map(lambda i: c.generate(f"msg-{i}").text, range(30)))
    assert out == [f"msg-{i}" for i in range(30)]               # every caller got its own answer
    assert engine.peak == 1                                     # the GPU never ran two at once
    assert engine.calls == 30


def test_a_slow_request_does_not_break_health_checks(live):
    engine = EchoEngine(delay=1.0)
    c = live(engine)
    with cf.ThreadPoolExecutor(2) as ex:
        slow = ex.submit(lambda: c.generate("slow one"))
        time.sleep(0.2)
        t = time.time()
        assert c.health()["status"] == "ok"
        assert time.time() - t < 0.8                            # health answers while generating
        assert slow.result().text == "slow one"


def test_the_server_keeps_working_after_a_failed_request(live):
    class Flaky(EchoEngine):
        def generate(self, messages, p):
            if messages[-1]["content"] == "boom":
                raise RuntimeError("kaboom")
            return super().generate(messages, p)

    c = live(Flaky())
    from app.ai_client import AIError
    with pytest.raises(AIError) as e:
        c.generate("boom")
    assert e.value.code == "server_error"
    assert c.generate("fine").text == "fine"
