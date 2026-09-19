# I-Turn — UI design brief

For handing to **Stitch** (or any designer). Written from the running app, so the
copy, screens and data below are what the product really does — not a wish list.

Tags used throughout, so nothing gets designed that can't be built:

- **[new front-end]** — new UI behaviour, no backend change needed.
- **[needs backend]** — the API doesn't do this yet; design it, but it ships later.
- **[needs decision]** — a product/clinical call someone must make first.
- **MUST / SHOULD / MAY** — required / strongly preferred / optional.

---

## How to use this with Stitch

1. Paste **Part A (master prompt)** first. It sets tone, palette and constraints.
2. Generate each screen from **Part B (screen prompts)**, one at a time.
3. Use **Part C (requirements)** as the acceptance checklist and for anything the
   prompts leave out. Paste the relevant sections if Stitch asks for more detail.
4. Ask for: mobile (390 px) and desktop (1280 px) versions, light and dark, the
   design tokens, and **plain HTML/CSS with no framework** if it can export code.

---

# Part A — Master prompt (paste first)

> Design a calm, private, wellbeing-conversation web app called **I-Turn** for
> university students (ages 17–25, mostly on phones, often late at night, some may
> be distressed). It is an anonymous, open-ended chat with an AI companion, with an
> optional standard questionnaire (DASS-21) that the student can accept or decline.
> It is **not** a therapy app, a medical tool or a productivity chatbot.
>
> **Feel:** a quiet room, a well-typeset letter, a paper notebook. Warm, unhurried,
> human, respectful; never clinical, corporate, playful or "techy". The student should
> feel unobserved, unrushed and in control of every choice.
>
> **Look:** editorial and restrained. Warm paper background (#EDEAE3) with sage-green
> accent (#4E6A50); a matching dusk dark theme (#161A15, accent #9BB59B). Large
> literary serif for headings and the conversation (Newsreader-style), plain system
> sans for small interface labels. Thin lines, generous whitespace, one centred reading
> column (~38 rem). Slow, soft motion only.
>
> **Avoid:** hospital blue/white, hearts, crosses, brains, lotus or zen clichés, stock
> illustrations of people, robot or sparkle "AI" icons, purple/neon gradients, glass
> effects, emoji, confetti, streaks, badges, gamified progress, Material-default
> styling, and red/alarm colours anywhere — including the crisis screen.
>
> **Must be:** accessible (WCAG 2.2 AA minimum, AAA text contrast on the crisis
> screen), mobile-first (360 px up), keyboard- and screen-reader-complete, and
> buildable as plain HTML/CSS with a little vanilla JS. No external fonts, CDNs or
> trackers. Light and dark themes.
>
> Screens: 1 Welcome, 2 Conversation, 3 Questionnaire offer, 4 Questionnaire
> (one statement at a time), 5 Results, 6 Crisis/safety, 7 End-of-session summary,
> 8 Errors and empty states, plus a persistent "Need help now?" sheet.

---

# Part B — Per-screen prompts

**1 · Welcome.** Full-height centred column. Large light-weight serif headline
"Tell me what's happening." Subline: "No account, no real name. Start wherever you
want — there's no right way in." Below: a name field ("Pick a name to go by") with a
small shuffle button, a language selector, and two large selectable cards — Incognito
("Nothing is kept. Close the tab and it's gone.") and Story ("Remembers you between
visits. Delete it whenever.") — then a plainly readable privacy note (not collapsed,
comfortable contrast) and one primary button "Start talking". A quiet "Need help now?"
link in the corner. Quiet, spacious, unforced.

**2 · Conversation.** A single reading column. Assistant messages set as serif text
on the page like a letter (no chat-bubble chrome); the student's messages right-aligned
in a soft sage-tinted block. A gently "breathing" three-dot typing indicator. A fixed
composer at the bottom: auto-growing text area with the placeholder "Whatever's on
your mind.", a Send button, and a quiet "Done" ghost button. A slim top bar with a small
"I-Turn" wordmark, a mode label (Incognito / Story), "Need help now?", and a theme toggle.

**3 · Questionnaire offer.** An inline card inside the conversation, visually distinct
but gentle. Text: "There's a short standard questionnaire I can walk you through — 21
statements, and for each one you tell me how much it applied to you over the past week.
Takes about three minutes. It gives us something more solid than a guess, and you can
stop at any point. Want to do it?" Two buttons of **equal visual weight**: "Sure" and
"Not now". Nothing nudges toward yes.

**4 · Questionnaire.** One statement at a time, large serif, with the small line "Over the
past week — statement 4 of 21". Four full-width tappable answer rows (numbered 0–3) with
these exact labels: 0 "Did not apply to me at all" · 1 "Applied to me to some degree, or
some of the time" · 2 "Applied to me to a considerable degree, or a good part of the
time" · 3 "Applied to me very much, or most of the time". **No colour coding, sliders or
emoji.** Quiet progress ("4 of 21" plus a thin neutral line), and an always-visible
"Stop for now" link.

**5 · Results.** Calm and non-alarming. Sentence: "That's all 21. These are screening
bands, not a diagnosis — they describe the past week, not you." Three rows (one per
area) each showing the band word (Normal / Mild / Moderate / Severe / Extremely severe)
with a subtle five-step marker in a single sage hue — never a traffic light, gauge or
score. Below: an optional soft card "You can talk to a counsellor without explaining
yourself first" and an invitation to keep talking.

**6 · Crisis / safety.** The most important screen. Slow, still, warm; no red, no warning
triangles, no flashing. Large text (≥ 18 px, AAA contrast). Fixed compassionate message,
then big tappable call rows: Tele-MANAS **14416** and **1-800-891-4416**, the university
counselling line (only if configured), and **112** for immediate danger, plus "Someone you
trust who is physically near you". A one-line optional text box stays available: "You can
write here if you want. You don't have to."

**7 · Summary.** Headline "That's where we'll leave it." with the length of the chat
(and "Nothing was kept" in Incognito). "You talked about" as small pull-quotes of the
student's own words. Optional band results. Three quiet action rows: come back anytime /
book a counsellor / delete what I've kept. In Incognito, a gentle "this is the only copy"
line and a "Copy / Print this summary" action.

**8 · Errors and empty states.** Friendly inline notices with a "Try again" action (never
technical); a "this conversation timed out on our side — start a new one" card; an offline
banner; a model-loading state. Warm amber accent, never red.

---

# Part C — Detailed requirements

## C1. Product context

**What it is.** I-Turn is a first, low-stakes place for university students to talk
about how they're doing. A local/remote language model writes warm replies; everything
important (safety detection, scoring, what happens next) is deterministic code, not the
AI. The student can stay anonymous, chooses whether anything is remembered, and is
*offered* — never pushed into — a standard 21-statement questionnaire (DASS-21).

**What it is not.** A therapist, a diagnostic tool, an emergency service, or a friendly
mascot. The UI must never imply any of those.

**Audience.** Students 17–25 at an Indian university (Bengaluru). Mostly Android phones
on campus Wi-Fi or mobile data. Often late evening. Some will be stressed, anxious or in
crisis. English for the pilot; the product supports Hindi, Kannada, Tamil, Telugu,
Malayalam, Marathi and Bengali later, so typography must accommodate those scripts.

**Emotional goals** (design decisions should be traceable to these):
- *Safe:* nothing feels like surveillance, a form, or a test.
- *Unhurried:* no timers, streaks, urgency, or "almost there!" energy.
- *In control:* every choice is the student's, visible, and reversible where possible.
- *Honest:* plain about what is stored, and about being an AI, not a person.
- *Reachable help:* a human helpline is at most one tap away on every screen.

**Success looks like:** a first message sent within ~30 seconds of loading; a student in
distress reaches a phone number in one tap; no one feels judged, scored or "processed".

## C2. Hard constraints

| # | Requirement |
|---|---|
| T1 | **MUST** be implementable as plain HTML + CSS + vanilla JS. No framework, no build step. (The app is a static file served by FastAPI.) |
| T2 | **MUST NOT** make any third-party request at runtime: self-host fonts (WOFF2, subset, `font-display: swap`), no CDN, no analytics, no trackers, no external images. *(The current page loads Google Fonts, which contradicts the privacy story — replace it.)* |
| T3 | **MUST NOT** require API changes to render the screens below, except items tagged **[needs backend]**. The data each screen gets is in C9. |
| T4 | **MUST** render server text exactly as sent. The only inline markup in server text is `**bold**`, `\n` line breaks and `•` bullets. **Questionnaire statements and answer labels must never be reworded, truncated or restyled in a way that changes meaning** (they are copyrighted, validated instrument text). |
| T5 | **MUST** work on a low-end Android phone: under ~100 KB of CSS+JS (excluding fonts), no heavy animation libraries, no layout that needs a GPU. |
| T6 | **MUST** support light and dark themes: follow `prefers-color-scheme` by default, with a manual toggle (light / dark / system) remembered in `localStorage`, wrapped in try/catch because storage can be blocked. |
| T7 | **MUST** tolerate variable content: assistant replies run 1–6 sentences; student messages up to 4,000 characters; very long unbroken strings; names 3–40 characters. |
| T8 | **SHOULD** ship a print stylesheet for the end-of-session summary. |

## C3. Visual direction

**Personality words:** quiet · warm · literary · unhurried · trustworthy · human.
**Reference feel:** a well-set paperback, a Day One / iA Writer focus view, a handwritten
letter — not Headspace/Calm illustration, not a SaaS dashboard, not a messaging app.

**Signature touches** (subtle, not decorative noise):
- Headlines fade in slowly on first load.
- An abstract "turn" motif — a single soft curved line (the "I-Turn" idea of a turning
  point) — used sparingly: as the wordmark accent, a section divider, and the loading
  indicator. No literal arrows, no mascot.
- The end-of-session summary feels like a folded note: the student's own words set as a
  small anthology of quotes.

**Avoid (repeat of the master prompt, because AI tools default to these):** purple/blue
gradients, glassmorphism, neumorphism, emoji, robot/sparkle icons, stock people, medical
symbols, Material/Tailwind-demo look, drop-shadow-heavy cards, red anywhere.

### Colour tokens (starting point — refine hue-consistently, but keep the sage/paper family)

| Token | Light | Dark | Use |
|---|---|---|---|
| `--ground` | `#EDEAE3` | `#161A15` | page background |
| `--surface` | `#F7F5F0` | `#1D221C` | inputs, cards |
| `--ink` | `#22271F` | `#E4E2D9` | body text |
| `--muted` | `#6E756B` → **`#565D53`** | `#8E958A` | secondary text |
| `--accent` | `#4E6A50` | `#9BB59B` | primary actions, selection |
| `--accent-soft` | `#DDE4DA` | `#283028` | student message, selected card |
| `--line` | `#D6D2C8` | `#2F362E` | decorative hairlines |
| `--line-strong` *(new)* | **`#7F8478`** | **`#68725F`** | borders of inputs and buttons |
| `--warn` | `#8A5A2B` | `#C89860` | notices and errors (warm amber, **not red**) |

### Contrast findings (measured on the current page — fix these)

| Pair | Ratio | Result |
|---|---|---|
| Body text on ground (light / dark) | 12.7 / 13.6 | pass |
| Muted text on ground (light) | **3.95** | **fails AA (needs 4.5)** |
| Muted text on surface (light) | **4.36** | **fails AA** |
| Button label on accent | 5.0 (light) / 8.0 (dark) | pass |
| Input border vs surface (light / dark) | **1.39 / 1.30** | **fails the 3:1 non-text rule** |

The muted colour is used for form labels, the **privacy notice**, progress text and the
summary's meta line — so the most important explanatory text is currently the hardest
to read. The replacement values above pass: muted `#565D53` is 5.7 : 1 on ground and
6.2 : 1 on surface; light `--line-strong` is 3.5 : 1, dark `--line-strong` is 3.2 : 1.
Meaning must never rely on colour alone.

### Typography

- **Serif** for the conversation, headlines and questionnaire statements — a warm,
  optical-size serif in the Newsreader family (light 300 for display, 400 body).
  **Sans** (system UI stack) for small chrome only: labels, buttons, meta.
- Body 18 px / line-height 1.6; questionnaire statement ~20 px; small chrome never
  below 13 px. Left-aligned, ragged-right, never justified. Reading measure 60–70 characters.
- **Indic scripts (MUST plan for it):** provide Noto Serif/Sans fallbacks for Devanagari,
  Kannada, Tamil, Telugu, Malayalam and Bengali; increase line-height to ~1.75 when
  `lang` is not English; test that nothing clips ascenders/matras.
- Scale (suggested): 13 / 15 / 18 / 20 / 26 / 42 px. Headline fluid up to ~2.6 rem.

### Shape, space, motion, icons

- Spacing on an 8 px grid. Radii from a small scale (the current 3 px "paper" corners
  are a valid direction; a slightly softer 8–12 px is also fine — pick one and be
  consistent). Prefer hairlines to shadows.
- Motion: 150–250 ms ease-out fades and small rises; typing indicator breathes slowly
  (~4 s cycle). **MUST** honour `prefers-reduced-motion` (no animation at all).
  **No motion on the crisis screen.**
- Icons: minimal 1.5 px line icons only where they help (send, close, theme, info, phone,
  shuffle). Optional, no illustration required. No emoji anywhere.

## C4. Screens and requirements

### Screen 1 — Welcome / gate

**Purpose:** get the student to a first message with informed, unpressured choices.

| ID | Requirement |
|---|---|
| G1 | Headline **"Tell me what's happening."** and subline **"No account, no real name. Start wherever you want — there's no right way in."** MUST NOT ask for email, phone, real name, or any account. |
| G2 | Name field labelled **"Pick a name to go by"**. Pre-filled with a friendly generated alias, editable, with a **shuffle** button to generate another **[new front-end]**. The API accepts 3–40 characters; show inline validation "Use 3–40 characters." **[needs decision]** — current default is a machine-like `U_83F91A` shared by everyone who doesn't change it. |
| G3 | Language selector labelled "Language", options come from the server. If only one option is returned (English-only pilot), show it as static text, not a dropdown. |
| G4 | Mode as **two large selectable cards** (radio semantics, one required): **Incognito** — "Nothing is kept. Close the tab and it's gone." and **Story** — "Remembers you between visits. Delete it whenever." Default: Incognito. Selected state is obvious without colour alone (check mark + border weight). |
| G5 | The **privacy notice must be visible without interaction** (not collapsed, not a tooltip) and comfortably readable (≥ 15 px, ≥ 4.5:1). Exact text in C8. Bold words render as emphasis. |
| G6 | If **Story** is selected, show one explicit consent line before Start, e.g. "I understand this conversation will be saved under this name." (checkbox, required for Story only) **[new front-end]**. |
| G7 | Primary button **"Start talking"**. States: default, hover, focus, disabled (invalid name), loading ("Starting…", disabled), error ("Couldn't start. Try again."). |
| G8 | A one-line honest disclosure such as "I'm an AI, not a person." near the button **[needs decision]** (the assistant is instructed to say so if asked). |
| G9 | The persistent **"Need help now?"** link (see Global) is present. |

### Screen 2 — Conversation

| ID | Requirement |
|---|---|
| C1 | Slim top bar: small "I-Turn" wordmark, mode label ("Incognito" / "Story"), "Need help now?", theme toggle. Must not compete with the conversation. |
| C2 | First assistant message on start: **"I'm listening. Take your time."** For a returning Story user: **"Good to see you again. Where did we leave things?"** |
| C3 | Assistant messages: serif text on the page, left-aligned, no bubble chrome or avatar (the AI is not a character). Student messages: right-aligned, soft accent block, max ~32 rem wide. |
| C4 | System notices (errors/safety): sans, left border in `--warn`, visually distinct from both speakers. |
| C5 | Typing indicator: three softly breathing dots, announced to screen readers ("I'm thinking…"), replaced by the reply. Replies typically arrive in 1–5 s. |
| C6 | Composer fixed to the bottom, respecting phone safe areas and the on-screen keyboard (it must stay visible above the keyboard). Auto-growing text area (1–6 lines), placeholder **"Whatever's on your mind."** |
| C7 | **Enter sends, Shift+Enter adds a line** (show the hint on desktop only). **Send** is disabled when empty and while a reply is in flight (prevents double-sends). |
| C8 | Character counter appears only near the 4,000 limit. |
| C9 | **"Done"** (ghost) ends the session. It MUST ask for confirmation first **[new front-end]**: "Finish this session?" with "Finish" / "Keep talking". In Incognito add: "Nothing is kept — the summary is the only copy." |
| C10 | Auto-scroll to the newest message, **unless the student has scrolled up**; then show a small "Jump to latest" pill **[new front-end]**. |
| C11 | If sending fails, keep the message visible, show a friendly notice with a **"Try again"** button that resends it **[new front-end]** (the server rolls the failed turn back, so resending is safe). |
| C12 | Long threads stay fast and legible; no timestamps by default (MAY reveal on hover/long-press). |

### Screen 3 — Questionnaire offer (inline card)

| ID | Requirement |
|---|---|
| O1 | Inline card in the conversation flow, gentle but distinct from a normal reply. Text is the server's `prompt` (exact copy in C8). |
| O2 | Two buttons, **"Sure"** and **"Not now"** (labels come from the server), **identical size, weight and prominence**. No pre-selection, no nudging colour on "Sure". |
| O3 | After a choice the buttons disappear, leaving a quiet one-line record ("You chose to skip. It's here if you change your mind." / "Starting the questionnaire."). |
| O4 | The composer stays usable. Typing instead of tapping must not feel like an error. |

### Screen 4 — Questionnaire (DASS-21)

| ID | Requirement |
|---|---|
| Q1 | **One statement at a time.** Line above: "Over the past week — statement N of 21". Statement text large (~20 px serif), verbatim from the server. |
| Q2 | **Four full-width answer rows**, each showing the numeral 0–3 *and* the full label (C8). Min height 48 px, wrap long labels, whole row tappable. Radio semantics; arrow keys move between rows. |
| Q3 | **Equal visual weight** for all four. **No** colour ramp, sliders, faces or emoji — the scale is clinical and must not be visually "graded". |
| Q4 | Progress is quiet: "N of 21" and a thin single-colour line. No percentages, no encouragement. |
| Q5 | After an answer, collapse that item to one line ("You answered: 2 — Applied to me to a considerable degree…") and show the next. |
| Q6 | If the student types instead of tapping, the server may **suggest** a rating ("Sounds like about 2 — … That right?"). Show the suggested row with a subtle ring **but never select it** — the student must tap to confirm. If the server says it needs an explicit answer, show "Sorry, let me be precise about this one." with the four rows. |
| Q7 | A between-statements assistant line (one short sentence) may appear; keep it visually secondary. |
| Q8 | **"Stop for now"** always visible; stopping ends the questionnaire without scoring or showing bands, with "That's completely fine. It's there whenever you want it." **[needs backend]** — the API currently has no stop; the copy in the offer already promises it. |

### Screen 5 — Results

| ID | Requirement |
|---|---|
| R1 | Show the server message: **"That's all 21. These are screening bands, not a diagnosis — they describe the past week, not you."** |
| R2 | Three rows (Depression, Anxiety, Stress) each with the **band word** from the server: Normal · Mild · Moderate · Severe · Extremely severe. **[needs decision]** — clinical team may prefer softer display labels for the three areas; item text itself must not change. |
| R3 | A subtle **five-step marker** in a single hue shows position on the scale. **No traffic-light colours, gauges, pie charts, percentages or raw scores.** Never colour alone — the band word is always text. |
| R4 | If the server sets `offer_referral` (Severe / Extremely severe, or elevated risk earlier), show an optional gentle card: "You can talk to a counsellor without explaining yourself first." with an action **[needs decision + backend]** — the flag exists but nothing books or contacts anyone yet. |
| R5 | A soft invitation to continue: the composer remains and the assistant responds to how they feel about seeing it. |
| R6 | Partial completion MUST NOT show bands to the student. |

### Screen 6 — Crisis / safety (session halted)

Triggered when the server returns `session_halted: true`. This is the screen that
matters most; every requirement here is a **MUST** unless marked.

| ID | Requirement |
|---|---|
| S1 | The conversation is replaced or overlaid by a **focused, still, spacious panel**. No red, no warning triangle, no flashing, no animation, no alarm iconography. Warm neutral surface. |
| S2 | Show the fixed message exactly (C8). Text ≥ 18 px; **AAA contrast (≥ 7:1)**. |
| S3 | Each resource is a **large call row (≥ 56 px)**: Tele-MANAS **14416**, Tele-MANAS **1-800-891-4416**, the university counselling line(s) with hours, and **112** for immediate danger. On phones each is a real `tel:` link. On desktop show the number large with a **Copy** button. |
| S4 | **The campus row appears only when a real number is configured.** The server currently returns the placeholder text `<< fill in before pilot >>`; the UI MUST NOT render a value containing `<<` — omit the row instead. |
| S5 | Also list "Someone you trust who is physically near you — a friend, a warden, family". |
| S6 | **Keep a small one-line composer** so the student can still write: "You can write here if you want. You don't have to." The server replies "I'm still here. Have you been able to reach someone?" **[needs decision]** — the current UI hides the composer entirely. |
| S7 | No "Done"/summary pressure on this screen; a quiet "Close" may lead to the summary later. |
| S8 | Must work with slow networks and minimal JS; the phone numbers must be visible even if a script fails. |

### Screen 7 — End-of-session summary

| ID | Requirement |
|---|---|
| E1 | Headline **"That's where we'll leave it."** Meta line: length of the chat, plus " · nothing was kept" in Incognito. |
| E2 | **"You talked about"**: list of `{about, you_said}` shown as small **pull-quotes of the student's own words** with a tiny label above each. Hidden entirely when empty. (Incognito summaries have none.) |
| E3 | If the questionnaire was completed, show the band rows as in Results. Otherwise show the server note: "You didn't take the questionnaire this time. That's completely fine — it's there whenever you want it." |
| E4 | Server "next" copy is three lines (C8). Design them as **three quiet action rows**: *Come back anytime*, *Book a counsellor*, *Delete what I've kept*, plus **"Start a new conversation"**. **[needs decision]** — the counsellor line promises a background handover and the delete line promises deletion, and neither exists in the UI or is safe to expose without student sign-in yet. Design them, but don't ship the buttons until backed. |
| E5 | **Incognito:** a clear gentle line — "This is the only time you'll see this." — and **Copy / Print this summary** **[new front-end]** (uses the print stylesheet). |
| E6 | **Story:** "In Story mode I'll remember where we left off." and how to come back. |

### Screen 8 — Errors and empty states

Every state below needs a designed treatment (warm, plain, no jargon, no stack traces,
never red). The server returns a single sentence in `detail`; the UI decides how to frame it.

| State | Treatment |
|---|---|
| Message failed to send | Inline notice + **Try again** (C11). |
| AI service unavailable / slow / interrupted | Inline notice, "Try again", auto-recovers when it's back. Server wording is developer-flavoured today ("Check that the AI server … AI_BASE_URL is correct") — students should see a friendly version; keep the technical text in a collapsible **Details** shown only in a dev build **[needs decision]**. |
| Model still loading | "I'm just getting ready — give me a minute." with a gentle loading treatment. |
| Session lost (server restarted, "session not found") | Full-width card: "This conversation timed out on our side. Start a new one when you're ready." + button. |
| Offline | Slim banner: "You're offline. Your message will send when you're back." (MAY queue.) |
| First load | Fast, no spinner needed; avoid layout shift when the language list arrives. |
| Very long message / word | Wraps; never horizontal scroll. |

### Global elements

| ID | Requirement |
|---|---|
| X1 | **"Need help now?"** on every screen (top bar or quiet corner link). Opens a **bottom sheet / modal** with the same call rows as the crisis screen (Tele-MANAS, campus if configured, 112). Data is already in `/api/meta` → `crisis_resources`. **[new front-end]** Modal is accessible: focus trap, Esc closes, focus returns. |
| X2 | Theme toggle (light / dark / system). |
| X3 | Small disclaimer, e.g. "I-Turn isn't a substitute for professional care and isn't for emergencies." **[needs decision]** (copy sign-off). |
| X4 | Dev-only status dot (green ready / amber loading / grey unreachable) from `GET /api/ai/health`, shown only with `?dev=1` **[new front-end]**. |

## C5. Components (design each with every state)

States for interactive components: default · hover · focus-visible · active · disabled ·
loading · error.

`Button` (primary / secondary / ghost — **no red "danger" style**) · `TextInput` ·
`Select` · `Composer` (auto-growing textarea + Send + Done) · `SelectableCard`
(mode) · `Message` (assistant / student / system) · `TypingIndicator` ·
`InlineCard` (offer, referral) · `AnswerRow` (radio) · `ProgressLine` ·
`BandRow` + `ScaleMarker` · `ResourceRow` (call / copy) · `PullQuote` ·
`BottomSheet/Modal` · `Banner/Notice` · `ThemeToggle` · `StatusDot` · `Wordmark`.

## C6. Accessibility (WCAG 2.2 AA minimum; AAA text contrast on the crisis screen)

- Complete keyboard operation; logical focus order; **visible focus ring** (≥ 2 px,
  ≥ 3:1) on every control; focus moves sensibly when screens change (e.g. to the new
  headline or first control) and after dismissing a modal.
- The conversation is a **live region**: `role="log"` with `aria-live="polite"`; the
  typing indicator sets `aria-busy`. New assistant messages are announced; the student's
  own messages are not re-announced.
- Mode cards and answer rows use proper **radio-group** semantics with labels; errors are
  programmatically tied to their fields (`aria-describedby`).
- Touch targets ≥ 44 × 44 px (crisis rows ≥ 56 px); spacing prevents mis-taps.
- Text reflows at 200 % zoom and 320 px width with no horizontal scroll; survives
  user text-spacing overrides.
- Honour `prefers-reduced-motion`, `prefers-color-scheme` and `prefers-contrast`.
- No meaning by colour alone (band words, selected states, errors all have text/shape cues).
- Set `<html lang>` to match the chosen language so screen readers pronounce correctly.
- Dyslexia-friendly by default: left-aligned, generous line and paragraph spacing, no
  justified text, no all-caps blocks, no italic body text (the current typing indicator
  uses italics — avoid).
- Nothing flashes. No autoplay audio or video.

## C7. Responsive and platform

- **Mobile-first**, designed at 360 × 640 and 390 × 844; verify at 768 and 1280.
- One centred reading column, max ~38–42 rem, generous side margins on desktop; the
  composer spans the viewport width with its content aligned to the column.
- Respect `env(safe-area-inset-*)` (notches, home bar). Keep the composer above the
  on-screen keyboard (`visualViewport`). Landscape phones must remain usable.
- Touch and mouse both first-class; no hover-only affordances.

## C8. Voice and copy deck

**Voice:** plain, warm, second person, sentence case, short sentences. No jargon, no
clinical vocabulary, no exclamation marks, no emoji. Never "user", "patient", "session"
in student-facing text. Never promise confidentiality we don't control, never "I'll
always be here".

**Exact strings the product shows today** (from the running app):

- Welcome: "Tell me what's happening." · "No account, no real name. Start wherever you
  want — there's no right way in." · "Pick a name to go by" · "Language" · "How should
  this be remembered?" · "Start talking"
- Modes: "Incognito — Nothing is kept. Close the tab and it's gone." ·
  "Story — Remembers you between visits. Delete it whenever."
- **Privacy notice (server text):**
  "Two things before we start, plainly. **Incognito** keeps nothing. Close the tab and
  this conversation is gone — there is no copy. **Story** remembers you between visits
  under a made-up name you choose, so you don't start from scratch each time. You can
  delete all of it whenever you want. One exception, in both modes: if you say something
  that suggests you might be in danger, a record that it happened goes to the counselling
  department. Not what you said — that it happened. We'd rather tell you that now than
  surprise you with it later."
  **[needs decision]** — "goes to the counselling department" describes intended
  behaviour; alerts are not wired up yet. Fix the copy or the behaviour before launch.
- Conversation: "I'm listening. Take your time." · "Good to see you again. Where did we
  leave things?" · placeholder "Whatever's on your mind." · "Send" · "Done" ·
  failure: "That didn't go through: …" (design a friendlier frame).
- **Offer:** "There's a short standard questionnaire I can walk you through — 21
  statements, and for each one you tell me how much it applied to you over the past
  week. Takes about three minutes. It gives us something more solid than a guess, and
  you can stop at any point. Want to do it?" — buttons "Sure" / "Not now". After "Not
  now" the server says: "No problem. What were you saying?"
- **Questionnaire frame:** "Over the past week — statement N of 21".
  **Answer labels (verbatim, do not alter):** 0 "Did not apply to me at all" · 1
  "Applied to me to some degree, or some of the time" · 2 "Applied to me to a
  considerable degree, or a good part of the time" · 3 "Applied to me very much, or most
  of the time". Prompts: "Sorry, let me be precise about this one." · "Sounds like about
  N — <label in lower case>. That right?"
- **Results:** "That's all 21. These are screening bands, not a diagnosis — they
  describe the past week, not you." Band words: Normal, Mild, Moderate, Severe,
  Extremely severe.
- **Crisis message (fixed, written by the team — do not rewrite):**
  "I want to stop and stay with what you just said, because it matters more than
  anything else we were doing. I'm not the right kind of help for this, and I don't want
  to pretend otherwise. Please talk to someone who is — right now if you can:
  • Tele-MANAS, free and 24x7: **14416** or **1-800-891-4416**
  • The university counselling department: {campus number}
  • Someone you trust who is physically near you — a friend, a warden, family
  If you're in immediate danger, call **112**. I'm keeping this conversation open. You
  don't have to say anything more to me." · follow-up: "I'm still here. Have you been able
  to reach someone?"
- **Summary:** "That's where we'll leave it." · "Nothing was kept" · "You talked about" ·
  "These describe the past week, not you. They're a starting point for a conversation,
  not a label." · "You didn't take the questionnaire this time. That's completely fine —
  it's there whenever you want it." · Next: "Come back anytime. In Story mode I'll
  remember where we left off." / "You can book a counsellor without explaining yourself
  first — they'll already have the background if you want them to." / "Delete everything
  I've kept, whenever you want, no questions." · Incognito: "Incognito — nothing was kept.
  This is the only time you'll see it."

## C9. Data contract (what each screen receives)

The UI talks to JSON endpoints. Every error is an HTTP 4xx/5xx with a `detail` string.

| Call | Sends | Returns (fields the UI uses) |
|---|---|---|
| `GET /api/meta` | — | `languages[]`, `privacy_notice` (text with `**bold**` and blank lines), `crisis_resources{national{name,numbers[]}, campus{name,numbers[],hours}}` |
| `POST /api/start` | `pseudonym` (3–40), `mode` (`incognito`\|`story`), `language` | `session_id`, `mode`, `returning` |
| `POST /api/turn` | `session_id`, `text` (≤ 4000) | `message`; optional `offer{prompt, actions[2]}`, `item{…}`/`items[…]`, `suggested`, `needs_confirmation`, `needs_explicit`, `result{bands}`, `offer_referral`, `session_halted`, `resources` |
| `POST /api/instrument/accept` · `/decline` · `/answer` | `session_id` (+ `item`, `value` 0–3) | next `items[{number, text, anchors{0..3}, time_frame}]` + `progress{answered,total}`, or `phase:"post"` with `result{bands, referral_indicated}` and `message` |
| `POST /api/end` | `session_id` | `mode`, `report{ length, you_talked_about[{about, you_said}], screening_bands, screening_note, next[], ephemeral }` |
| `GET /api/ai/health` | — | `status` (`ok`\|`loading`\|`error`\|`unreachable`), `model` — dev only |

Notes: the server sends questionnaire items in blocks of three; the UI shows one at a
time (keep that). Result objects also contain raw scores — **the student UI must not
show them**. Counsellor-facing routes exist but are not part of this UI.

## C10. Later / out of scope for this pass

- **Counsellor briefing view** (separate surface, behind login, designed after the
  student UI). Sections, mirroring the existing text report: *Student* (pseudonym, session,
  duration, turns, sessions on record) · *Screening* (three areas with bands, "referral
  indicated" flag, flagged items with the statement text) · *Risk* (peak this session,
  events with times, unacknowledged count, an Acknowledge action) · *Lifestyle* (details
  with the student's own words, concerns) · *Over time* (score history) · *Transcript*
  (**withheld by default**, opened by explicit request) · a permanent caveat: "Screening
  indication only… not a diagnosis." Needs a queue of unacknowledged risk events first.
- Avatar / voice anonymity (phase 2). Full translated UI chrome for the seven Indian
  languages (design the layout to allow it now).

## C11. Open decisions (need an answer before the design is final)

1. **Default name** — friendly generated alias with a shuffle button, or keep `U_xxxxxx`?
2. **Stop the questionnaire** — needs backend; the offer copy already promises it.
3. **"Book a counsellor"** — what does the action do (form, email, phone, link)?
4. **"Delete what I've kept"** — needs a student-side secret before it can be exposed.
5. **Crisis screen composer** — keep a small text box (recommended) or read-only?
6. **Campus helpline numbers** — not configured yet; the UI must cope with none.
7. **Language list** — English only for the pilot (the safety detection is English-only)?
8. **Show bands to students at all?** — and with what labels for the three areas.
9. **"I'm an AI, not a person"** disclosure on the welcome screen.
10. **Copy that promises more than the product does** — the privacy notice (alerts) and
    the summary's counsellor/delete lines.

## C12. Deliverables and acceptance checklist

**Deliver:** every screen and state above at 390 px and 1280 px, light and dark; a
component sheet; the design tokens (colour, type scale, spacing, radii, motion timings);
annotated interactions; and exported semantic HTML/CSS with no framework if possible.

**Accept only if:**

- [ ] Reads as calm and human, not clinical, corporate or "AI-generated".
- [ ] No red, no gradients, no emoji, no stock illustration, no gamified progress.
- [ ] Contrast: all text ≥ 4.5:1 (light *and* dark); input/button borders ≥ 3:1; crisis text ≥ 7:1.
- [ ] Questionnaire text and labels appear verbatim; all four answers have equal weight.
- [ ] Crisis screen: `tel:` links, ≥ 56 px rows, no placeholder text, no motion, composer kept.
- [ ] "Need help now?" reachable on every screen.
- [ ] Privacy notice visible and readable before Start; Story requires explicit consent.
- [ ] Fully usable by keyboard and screen reader; visible focus; live region for replies.
- [ ] Works at 320–1280 px, with the keyboard open, at 200 % zoom, in reduced-motion.
- [ ] No external requests (fonts self-hosted); light and dark both complete.
- [ ] Every **[needs backend]** / **[needs decision]** item is clearly marked on the designs.
