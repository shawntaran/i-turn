"""
The reference AI server (ai_server/server.py), exercised through its HTTP
interface with fake engines — no model, no GPU. Includes a real end-to-end run:
AIClient -> HTTP -> ai_server -> stub engine.
"""

import sys
import threading

import pytest
import uvicorn
from fastapi.testclient import TestClient

from ai_server.server import (Completion, Engine, EngineError, StubEngine,
                              build_engine, create_app)
from app.ai_client import AIClient, AIError
from tests.conftest import free_port, wait_until


class FakeEngine(Engine):
    name = "fake"

    def __init__(self, text="  hello  ", load_error=None, gen_error=None, gate=None, **kw):
        super().__init__("fake-model")
        self.text, self.load_error, self.gen_error, self.gate = text, load_error, gen_error, gate
        self.kw, self.calls = kw, []

    def load(self):
        if self.gate:
            self.gate.wait(5)
        if self.load_error:
            raise self.load_error

    def generate(self, messages, p):
        self.calls.append((messages, p))
        if self.gen_error:
            raise self.gen_error
        return Completion(self.text, input_tokens=3, output_tokens=2, **self.kw)


@pytest.fixture
def serve():
    """Factory: an app around `engine`, lifespan running, closed after the test."""
    opened = []

    def _serve(engine, api_key="", ready=True):
        c = TestClient(create_app(engine, api_key=api_key))
        c.__enter__()
        opened.append(c)
        if ready:
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
            assert wait_until(lambda: c.get("/health", headers=headers).status_code == 200)
        return c

    yield _serve
    for c in opened:
        c.__exit__(None, None, None)


# -- the contract -----------------------------------------------------------------

def test_generate_with_prompt(serve):
    eng = FakeEngine()
    r = serve(eng).post("/v1/generate", json={"prompt": "hi", "system_prompt": "be kind"})
    assert r.status_code == 200
    assert r.json() == {"text": "hello", "model": "fake-model", "finish_reason": "stop",
                        "usage": {"input_tokens": 3, "output_tokens": 2}}
    msgs, _ = eng.calls[0]
    assert msgs == [{"role": "system", "content": "be kind"}, {"role": "user", "content": "hi"}]


def test_generate_with_message_history(serve):
    eng = FakeEngine()
    history = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"},
               {"role": "user", "content": "c"}]
    assert serve(eng).post("/v1/generate", json={"messages": history}).status_code == 200
    assert eng.calls[0][0] == history


def test_sampling_parameters_reach_the_engine(serve):
    eng = FakeEngine()
    serve(eng).post("/v1/generate", json={"prompt": "x", "temperature": 0.0, "max_tokens": 128,
                                          "top_p": 0.5, "repeat_penalty": 1.2, "json_mode": True})
    p = eng.calls[0][1]
    assert (p.temperature, p.max_tokens, p.top_p, p.repeat_penalty, p.json_mode) == \
           (0.0, 128, 0.5, 1.2, True)


def test_engine_output_is_normalised(serve):
    """Whatever an engine hands back, the response has the contract's shape."""
    body = serve(FakeEngine(text="\n\n  padded answer \n", finish_reason="something-odd")) \
        .post("/v1/generate", json={"prompt": "x"}).json()
    assert body["text"] == "padded answer"
    assert body["finish_reason"] == "stop"
    assert set(body) == {"text", "model", "finish_reason", "usage"}

    cut = serve(FakeEngine(finish_reason="length")).post("/v1/generate", json={"prompt": "x"})
    assert cut.json()["finish_reason"] == "length"


def test_model_field_is_advisory(serve):
    r = serve(FakeEngine()).post("/v1/generate", json={"prompt": "x", "model": "some-other-model"})
    assert r.status_code == 200 and r.json()["model"] == "fake-model"


@pytest.mark.parametrize("body", [
    {},                                                                # neither
    {"prompt": "x", "messages": [{"role": "user", "content": "y"}]},   # both
    {"prompt": "x", "temperature": 9},
    {"prompt": "x", "max_tokens": 0},
    {"messages": [{"role": "robot", "content": "y"}]},
])
def test_invalid_requests_are_rejected(serve, body):
    assert serve(FakeEngine()).post("/v1/generate", json=body).status_code == 422


