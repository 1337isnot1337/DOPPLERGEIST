# Taste-skill template gate, 2026-11-07

`GATE: OPEN 35 (rounds used up)`

The gate ran all three allowed refinement rounds: 46, 38 and 35 open findings.
No waivers were created and no skill sources were modified. This report records
remaining failures explicitly; it is not a PASS or full guide-compliance claim.

The guide requires stopping refinement after its third round. The site retains
the incumbent headline, research captions and natural document flow. These
choices leave literal template requirements unmet; they have not been waived.
Functional/browser/accessibility checks are recorded separately in
[SITE_REFRESH_VERIFICATION.md](SITE_REFRESH_VERIFICATION.md).

## Open findings

1. **no-visual** (1440, 390px): no picture, effect or mock in this section; a feature section needs a visual
   - Target: `main#main > section.section.wrap:nth-of-type(3) "From a pitch curve to a place on the map"`
   - Checker recommendation: give the section a visual: a UI fragment on a ground, real icons, or a photograph that fits

2. **text-only** (1440, 390px): the closing section is only text: no picture, icon, mock or effect in it
   - Target: `main#main > section.closing.wrap "Start with a recording."`
   - Checker recommendation: give the section a visual: a photograph that fits, the real icons, or a UI fragment on a ground

3. **copy-headline** (1440px): "A flight leaves a trace in sound." does not name what is sold (aircraft audio geolocation, aircraft, audio, geolocation, from flags); only the line under it does
   - Target: `main#main > section.hero.wrap > div.hero-copy > h1 "A flight leaves a trace in sound."`
   - Checker recommendation: put the category noun in the h1 (and who it is for, or where), in 2 to 8 words

4. **copy-headings** (1440px): "Read the sound." names no product, part, place or section (3 headings like it; at most one brand line per page) (and 2 more like it: "Test the fit.", "Start with a recording.")
   - Target: `section.section.wrap:nth-of-type(3) > ol.method-steps > li:nth-of-type(1) > h3 "Read the sound."`
   - Checker recommendation: name the thing in every heading: the product, a part, the place or a section noun

5. **section-gaps** (1440px): 280px between these sections, +67% against the median 168px
   - Target: `main#main > section.section.wrap:nth-of-type(3) / main#main > section.section.wrap:nth-of-type(4)`
   - Checker recommendation: use one gap between sections (all within 25% of each other)

6. **visual-caption** (1440px): a figcaption under the picture livermore-automatic-mp3.webp: "Recorded audio and ranked candidates. Th..."; no caption or description under any image, render or visual (house rule)
   - Target: `main#main > section.section.wrap:nth-of-type(2) > figure.evidence-figure > figcaption "Recorded audio and ranked candidates. Th"`
   - Checker recommendation: take the line away: no caption or description under, over or on any image, render or visual; a licence credit goes in one footer line

7. **visual-caption** (1440px): a figcaption under the picture discovery-overview.webp: "Moving-frequency proposals found by the ..."; no caption or description under any image, render or visual (house rule)
   - Target: `main#main > section.section.wrap:nth-of-type(4) > figure.evidence-figure > figcaption "Moving-frequency proposals found by the "`
   - Checker recommendation: take the line away: no caption or description under, over or on any image, render or visual; a licence credit goes in one footer line

8. **empty-area** (1440px): 62% of the section is empty: 63% beside content that covers under half the container, in its 238px of rows (WARN over 35%, FAIL over 50%)
   - Target: `main#main > section.closing.wrap "Start with a recording."`
   - Checker recommendation: fill the section: a picture or a second column beside the words, or more of its own content; the section stays one or two screens tall (T-height)

9. **moment-none** (1440px): a software page (--type) deals no moment: every kind carries one, two on a long page (moments.md)
   - Target: `(the page)`
   - Checker recommendation: deal one (moments.mjs pick --page software) and mount it in its own section

10. **section-height** (1440px): the section is 115px tall (0.1 screens), 785px short of one screen (900px): every section after the hero is one screen or two, 2px either way (SR-2)
   - Target: `footer.wrap "DOPPLERGEIST DocumentationLicenseCommerc"`
   - Checker recommendation: set the section to one screen or two (height: calc(var(--h,1) * 100vh), --h 1 or 2) and cut or split its content to fit

