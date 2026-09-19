"""
Guards for the student UI (static/index.html, css/app.css, js/app.js).

These can't run a browser, but they pin the things that are easy to break
silently and expensive when they are: no third-party requests, no markup
injection, no design-tool annotations left in the page, no red, real contrast,
an accessible skeleton, and no hard-coded questionnaire or crisis wording that
should come from the server.
"""

import colorsys
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main

STATIC = Path(main.STATIC)
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
CSS = (STATIC / "css" / "app.css").read_text(encoding="utf-8")
JS = (STATIC / "js" / "app.js").read_text(encoding="utf-8")


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids, self.tags, self.labels_for, self.inputs = [], [], set(), []
        self.buttons = []            # (attrs, has_text)
        self._btn = None
        self._label_depth = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.tags.append((tag, a))
        if "id" in a:
            self.ids.append(a["id"])
        if tag == "label":
            self._label_depth += 1
            if "for" in a:
                self.labels_for.add(a["for"])
        if tag in ("input", "textarea") and a.get("type") not in ("hidden",):
            self.inputs.append((a, self._label_depth > 0))
        if tag == "button":
            self._btn = [a, False]

    def handle_endtag(self, tag):
        if tag == "label":
            self._label_depth -= 1
        if tag == "button" and self._btn:
            self.buttons.append(tuple(self._btn))
            self._btn = None

    def handle_data(self, data):
        if self._btn is not None and data.strip():
            self._btn[1] = True


PAGE = Page()
PAGE.feed(HTML)


# -- served correctly ----------------------------------------------------------------

def test_assets_are_served():
    c = TestClient(main.app)
    r = c.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    assert "/static/css/app.css" in r.text and "/static/js/app.js" in r.text
    assert "css" in c.get("/static/css/app.css").headers["content-type"]
    assert "javascript" in c.get("/static/js/app.js").headers["content-type"]


def test_assets_are_small_enough_for_a_cheap_phone():
    total = sum(len(x.encode("utf-8")) for x in (HTML, CSS, JS))
    assert total < 100_000, f"{total} bytes of html+css+js"


# -- privacy: nothing but this server -----------------------------------------------------

def test_no_third_party_requests():
    allowed = {"http://www.w3.org/2000/svg"}
    for name, text in (("index.html", HTML), ("app.css", CSS), ("app.js", JS)):
        urls = set(re.findall(r"https?://[^\s\"'<>)]+", text)) - allowed
        assert not urls, f"{name} references {urls}"
    assert "@import" not in CSS and "fonts.googleapis" not in HTML + CSS + JS
    assert "cdn." not in (HTML + CSS + JS).lower()


def test_no_design_tool_leftovers():
    blob = HTML + CSS + JS
    for junk in ("[needs decision]", "[new front-end]", "[needs backend]", "Draft Spec",
                 "Paper Ground", "material-symbols", "Material Symbols", "tailwind"):
        assert junk.lower() not in blob.lower(), junk


# -- security: text is never parsed as markup -----------------------------------------------

@pytest.mark.parametrize("bad", ["innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"])
def test_javascript_never_turns_text_into_markup(bad):
    assert bad not in JS


def test_the_ui_only_calls_routes_students_may_call():
    called = set(re.findall(r"api\('(/api/[a-z/]+)", JS))
    called.add("/api/ai/health")                       # dev status dot, via fetch
    allowed = {"/api/meta", "/api/start", "/api/turn", "/api/end", "/api/ai/health",
               "/api/instrument/", "/api/instrument/answer", "/api/instrument/stop"}
    assert called and called <= allowed, called - allowed
    for locked in ("counsellor", "handoff", "report", "sessions", "data"):
        assert f"/api/{locked}" not in JS


# -- content that must come from the server, not be typed into the UI -----------------------

def test_questionnaire_wording_is_never_hard_coded():
    """The statements and answer labels are validated instrument text; the UI renders
    what the server sends and must not carry its own copy of them."""
    for phrase in ("Did not apply to me at all", "Applied to me", "I found it hard to wind down",
                   "There's a short standard questionnaire"):
        assert phrase not in JS and phrase not in HTML


def test_crisis_help_always_has_real_numbers_and_never_a_placeholder():
    assert "14416" in JS and "1-800-891-4416" in JS and "'112'" in JS       # fallback if /api/meta fails
    assert "includes('<<')" in JS                                            # placeholder text is dropped
    assert "tel:" in JS                                                      # rows are dialable


# -- skeleton and accessibility ---------------------------------------------------------------

REQUIRED_IDS = {"gate", "gate-form", "pseudonym", "shuffle", "consent", "consent-check", "notice-body",
                "begin", "chat", "thread", "composer", "input", "send", "done", "jump", "help",
                "help-rows", "finish", "announcer", "alert-announcer", "theme", "help-open", "offline",
                "modeline", "count", "name-hint", "gate-error", "pilot-chip"}


