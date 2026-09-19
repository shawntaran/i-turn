"""
Shared fixtures. Nothing here needs a GPU, a model, Colab or network access:
the "AI server" is either a tiny scripted HTTP server on localhost (MockAI) or
the real ai_server with its stub engine.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app import llm


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Sessions open ./iturn.db; give every test its own directory, and never
    let one test's AI client leak into the next."""
    monkeypatch.chdir(tmp_path)
    llm.set_client(None)
    yield
    llm.set_client(None)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_until(pred, timeout: float = 5.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


class MockAI:
    """
    A scripted stand-in for an AI server, speaking the real contract over real
    sockets. Set `.mode` to choose how the next requests behave.
    """

    def __init__(self) -> None:
        self.mode = "ok"
        self.reply = "That sounds heavy. What's been the hardest part?"
        self.json_reply = "{}"
        self.delay = 2.0
        self.requests: list[dict] = []
        mock = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):  # keep test output quiet
                pass

            def _send(self, status: int, body, raw: bool = False):
                data = body.encode() if raw else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _handle(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                mock.requests.append({"method": self.command, "path": self.path,
                                      "auth": self.headers.get("Authorization"), "json": body})
                m = mock.mode
                if m == "slow":
                    time.sleep(mock.delay)
                if m == "interrupt":
                    self.close_connection = True   # hang up without answering
                    return
                if m == "health_loading":
                    return self._send(503, {"status": "loading", "model": "mock-model"})
                if m == "malformed":
                    return self._send(200, "this is not { json", raw=True)
                if m == "no_text":
                    return self._send(200, {"model": "mock"})
                if m == "empty_text":
                    return self._send(200, {"text": "   ", "model": "mock"})
                if m == "wrong_type":
                    return self._send(200, ["a", "list"])
                if m == "unauthorized":
                    return self._send(401, {"error": {"code": "unauthorized", "message": "no"}})
                if m == "loading":
                    return self._send(503, {"error": {"code": "model_loading", "message": "wait"}})
                if m == "model_error":
                    return self._send(503, {"error": {"code": "model_error", "message": "boom"}})
                if m == "oom":
                    return self._send(503, {"error": {"code": "out_of_memory", "message": "oom"}})
                if m == "tunnel_down":
                    return self._send(530, "<html>error code: 1033</html>", raw=True)
                if m == "not_found":
                    return self._send(404, "Not Found", raw=True)
                if m == "crash":
                    return self._send(500, {"error": {"code": "generation_failed", "message": "x"}})

                if self.path == "/health":
                    return self._send(200, {"status": "ok", "model": "mock-model"})
                text = mock.json_reply if body.get("json_mode") else mock.reply
                return self._send(200, {
                    "text": text, "model": "mock-model", "finish_reason": "stop",
                    "usage": {"input_tokens": 12, "output_tokens": 7},
                })

            do_GET = do_POST = _handle

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def start(self) -> "MockAI":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture
def mock_ai():
    m = MockAI().start()
    yield m
    m.stop()
