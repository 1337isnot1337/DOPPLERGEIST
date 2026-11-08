# Public website refresh, 2026-11-07

## Follow-up after PR #437

The owner requested merging the first pass and continuing; PR #437 was merged
at `771897f`. The follow-up adds actual method plots with scroll and keyboard
stage navigation, compact model settings, an aligned page grid, and a screenshot
of the real empty upload interface. No audio was submitted to capture that UI.
Figure qualifications are preserved in visible prose and in the enlarged view.

- Completed homepage Taste build: **GATE: PASS**, zero waivers. The earlier 35
  findings are historical. A subsequent invocation returned `GATE: OFF` because
  the successful build had already closed; it was not restarted.
- All three pages: 18 layouts from 320 to 1440 pixels and 111 recorded interaction
  observations passed with zero unexpected browser errors.
- Six axe WCAG A/AA scans passed. All three method stages work by keyboard at
  1024x768 and 1440x900; reduced motion restores the static layout and all links.
- Local performance check: zero failures; warnings for the original large
  Livermore figure and the upload screenshot. A smaller screenshot variant was
  added afterward. Field Web Vitals and geolocation accuracy were not measured.
- Remaining nonblocking Taste warnings concern the instructional pinned moment,
  visual coverage/spacing, original plot palettes, contextual action labels,
  image resolution and the live pitch readout. Scientific plots keep their data
  colors; pitch text is a working measurement readout. Responsive sources serve
  the method plots and upload screenshot.
- Impeccable's remaining warnings concern the retained Geist family and padding
  detection: rendered method rows have no left border, and the footer has 30px
  of top padding. No guide/vendor source was modified. Its MIT notice is retained.
- Deployment verification is omitted at the owner's explicit request.

Local follow-up screenshots and checks are in
`/home/cinna/dopplergeist-site-refinement-preview/`. The rest of this document
records the first pass at `742b89d`, before these follow-up changes.

Scope: the three static GitHub Pages pages and their shared stylesheet/script.
Base: `a1307b621b28b5c677fa88d5793bb4d8f43726f1`. Scientific code, evidence,
experiment results and acceptance criteria are outside this change.

## Direction and sources

The incumbent serif/dark/wave identity is retained, with a split introduction and
interactive model, a charcoal/amber palette, clearer controls and evidence
hierarchy, and a method list instead of three feature cards. Reasons and motion
dials are recorded in [DESIGN.md](DESIGN.md).

User-requested guides were read from these source revisions:

