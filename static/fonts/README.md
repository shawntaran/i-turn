# Fonts

The design (from Stitch) uses two typefaces, both bundled here and served by this
server — nothing is fetched from Google or anywhere else.

| Role | Font | File | Size |
|---|---|---|---|
| Serif | **Newsreader** | `Newsreader-Variable.woff2` | 96 KB |
| Sans | **Work Sans** | `WorkSans-Variable.woff2` | 54 KB |

Both are open-source under the **SIL Open Font License 1.1**. The licence texts are
kept next to the fonts (`OFL-Newsreader.txt`, `OFL-WorkSans.txt`) and must stay with
them if the files are copied or redistributed.

## Why self-hosted

The original design loaded them from Google Fonts, which would send every student's
browser to Google on each visit — at odds with I-Turn's privacy promise. A test
(`tests/test_ui_assets.py`) fails if the page ever references an outside host.

## What these files are

They are **variable fonts**, trimmed to what the UI uses, so a few small files cover
every weight:

- **Latin subset** (Basic Latin, Latin-1, general punctuation: curly quotes, dashes,
  bullets, ellipsis) — the standard Google Fonts "latin" range.
- **Weights 400–600 only** (regular, medium, semibold — the only ones the CSS uses).
  Newsreader keeps its optical-size axis, so headlines and body text are drawn
  differently at different sizes, as the designers intended.
- **No italic file.** Italic text is not used anywhere (it is harder to read for many
  dyslexic readers), and the CSS has a test against `font-style: italic` so the
  browser never fakes one.

Roughly 150 KB in total, cached after the first visit. `font-display: swap` shows text
immediately in Georgia / the system font and swaps when the file arrives; if a font
fails to load, the page still reads correctly.

## Regenerating or updating

Source: <https://github.com/google/fonts> → `ofl/newsreader/` and `ofl/worksans/`
(`Newsreader[opsz,wght].ttf`, `WorkSans[wght].ttf`, and each folder's `OFL.txt`).

```bash
pip install fonttools brotli

# 1. keep only the weights the UI uses
python -m fontTools.varLib.instancer "Newsreader[opsz,wght].ttf" wght=400:600 -o Newsreader-trim.ttf
python -m fontTools.varLib.instancer "WorkSans[wght].ttf"        wght=400:600 -o WorkSans-trim.ttf

# 2. Latin subset, compressed to WOFF2
U="U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+2074,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD"
pyftsubset Newsreader-trim.ttf --unicodes="$U" --layout-features='*' --flavor=woff2 --output-file=Newsreader-Variable.woff2
pyftsubset WorkSans-trim.ttf   --unicodes="$U" --layout-features='*' --flavor=woff2 --output-file=WorkSans-Variable.woff2
```

## Indian-language scripts

The pilot is English-only, but the UI is built to take Hindi, Kannada, Tamil, Telugu,
Malayalam, Marathi and Bengali later. When those ship, add **Noto Serif / Noto Sans**
for each script the same way (Noto is also OFL) and a matching `@font-face` with a
`unicode-range`, so a student only downloads the script they use. The stylesheet
already raises line-height for those `lang` values.
