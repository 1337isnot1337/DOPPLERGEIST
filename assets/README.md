# README banner

`dopplergeist-banner.svg` is the self-contained source; the PNG is a native-size
preview. Keep the SVG filename stable because the root README embeds it.

The composition is adapted from the supplied `DOPPLERGEIST-README-refresh.zip`:
navy field, centered wordmark and subtitle, spectral traces and original aircraft
silhouette. The two target circles share the aircraft silhouette's geometric
center. The illustration is not recorded data or an accuracy claim.

## Typography and provenance

Both lines are vector outlines, shaped with HarfBuzz using the fonts' kerning
and centered on the rendered ink bounds. No font installation, embedded font
binary, stylesheet or network request is needed to display the SVG.

- **Wordmark:** genuine Geist Serif VF, version 1.001, default `ELSH=0`, 114 SVG
  units with 2.1 units of added tracking. Copyright 2026 The Geist Project Authors;
  font metadata credits WORDMARK, Vercel, Mark Davis and Andrés Briganti.
- **Subtitle:** Geist Sans, default variation settings, 24 SVG units with 0.35
  units of added tracking. The wording is “Acoustic geolocation through Doppler
  analysis”, without a period.

Fonts were obtained from [Vercel's official font page](https://vercel.com/font).
The page served these source files when the banner was prepared:

| Typeface | Official asset | SHA-256 |
| --- | --- | --- |
| Geist Serif | `GeistSerifVF-s.p.09h0rm9evi_qd.woff2` | `a306592934889c88bc2a76ea4b861d0e6877373980d665eb0e68325c2ebbefe7` |
| Geist Sans | `Geist_Variable-s.p.2wz-lhd5-5z0-.woff2` | `5c5588027e59e74e205b9d6c7fd877b261091cee367f6bb3a8d505da14cae512` |

Geist uses [SIL OFL 1.1](https://github.com/vercel/geist-font/blob/main/LICENSE.txt).
The [OFL usage guidance](https://openfontlicense.org/how-to-use-ofl-fonts/)
explicitly permits graphics made from font outlines. This repository includes
the finished lettering, not the font software.

## Illustrative model and maintenance

The dominant trace follows a constant-velocity pass at 79 m/s, a closest slant
range of 2,000 m and sound speed of 343 m/s. It plots reception time
`tau + range(tau)/c` against logarithmic observed frequency, with
`f/f0 = c/(c + d(range)/d(tau))`. The secondary tones share the same fractional
Doppler shift, with harmonic ratios 10:9:8. Frequency is higher on approach and
lower on recession, flattening at both ends. Faint irregular spectral strokes
and restrained energy changes suggest a measured signal without representing
one. These display parameters are independent of the scientific application.

For lettering changes, reacquire the genuine fonts from the official page,
shape with kerning, outline, then center the visible paths. Do not substitute
a local serif or embed raw font files. Preserve the SVG title and description
for accessibility. Recheck the white-dominant gradient, circle alignment and
subtitle at native resolution and 600 px wide after any edit.

Render previews with librsvg:

```bash
rsvg-convert assets/dopplergeist-banner.svg \
  -o assets/dopplergeist-banner-preview.png
rsvg-convert -w 600 assets/dopplergeist-banner.svg -o /tmp/dopplergeist-banner-600.png
```

## Livermore demonstration

`livermore-real-demo.png` shows a real recording and a configured search over
published flight data. It uses USGS / USDA NAIP imagery and data from Praveen
Pathak's [Zenodo dataset](https://doi.org/10.5281/zenodo.23424278) (CC BY 4.0).
[Setup, limitations and rendering instructions](../docs/LIVERMORE_DEMO.md)
explain the inferred reference and the incomplete model assessment.
