"""
The Colab notebook can't be run in CI (no Colab, no GPU), so these tests check
what can be checked: it is in sync with ai_server/server.py, it is structurally
sound, every code cell is valid Python, and it keeps its configuration separate
from its implementation.
"""

import ast
import json
import re
import sys
from pathlib import Path

from collab import build_notebook

ROOT = Path(__file__).resolve().parent.parent
NB_PATH = ROOT / "collab" / "i-turn-ai-server.ipynb"


def load():
    return json.loads(NB_PATH.read_text(encoding="utf-8"))


def src(cell):
    return "".join(cell["source"])


def test_notebook_is_in_sync_with_the_server_source():
    assert build_notebook.main(["--check"]) == 0, \
        "run: python collab/build_notebook.py"


def test_embedded_server_is_the_real_server_file():
    server_cell = next(c for c in load()["cells"] if src(c).startswith("%%writefile ai_server.py"))
    embedded = src(server_cell).split("\n", 1)[1]
    assert embedded == (ROOT / "ai_server" / "server.py").read_text(encoding="utf-8").replace("\r\n", "\n")


def test_notebook_structure():
    nb = load()
    assert nb["nbformat"] == 4
    ids = [c["id"] for c in nb["cells"]]
    assert len(ids) == len(set(ids))
    assert nb["metadata"]["accelerator"] == "GPU"
    for c in nb["cells"]:
        if c["cell_type"] == "code":
            assert c["outputs"] == [] and c["execution_count"] is None   # no stale output committed


def test_every_code_cell_is_valid_python():
    for c in load()["cells"]:
        if c["cell_type"] != "code":
            continue
        code = src(c)
        if code.startswith("%%writefile"):
            code = code.split("\n", 1)[1]
        code = "\n".join(l for l in code.splitlines() if not l.startswith("!"))
        ast.parse(code)


def test_configuration_is_the_first_code_cell_and_separate_from_implementation():
    code_cells = [c for c in load()["cells"] if c["cell_type"] == "code"]
    config = src(code_cells[0])
    assert re.search(r'^MODEL_NAME = ".+"', config, re.M)
    assert re.search(r"^PORT = \d+", config, re.M)
    assert len(config.splitlines()) < 15          # a config, not 500 lines of code
    assert "subprocess" not in config and "import" not in config


def test_notebook_prints_what_the_developer_must_copy():
    text = "\n".join(src(c) for c in load()["cells"])
    assert "AI_BASE_URL={PUBLIC_URL}" in text and "AI_API_KEY={AI_API_KEY}" in text
    assert "Set this in your i-turn .env" in text


def test_notebook_carries_no_secrets_or_model_weights():
    raw = NB_PATH.read_text(encoding="utf-8")
    assert not re.search(r"hf_[A-Za-z0-9]{20,}", raw)
    assert NB_PATH.stat().st_size < 200_000


def test_trycloudflare_url_regex_matches_real_cloudflared_output():
    line = "2026-09-19T10:00:00Z INF |  https://random-words-here-1234.trycloudflare.com  |"
    tunnel_cell = next(c for c in load()["cells"] if c["id"] == "tunnel")
    pattern = re.search(r're\.search\(r"([^"]+)"', src(tunnel_cell)).group(1)
    assert re.search(pattern, line).group(0) == "https://random-words-here-1234.trycloudflare.com"
    assert not re.search(pattern, "https://api.cloudflare.com/tunnel")


def test_this_test_module_imported_no_gpu_libraries():
    assert "torch" not in sys.modules
