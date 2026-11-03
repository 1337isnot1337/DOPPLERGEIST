# Avoid repeated refinement-grid work

The actual automatic MP3 run at integration `0633b9b` requested 8,405 fine
point visits across five refinement rectangles, covering only 5,863 distinct
global grid cells. Two retained flight hypotheses requested the same rectangle.
Dropping a hypothesis would discard useful ambiguity evidence.

The driver now removes cells inside previously completed refinement rectangles
before acquiring/scoring their tracks. It still searches the complete union of
all requested rectangles against every relevant track, with the same common
recording clock and ranking. Bookkeeping stores at most one rectangle per
refinement finalist; it does not accumulate a national per-cell cache. Points
outside the requested geographic bounds remain excluded. Failure and source
coverage rules are unchanged.

The regression builds two translated physical flight pairs with competing
locations. It records the requested fine-grid union and every scored point,
then compares the retained flight/coordinate/score/clock tuples with a separate
dense evaluation over that union. Coordinates and flight associations match;
the existing comparator checks scores to eight decimal places and clocks to
five. At least two flight associations must survive the comparison.

Before the fix, the test fails because 50 scored points contain only 35 distinct
cells. After the fix, all 35 cells are scored once and 15 duplicate visits are
skipped. All five tiled-search tests pass; the full base-branch suite passes
83 tests in 23.58 s. The adjacent receipt records hashes and commands.

The large automatic run's 2,542 duplicate visits are a measured workload
opportunity, not a measured wall-time speedup. This change does not tighten
uncertainty, remove competing modes or establish a supported location. The
underlying full synthetic upload's leading hypothesis is 5.5531 m from truth
but remains inconclusive for ambiguity; independent real-audio acceptance is
still open.