11. **section-height** (1440px): the section is 450px tall (0.5 screens), 450px short of one screen (900px): every section after the hero is one screen or two, 2px either way (SR-2)
   - Target: `main#main > section.closing.wrap "Start with a recording.Run DOPPLERGEIST "`
   - Checker recommendation: set the section to one screen or two (height: calc(var(--h,1) * 100vh), --h 1 or 2) and cut or split its content to fit

12. **one-section** (1440px): the screen at scroll 3600px (stride 4) shows 336px of section 4 and the content of 3 sections, over 24px each beside section 5: a screen shows one section (another may peek 8px, 24px WARN) (SR-4)
   - Target: `main#main > section.section.wrap:nth-of-type(4) "More flyovers. One location.DOPPLERGEIST"`
   - Checker recommendation: make each section exactly one screen or two, so a screen shows one section and no neighbour peeks

13. **container-edges** (1440px): a <a> at the top of the page, outside header.nav, main, footer.closing and nav.actionbar (SR-6)
   - Target: `a.skip "Skip to content"`
   - Checker recommendation: build the page as header.nav, a main of sections (each one in-flow .wrap plus background layers) and footer.closing

14. **container-edges** (1440px): a <header> at the top of the page, outside header.nav, main, footer.closing and nav.actionbar (SR-6)
   - Target: `header.site-header.wrap "DOPPLERGEIST OverviewExamplesHow it work"`
   - Checker recommendation: build the page as header.nav, a main of sections (each one in-flow .wrap plus background layers) and footer.closing

15. **container-edges** (1440px): a <footer> at the top of the page, outside header.nav, main, footer.closing and nav.actionbar (and 6 more like it: "A flight leavesa trace i", "An aircraft over Livermo", "From a pitch curveto a p") (SR-6)
   - Target: `footer.wrap "DOPPLERGEIST DocumentationLicenseCommerc"`
   - Checker recommendation: build the page as header.nav, a main of sections (each one in-flow .wrap plus background layers) and footer.closing

16. **container-edges** (1440px): 1 text block starts on a left line at x 706, 626px from the container's left: text starts on the container's left, or on one split line (x 623, 732, 841) (SR-6)
   - Target: `section.hero.wrap > div.doppler-demo > div.instrument-heading > span:nth-of-type(1) "The Doppler effect"`
   - Checker recommendation: start the text on the container's left, or on the one split line every split shares

17. **container-edges** (1440px): 4 text blocks start on a left line at x 101, 21px from the container's left: text starts on the container's left, or on one split line (x 623, 732, 841) (also "Recorded audio and ranked candid", "Across the recording", "Moving-frequency proposals found") (SR-6)
   - Target: `section.section.wrap:nth-of-type(2) > figure.evidence-figure > div.figure-heading > span:nth-of-type(1) "Automatic MP3 search"`
   - Checker recommendation: start the text on the container's left, or on the one split line every split shares

18. **container-edges** (1440px): a box over half the container wide runs 681-1360px, not on the container's lines at 80-1360px (SR-6)
   - Target: `main#main > section.hero.wrap > div.doppler-demo "The Doppler effectInteractive model How "`
   - Checker recommendation: run the picture or box from the container's left line to its right line, or put it in a row or a split

19. **split-pair** (1440px): the two columns of the split start 69px apart at the top: a split's columns are top-aligned, 8px either way (SR-8)
   - Target: `main#main > section.section.wrap:nth-of-type(4) > div.section-intro "More flyovers. One location.DOPPLERGEIST"`
   - Checker recommendation: top-align both columns of the split (align-items: start)

20. **split-pair** (1440px): the two columns of the split start 39px apart at the top: a split's columns are top-aligned, 8px either way (SR-8)
   - Target: `main#main > section.section.wrap:nth-of-type(2) > div.section-intro "An aircraft over Livermore.An MP3 record"`
   - Checker recommendation: top-align both columns of the split (align-items: start)

