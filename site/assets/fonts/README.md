# Display typefaces

The showcase uses Noto Serif SC for Chinese display text and Cormorant Garamond for Latin display text and chapter numerals. Body text, controls and business figures keep their existing system sans-serif families. The local variable fonts retain the site's existing CSS weights; English italic captions use a real italic face.

Sources are the [Cormorant Garamond](https://github.com/google/fonts/tree/main/ofl/cormorantgaramond) and [Noto Serif SC](https://github.com/google/fonts/tree/main/ofl/notoserifsc) Google Fonts distributions, downloaded on 2026-09-11. Original SIL Open Font Licenses are preserved alongside the subsets.

| Local WOFF2 | Source TTF | Source SHA-256 | Characters |
| --- | --- | --- | --- |
| `cormorant-garamond.woff2` | `CormorantGaramond[wght].ttf` | `b20b7d9626dd956b2c5e558692ad328b1f19e3275e2782db4fa07670d83f35e0` | 450 |
| `cormorant-garamond-italic.woff2` | `CormorantGaramond-Italic[wght].ttf` | `0f48ea6abb2084537854f7174c470991a463b13036309e3b50a81511611c530d` | 449 |
| `noto-serif-sc.woff2` | `NotoSerifSC[wght].ttf` | `050080d9255a86808f2945bffac582b31ef32bc36411ce29563b4961670c66f9` | 343 |

Subset with fontTools, retaining OpenType layout features and variable weight axes; no glyph outlines were redrawn. Latin subsets cover supported characters in U+0020–024F, U+2000–206F and U+20A0–20CF. The Chinese subset covers characters at U+3000 and above used in `index.html`, `style.css`, `merchant.css` and `merchant.js`, including generated mobile text. Rebuild that subset when display copy introduces new characters. There is no runtime request to an external font service.
