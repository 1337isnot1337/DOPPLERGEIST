"""Direct controls for benchmark timing eligibility; no flight data or timings.

Run in an uninstrumented interpreter:
    python scripts/check_benchmark_instrumentation.py
"""
import cProfile
import json
import sys

from benchmark_prepared_measurements import timing_instrumentation_active


def observed_state():
    monitoring = getattr(sys, "monitoring", None)
    tools = (() if monitoring is None else
             tuple((monitoring.get_tool(tool_id), monitoring.get_events(tool_id))
                   for tool_id in range(6)))
    return sys.getprofile(), sys.gettrace(), tools


def check(expected):
    before = observed_state()
    assert timing_instrumentation_active() is expected
    assert observed_state() == before, "Detection changed an execution hook"


def main():
    check(False)
    controls = ["ordinary interpreter"]

    profile = cProfile.Profile()
    try:
        profile.enable()
        legacy_detector_missed_cprofile = sys.getprofile() is None
        check(True)
    finally:
        profile.disable()
    check(False)
    controls.append("active cProfile")

    def hook(*args):
        return hook

    for name, getter, setter in (("legacy profile", sys.getprofile, sys.setprofile),
                                 ("legacy trace", sys.gettrace, sys.settrace)):
        original = getter()
        try:
            setter(hook)
            check(True)
            assert getter() is hook
        finally:
            setter(original)
        check(False)
        controls.append(name)

    monitoring = getattr(sys, "monitoring", None)
    if monitoring is not None:
        for tool_id in range(6):
            monitoring.use_tool_id(tool_id, "benchmark-instrumentation-control")
            try:
                # A reserved slot suffices even with no global events or
                # callbacks. Detection must not alter that reservation.
                assert monitoring.get_events(tool_id) == 0
                check(True)
            finally:
                monitoring.free_tool_id(tool_id)
            check(False)
            controls.append(f"monitoring tool {tool_id}")

    print(json.dumps({"passed": controls,
                      "legacy_detector_missed_cprofile": legacy_detector_missed_cprofile,
                      "ordinary_timing_eligible_after_controls": True}, indent=2))


if __name__ == "__main__":
    main()