21. **edge-left** (1440px): starts at x 802.2; the lines are 80 and the column starts
   - Target: `section.section.wrap p "An MP3 recorded in Livermore, se"`
   - Checker recommendation: start it on the .wrap left line

22. **edge-left** (1440px): starts at x 802.2; the lines are 80 and the column starts
   - Target: `section.section.wrap p "DOPPLERGEIST scans the whole rec"`
   - Checker recommendation: start it on the .wrap left line

23. **screen-short** (1440px): 812px tall; one screen under the nav is 900px
   - Target: `section.hero.wrap section.hero.wrap "A flight leavesa trace in sound."`
   - Checker recommendation: make the section one full screen (--h: 1, layout-v4.md section 2)

24. **screen-height** (1440, 390px): 1113px, 1.24 screens; a section is exactly one or two (--h)
   - Target: `section.section.wrap section.section.wrap "An aircraft over Livermore.An MP"`
   - Checker recommendation: make the section exactly one or two screens (--h: 1 or 2)

25. **screen-height** (1440, 390px): 1022px, 1.14 screens; a section is exactly one or two (--h)
   - Target: `section.section.wrap section.section.wrap "More flyovers. One location.DOPP"`
   - Checker recommendation: make the section exactly one or two screens (--h: 1 or 2)

26. **screen-short** (1440, 390px): 450px tall; one screen under the nav is 900px
   - Target: `section.closing.wrap section.closing.wrap "Start with a recording.Run DOPPL"`
   - Checker recommendation: make the section one full screen (--h: 1, layout-v4.md section 2)

27. **screen-height** (1440, 390px): 450px, 0.50 screens; a section is exactly one or two (--h)
   - Target: `section.closing.wrap section.closing.wrap "Start with a recording.Run DOPPL"`
   - Checker recommendation: make the section exactly one or two screens (--h: 1 or 2)

28. **neighbour** (1440, 390px): framed, 115px of the footer shows
   - Target: `section.closing.wrap section.closing.wrap "Start with a recording.Run DOPPL"`
   - Checker recommendation: keep the next section's heading and picture out of this screen

29. **hero-fold** (1440, 390px): starts at y 88, not under the nav
   - Target: `section.hero.wrap section.hero.wrap "A flight leavesa trace in sound."`
   - Checker recommendation: the hero fills the first screen alone, its button inside it

30. **screen-short** (390px): 650px tall; one screen under the nav is 844px
   - Target: `section.section.wrap section.section.wrap "An aircraft over Livermore.An MP"`
   - Checker recommendation: make the section one full screen (--h: 1, layout-v4.md section 2)

31. **neighbour** (390px): framed, 73px of section.section.wrap section.section.wrap "From a pitch curveto a place on " shows
   - Target: `section.section.wrap section.section.wrap "An aircraft over Livermore.An MP"`
   - Checker recommendation: keep the next section's heading and picture out of this screen

32. **screen-short** (390px): 823px tall; one screen under the nav is 844px
   - Target: `section.section.wrap section.section.wrap "From a pitch curveto a place on "`
   - Checker recommendation: make the section one full screen (--h: 1, layout-v4.md section 2)

33. **screen-height** (390px): 823px, 0.97 screens; a section is exactly one or two (--h), or on a phone at least one that its content fills
   - Target: `section.section.wrap section.section.wrap "From a pitch curveto a place on "`
   - Checker recommendation: make the section exactly one or two screens (--h: 1 or 2)

34. **screen-short** (390px): 598px tall; one screen under the nav is 844px
   - Target: `section.section.wrap section.section.wrap "More flyovers. One location.DOPP"`
   - Checker recommendation: make the section one full screen (--h: 1, layout-v4.md section 2)

35. **neighbour** (390px): framed, 56px of section.closing.wrap section.closing.wrap "Start with a recording.Run DOPPL" shows
   - Target: `section.section.wrap section.section.wrap "More flyovers. One location.DOPP"`
   - Checker recommendation: keep the next section's heading and picture out of this screen

## Warnings

The gate also records nine nonblocking warnings. The full text, screenshots,
consistency JSON and layout reports are retained with the local preview receipts.
Scientific captions and the original factual copy are retained deliberately.
The original headline is the incumbent site's wording; it is not newly invented copy.
