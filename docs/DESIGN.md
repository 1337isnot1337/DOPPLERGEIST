# DOPPLERGEIST website

Scope: the public GitHub Pages site (`index.html`, `examples.html`,
`how-it-works.html`, `site.css`, `site.js`). The upload application and scientific
pipeline are outside this visual pass.

## Design read

A working instrument with the reading pace of a field report. Preserve the
existing serif headlines, dark canvas, wave geometry and real experiment figures.
Place the model beside the introduction so the subject is clear on arrival.
The second pass aligns the page to a shared grid, pairs the method with actual
research plots, and shows the real local upload interface in the closing section.

ENERGY 2 / RHYTHM 3 / MOTION 2. An editorial introduction, interactive instrument,
broad evidence figures and an illustrated method provide the rhythm. The dealt
`pinned-chapters` moment connects each method stage to its actual plot. On phones,
under reduced motion and without JavaScript, the stages and their plots remain
ordinary document rows. Figures retain their full aspect and are never cropped.

## Decisions

- Color: charcoal and paper keep real spectrograms legible; amber marks the
  received signal, controls and primary action. Remove lavender.
- Typography: retain locally hosted Geist Serif for the established editorial
  voice and Geist for readable controls. Reserve monospace for commands.
- Layout: equal content edges on all pages; a split homepage hero directly
  connects the explanation to its working model.
- Spacing: generous separation distinguishes research stages; controls stay
  close to their readouts.
- Containers: frame the instrument and evidence; prose needs no decorative cards.
- Imagery: retain the geometric wave simulation and actual experiment plots.
  The simulation is an educational model, not audio playback or recorded data.
- Dark canvas: preserve the incumbent visual world and dark plot backgrounds
  so figures and model form one continuous reading surface.
- Motion: a brief entrance introduces the instrument; playback has pause/replay,
  stops offscreen and defaults to still under reduced motion.
- Links: a solid primary action opens the method; external arrows identify
  repository destinations. Preserve existing navigation and destinations.

## Truth and resilience

Preserve scientific qualifications: rankings are not probabilities, proposals
are not confirmed aircraft, and inconclusive runs remain inconclusive. Homepage
qualifications sit in the surrounding prose and are associated with their
figures by `aria-describedby`; enlarging a figure includes that same context.
Original figures, their links and the static model work without JavaScript. Enhancement
adds playback, scrubbing and image dialogs. Dialogs report image loading and
failure. Every control has a label, a keyboard path and visible focus.

Direction: incumbent site plus the user-requested taste-skill, Impeccable and
anti-slop guides, retrieved 2026-11-07. No generated imagery or claims are needed.
Verification is recorded in `SITE_REFRESH_VERIFICATION.md`.