- [taste-skill](https://github.com/Leonxlnx/taste-skill), `f6b7657`.
- [Impeccable](https://github.com/pbakaus/impeccable), `687bc38`.
- [anti-slop](https://github.com/miqdadbadjuber/anti-slop), `9504989`, during mode
  selected by the user in this session.

No new images, brand marks, client claims, testimonials, accounts or dependencies
were added to the website. Fonts remain local. Existing scientific captions and
qualifications are retained.

## Rendered and interaction verification

Chromium 1243 was run locally against an HTTP-served checkout. The system
browser adapter supplied `--no-sandbox` because this host does not support the
browser's default namespace sandbox. No skill source was modified.

- All three pages: 320x800, 390x844, 768x1024, 820x1180, 1024x768 and 1440x900.
  Eighteen layouts passed root-overflow and content-boundary checks. Command
  examples scroll inside their own focusable region.
- 103 interaction observations passed at mobile and desktop widths, with zero
  unexpected browser console errors or JavaScript exceptions.
- Every figure on every page opens its actual original, loads, closes with both
  Escape and the Close button, and returns focus to its link.
- Both simulations: play, pause, replay, timeline scrubbing and keyboard changes
  to speed/distance update the curve and named readouts.
- Every local navigation, section link and page transition was clicked. All
  nine distinct external URLs returned HTTP 200; external anchors were not
  verified as destinations within the GitHub page.
- The physics disclosure opens with the pointer and closes by keyboard.
- Delayed original image: visible loading status followed by the actual figure.
  Blocked original image: recovery text, original-image link and working close.
  The deliberately blocked request's console error is recorded separately.
- Reduced motion: the simulation starts still and accepts explicit playback;
  the entrance and hover transitions are disabled.
- Normal motion: automatic playback advances, stops advancing offscreen and
  resumes when the model returns. Switching the preference to reduced motion
  stops playback and removes the entrance animation.
- With JavaScript disabled: headings, explanatory SVG, content and original
  figure links remain; unavailable enhancement controls stay hidden.
- Axe-core WCAG 2 A/AA and 2.1 AA: zero detected violations across all three
  pages at 390 and 1440 pixels. The scan found and prompted the keyboard fix
  for the mobile command region. Automated scans do not certify accessibility.
- `node --check docs/site.js` and `git diff --check` passed.
- Taste's local performance run (three runs per size, 1440 and 390): zero FAILs
  and one WARN for the existing 457.9 KiB full-resolution Livermore WebP. Total
  measured transfer was 589.3 KiB on desktop and 210.9 KiB on mobile; the mobile
  figure variant was 90.4 KiB. No broken requests, measured layout shift or long
  tasks were recorded in that local run. These are lab observations, not field
  performance claims. Original scientific plot assets were retained.

Local screenshots, per-interaction receipts, accessibility results and link
responses are in `/home/cinna/dopplergeist-site-refresh-preview/`. These are
website checks, not validation of geolocation accuracy. Scientific tests were
not rerun for this static-site change. Field Web Vitals were not measured.

## Anti-slop delivery gate

Each line records a scoped check of the changed interface.

- R-02 PASS: new interface copy contains no em dash; original metadata is preserved.
- R-03 PASS: eighteen layouts fit 320 through 1440 pixels; navigation and controls have 44px targets.
- R-17 PASS: the existing 466-aircraft example remains tied to the linked experiment; no statistics added.
- R-18 PASS: no testimonials or invented identities.
- R-23 PASS: existing assets, name and navigation are retained; layout work is within the user's refresh request.
- R-24 PASS: all local navigation destinations were clicked and resolved.
- R-25 PASS: six axe A/AA scans found no contrast violations; hover/focus colors were inspected.
- R-26 PASS: 103 recorded interaction checks; no new dead controls.
- R-27 PASS: the viewer has unopened, loading, loaded and recoverable error states.
- R-28 PASS: no FAQ added.
- R-32 PASS: skip link, sliders, disclosure and dialog keyboard paths verified; visible focus retained.
- R-33 PASS: UI changes were written directly in the source; no source-rewriting helper shipped.
- R-34 PASS: one fixed theme, consistent across all three pages; no theme toggle.
- R-35 PASS: HTTP-served Chromium run, clicked local navigation and controls, zero unexpected console errors.
- R-36 PASS: no invented claims or measured-performance numbers.
- R-37 PASS: incumbent direction and explicit dials recorded before UI edits in DESIGN.md.
- R-38 PASS: original research content and plot assets preserved; no fabricated content.
- R-39 PASS: native controls, labels, focus, image alternatives and reduced-motion handling verified.
- R-40 PASS: images retain dimensions, scripts defer, fonts are local, no third-party runtime scripts added.
- R-01 PASS: flat charcoal surfaces and amber signal emphasis; no decorative gradients/glows.
- R-04 PASS: existing aircraft/microphone geometry explains the model; no generic icon set added.
- R-06 PASS: retained editorial serif and readable sans; measurement labels identify axes and controls.
- R-07 PASS: wavefronts exist inside the simulation; no decorative page grid.
- R-08 PASS: primary action is text; retained arrows denote destinations or diagram direction.
- R-09 PASS: no badges added.
- R-10 PASS: no glass or backdrop blur.
- R-12 PASS: no floating card shadows.
- R-13 PASS: no glow layer.
- R-14 PASS: research figures and a method list replace a uniform feature-card rhythm.
- R-19 PASS: one brief introduction and explicit simulation playback; no scroll reveals.
- R-22 PASS: only the existing domain model and actual experiment imagery.
- R-05 PASS: existing research narrative; split model, evidence figures and method list have different composition.
- R-11 PASS: 12px frames and 4px controls; no pill system.
- R-15 PASS: primary action says Read the method and opens that page.
- R-16 PASS: no new marketing buzzwords.
- R-20 PASS: the physical wave/curve instrument and actual aircraft evidence anchor the identity.
- R-21 PASS: dark canvas preserves the incumbent world and continuity with measurement figures.
- R-29 PASS: neutral surfaces, paper text and one amber accent; plot data retains original colors.
- R-30 PASS: no reference website cloned.
- R-31 PASS: one-line reasons for palette, layout, type, spacing, containers, imagery and motion in DESIGN.md.
- Liveliness PASS: ENERGY 2 / RHYTHM 3 / MOTION 2; the instrument is the focal point and identity motif.
- C-1..C-5 PASS: documented decisions, working controls, real content, responsive/keyboard paths and factual claims.

## Other guide checks

Impeccable context and its manual detector were run. The detector identified a
real skip-link hover contrast issue, which was fixed. Its padding warnings
were checked against computed/rendered padding (24px for method rows and physics
details, 36px for page transitions). Explicit longhands now express that padding.
The generic Geist warning is an intentional retention of the incumbent,
self-hosted type system, as documented in DESIGN.md.

The strict taste-skill template gate ended `GATE: OPEN 35 (rounds used up)`.
It improved from 46 to 38 to 35 findings across the three allowed rounds. No
waivers were created. Every remaining finding is recorded in
[SITE_REFRESH_TASTE_GATE.md](SITE_REFRESH_TASTE_GATE.md), including fixed screen
geometry, mandatory visuals in prose sections, the original headline, container
conventions and the retained scientific captions. The guide says to stop fixing
after the third round. This gate is open, independently of the passing browser
and accessibility checks; the proposed change is left unmerged for review.