def test_every_element_the_script_needs_exists_exactly_once():
    assert REQUIRED_IDS <= set(PAGE.ids), REQUIRED_IDS - set(PAGE.ids)
    dupes = {i for i in PAGE.ids if PAGE.ids.count(i) > 1}
    assert not dupes, dupes
    for i in re.findall(r"\$\('#([a-z-]+)'\)", JS):
        assert i in PAGE.ids, f"app.js looks for #{i}, which is not in index.html"


def test_page_basics():
    assert '<html lang="en">' in HTML
    assert 'name="viewport"' in HTML and "viewport-fit=cover" in HTML
    assert 'name="color-scheme"' in HTML
    assert any(t == "main" for t, _ in PAGE.tags) and 'class="skip"' in HTML


def test_every_form_control_has_a_label():
    for attrs, inside_label in PAGE.inputs:
        assert inside_label or attrs.get("id") in PAGE.labels_for or "aria-label" in attrs, attrs


def test_every_button_has_a_name():
    for attrs, has_text in PAGE.buttons:
        assert has_text or attrs.get("aria-label"), f"unnamed button: {attrs}"


def test_conversation_is_a_log_and_replies_are_announced_separately():
    thread = next(a for t, a in PAGE.tags if a.get("id") == "thread")
    assert thread["role"] == "log"
    assert next(a for t, a in PAGE.tags if a.get("id") == "announcer")["aria-live"] == "polite"
    assert next(a for t, a in PAGE.tags if a.get("id") == "alert-announcer")["aria-live"] == "assertive"


def test_dialogs_use_the_native_element_for_focus_handling():
    assert PAGE.ids.count("help") == 1 and any(t == "dialog" for t, _ in PAGE.tags)
    assert "showModal" in JS


def test_css_honours_user_preferences():
    assert "prefers-reduced-motion: reduce" in CSS
    assert "prefers-color-scheme: dark" in CSS
    assert ":focus-visible" in CSS
    assert "env(safe-area-inset-bottom)" in CSS
    assert "@media print" in CSS


# -- colour ---------------------------------------------------------------------------------------

def tokens(block):
    return {k: v.lower() for k, v in re.findall(r"--([a-z-]+):\s*(#[0-9a-fA-F]{6})", block)}


def block_after(marker):
    i = CSS.index(marker)
    return CSS[CSS.index("{", i): CSS.index("}", i)]


LIGHT = tokens(block_after(":root {"))
DARK = tokens(block_after(':root[data-theme="dark"] {'))
DARK_MEDIA = tokens(block_after(':root:not([data-theme="light"]) {'))


def lum(h):
    r, g, b = (int(h.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contrast(a, b):
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_dark_theme_is_defined_the_same_way_for_system_and_manual_choice():
    assert DARK and DARK == DARK_MEDIA


TEXT_PAIRS = [("on-surface", "surface"), ("on-surface", "surface-lowest"), ("on-variant", "surface"),
              ("on-variant", "surface-lowest"), ("on-variant", "surface-container"),
              ("on-surface", "me"), ("on-primary", "primary"), ("primary", "surface"),
              ("secondary", "surface"), ("on-secondary-soft", "secondary-soft"), ("on-surface", "surface-low")]
BORDER_PAIRS = [("outline", "surface-lowest"), ("outline", "surface")]      # controls need 3:1


@pytest.mark.parametrize("theme,t", [("light", LIGHT), ("dark", DARK)])
def test_text_contrast_meets_wcag_aa(theme, t):
    for fg, bg in TEXT_PAIRS:
        assert contrast(t[fg], t[bg]) >= 4.5, f"{theme}: {fg} on {bg} = {contrast(t[fg], t[bg]):.2f}"


@pytest.mark.parametrize("theme,t", [("light", LIGHT), ("dark", DARK)])
def test_control_borders_meet_the_non_text_rule(theme, t):
    for fg, bg in BORDER_PAIRS:
        assert contrast(t[fg], t[bg]) >= 3.0, f"{theme}: {fg} vs {bg} = {contrast(t[fg], t[bg]):.2f}"


def test_no_red_anywhere():
    """Red reads as alarm. Amber is the only warning colour, including on the crisis panel."""
    for h in re.findall(r"#[0-9a-fA-F]{6}\b", CSS):
        r, g, b = (int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))
        hue, light, sat = colorsys.rgb_to_hls(r, g, b)[0] * 360, colorsys.rgb_to_hls(r, g, b)[1], colorsys.rgb_to_hls(r, g, b)[2]
        if sat > 0.3 and 0.15 < light < 0.9:
            assert not (hue < 16 or hue > 340), f"{h} is red (hue {hue:.0f})"
