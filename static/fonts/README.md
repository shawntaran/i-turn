# Fonts

The design (from Stitch) uses two typefaces:

| Role | Font | Used for |
|---|---|---|
| Serif | **Newsreader** | headlines, the conversation, questionnaire statements |
| Sans | **Work Sans** | small interface labels, buttons, meta text |

They are **not bundled yet**, so the app currently falls back to Georgia and the
system UI font (see `--serif` / `--sans` in `../css/app.css`). Nothing is broken —
it just looks slightly less refined than the design.

## Why they are not loaded from Google Fonts

The original design pulled them from Google Fonts. That sends every student's
browser to Google on each page load, which contradicts I-Turn's privacy story
("nothing leaves the machine"). Fonts must be served from this server instead.

## To use the real fonts

Both are open-source (SIL Open Font License 1.1), so they can be committed to this
repository. Add these files here and keep each font's `OFL.txt` licence next to it:

```
static/fonts/Newsreader-Variable.woff2
static/fonts/Newsreader-Italic-Variable.woff2
static/fonts/WorkSans-Variable.woff2
```

Then add to the top of `../css/app.css`:

```css
@font-face { font-family: "Newsreader"; src: url("/static/fonts/Newsreader-Variable.woff2") format("woff2");
             font-weight: 200 800; font-style: normal; font-display: swap; }
@font-face { font-family: "Newsreader"; src: url("/static/fonts/Newsreader-Italic-Variable.woff2") format("woff2");
             font-weight: 200 800; font-style: italic; font-display: swap; }
@font-face { font-family: "Work Sans"; src: url("/static/fonts/WorkSans-Variable.woff2") format("woff2");
             font-weight: 100 900; font-style: normal; font-display: swap; }
```

`font-display: swap` shows text immediately in the fallback and swaps when the font
arrives. Subsetting to Latin keeps each file small (the page budget is ~100 KB of
CSS + JS, excluding fonts).

## Indian-language scripts

The pilot is English-only, but the UI is built to take Hindi, Kannada, Tamil, Telugu,
Malayalam, Marathi and Bengali later. When those ship, add Noto Serif / Noto Sans
for each script the same way (Noto is also OFL). The stylesheet already raises
line-height for those `lang` values.