# -- health -------------------------------------------------------------------------------

def test_health_ok(serve):
    r = serve(FakeEngine()).get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "model": "fake-model", "engine": "fake", "contract": "1"}


def test_health_and_generate_while_loading(serve):
    gate = threading.Event()
    c = serve(FakeEngine(gate=gate), ready=False)
    r = c.get("/health")
    assert r.status_code == 503 and r.json()["status"] == "loading"
    g = c.post("/v1/generate", json={"prompt": "x"})
    assert g.status_code == 503 and g.json()["error"]["code"] == "model_loading"
    gate.set()
    assert wait_until(lambda: c.get("/health").status_code == 200)


def test_model_that_fails_to_load(serve):
    eng = FakeEngine(load_error=EngineError("model_error", "no such repo: nope/nope"))
    c = serve(eng, ready=False)
    assert wait_until(lambda: c.get("/health").json()["status"] == "error")
    h = c.get("/health")
    assert h.status_code == 503 and "no such repo" in h.json()["detail"]
    g = c.post("/v1/generate", json={"prompt": "x"})
    assert g.status_code == 503 and g.json()["error"]["code"] == "model_error"


def test_unexpected_exception_during_load_is_contained(serve):
    c = serve(FakeEngine(load_error=RuntimeError("cuda exploded")), ready=False)
    assert wait_until(lambda: c.get("/health").json()["status"] == "error")


# -- generation failures ------------------------------------------------------------------------

def test_gpu_out_of_memory(serve):
    c = serve(FakeEngine(gen_error=EngineError("out_of_memory", "GPU ran out of memory")))
    r = c.post("/v1/generate", json={"prompt": "x"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "out_of_memory"


def test_unexpected_generation_error_leaks_nothing(serve):
    c = serve(FakeEngine(gen_error=RuntimeError("secret internal path /root/x")))
    r = c.post("/v1/generate", json={"prompt": "x"})
    assert r.status_code == 500 and r.json()["error"]["code"] == "generation_failed"
    assert "secret" not in r.text and "/root" not in r.text


# -- auth ------------------------------------------------------------------------------------------

def test_api_key_is_required_when_set(serve):
    c = serve(FakeEngine(), api_key="k3y")
    for call in (lambda h: c.get("/health", headers=h),
                 lambda h: c.post("/v1/generate", json={"prompt": "x"}, headers=h)):
        assert call({}).status_code == 401
        assert call({"Authorization": "Bearer wrong"}).status_code == 401
        assert call({"Authorization": "Bearer k3y"}).status_code == 200
    assert c.get("/health").json() == {"error": {"code": "unauthorized",
                                                 "message": "missing or invalid API key"}}


def test_no_key_configured_means_open(serve):
    assert serve(FakeEngine()).get("/health").status_code == 200


# -- engine selection --------------------------------------------------------------------------------

def test_build_engine():
    assert build_engine("stub", "").name == "stub"
    assert build_engine("ollama", "qwen2.5:3b").name == "ollama"
    assert build_engine("transformers", "x/y").name == "transformers"   # constructed, not loaded
    with pytest.raises(ValueError):
        build_engine("gpt", "x")


def test_server_module_does_not_pull_in_torch():
    assert "torch" not in sys.modules and "transformers" not in sys.modules


# -- end to end: real client, real HTTP, real server, stub engine --------------------------------------

@pytest.fixture
def live_server():
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(
        create_app(StubEngine("stub-model"), api_key="e2e-key"),
        host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    assert wait_until(lambda: server.started, timeout=10)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    t.join(timeout=5)


def test_client_talks_to_the_real_server(live_server):
    c = AIClient(live_server, api_key="e2e-key", timeout=5)
    assert wait_until(lambda: c.health()["status"] == "ok")
    r = c.generate(messages=[{"role": "user", "content": "hi"}], system_prompt="s")
    assert r.model == "stub-model" and "stub" in r.text and r.finish_reason == "stop"
    assert c.generate("x", json_mode=True).text == "{}"


def test_client_with_wrong_key_gets_a_clean_error(live_server):
    with pytest.raises(AIError) as e:
        AIClient(live_server, api_key="wrong", timeout=5).generate("x")
    assert e.value.code == "unauthorized"
