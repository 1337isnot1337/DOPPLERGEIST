# Independent finite-union decision controls

This branch supplies four independently specified contract checks for the
finite-point/reported-profile union approved by Primary in discussion #39.
It changes no production file and does not claim a localization experiment.
W4 retains implementation ownership. The controls depend on the common
independent fixture already offered in PR #74.

The predeclared checks use WGS84 direct geodesics to place a competing point at a
specified separation from the unchanged returned center:

| Control | Required behavior under the new finite scope |
| --- | --- |
| Point 600 m away with an explicitly reported 300 m sensitivity radius | Return a copied candidate array with a 900 m leading union, not merely the maximum of center distance and individual radii |
| Point 800 m away with a 300 m reported radius | Remain inconclusive because the union exceeds the 1,000 m target |
| Raw seed 600 m away and improved leading refinement share one stable ID | Preserve both returned states in the geometric calculation; the original seed score remains 1.8 and the refined score is 1.95 |
| Unprofiled finite point 150 m away; leading profile radius 100 m | The finite-point/tested-profile union is 150 m; do not invent an extra competitor profile by copying the leading radius |

The successful-scope controls also require input immutability, copied output,
unchanged candidate count/order and leading fitted parameters, unchanged
non-leading candidates, sensitivity kind and no calibration/probability labels.
Unperformed profiles remain unbounded outside this explicitly conditional scope.
The tests do not turn the finite union into calibrated uncertainty or assert that
it guarantees real-world error below its radius.

Against production source `27a2f87aa106f908a1143d2314ee07b7f4dff947` plus the exact
new test overlay, the baseline is **one passed and three expected readiness
failures**, with zero errors/skips. The prior consumer returns
`inconclusive / ambiguous_locations` for the three newly permitted finite-cluster
controls; its conservative behavior has not regressed. The exceeding-target
negative control already abstains. The native JUnit and exact source/test hashes
are preserved in `baseline.xml` and `receipt.json`.

No merge-ready PR is opened while the dependency is unimplemented. Run the exact
test file against W4's published implementation with an absolute `PYTHONPATH` to
that implementation's `src` and the fixture directory. Keep this baseline frozen
and record the actual implemented outcome separately. All historical four-event,
two-event and real-recording decisions remain their original producer outcomes.
