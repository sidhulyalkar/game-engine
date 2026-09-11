import copy
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from game_engine.playtesting.scenario import digest
from game_engine.playtesting.timing import (
    SCOPE, analyze_timing, input_steps, make_timing_plan, run_timing,
    validate_timing_plan, verify_timing,
)


class TimingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        core = self.source / "Assets/Wildbound/Core"
        core.mkdir(parents=True)
        (core / "Test.cs").write_text("// validation fixture, never executed\n")
        self.plan = make_timing_plan(self.source)

    def tearDown(self):
        self.temp.cleanup()

    def fixture_trace(self):
        # Synthetic records exercise the verifier only; real C# has a separate test.
        trials = []
        for spec in self.plan["plan"]["schedule"]:
            steps = input_steps(spec)
            limit = self.plan["plan"]["expected_last_accepted_tick"][spec["mechanism"]][spec["arm"]]
            row = {"id": spec["id"], "coyote_seconds": .11, "buffer_seconds": .13,
                   "steps": [{"grounded_before": g, "jump_pressed": p,
                              "events": int(i == len(steps) - 1 and spec["delay_ticks"] <= limit),
                              "velocity_y": 14.0} for i, (g, p) in enumerate(steps)]}
            if spec["arm"] == "narrow":
                row[spec["mechanism"] + "_seconds"] = 1 / 240
            trials.append(row)
        return {"scope": SCOPE, "trials": trials}

    def test_plan_binds_complete_schedule_and_source(self):
        self.assertEqual(self.plan, make_timing_plan(self.source))
        self.assertEqual(len(self.plan["plan"]["schedule"]), 200)
        bad = copy.deepcopy(self.plan)
        bad["plan"]["schedule"][0] = bad["plan"]["schedule"][1]
        bad["plan_sha256"] = digest(bad["plan"])
        with self.assertRaises(ValueError):
            validate_timing_plan(bad)
        (self.source / "Assets/Wildbound/Core/Test.cs").write_text("// drift\n")
        with self.assertRaises(ValueError):
            run_timing(self.plan, self.source, self.root / "out")
        self.assertFalse((self.root / "out").exists())

    def test_missing_duplicate_and_changed_inputs_are_rejected(self):
        for change in ("missing", "duplicate", "input", "tuning", "nonfinite"):
            with self.subTest(change=change):
                trace = self.fixture_trace()
                if change == "missing": trace["trials"].pop()
                elif change == "duplicate": trace["trials"][0] = trace["trials"][1]
                elif change == "input": trace["trials"][0]["steps"][0]["jump_pressed"] ^= True
                elif change == "tuning": trace["trials"][0]["coyote_seconds"] = .5
                else: trace["trials"][0]["steps"][0]["velocity_y"] = float("nan")
                with self.assertRaises(ValueError): analyze_timing(self.plan, trace)

    def test_positive_control_failure_is_retained_and_summary_rechecked(self):
        trace = self.fixture_trace()
        self.assertEqual(analyze_timing(self.plan, trace)["status"], "passed")
        for trial in trace["trials"]:
            for step in trial["steps"]: step["events"] = 0
        result = analyze_timing(self.plan, trace)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["mismatches"])
        out = self.root / "evidence"; out.mkdir()
        for name, value in (("plan", self.plan), ("trace", trace), ("summary", result)):
            (out / f"{name}.json").write_text(json.dumps(value))
        self.assertEqual(verify_timing(out), result)
        result["status"] = "passed"
        (out / "summary.json").write_text(json.dumps(result))
        with self.assertRaises(ValueError): verify_timing(out)

    def test_missing_runtime_retains_error_without_curves(self):
        with patch("game_engine.playtesting.timing.shutil.which", return_value=None):
            result = run_timing(self.plan, self.source, self.root / "out")
        self.assertEqual(result["status"], "error")
        self.assertNotIn("curves", result)
        self.assertTrue((self.root / "out/plan.json").exists())

    def test_identity_repetition_detects_changed_measurements(self):
        trace = self.fixture_trace()
        trace["trials"][0]["steps"][0]["velocity_y"] += .01
        result = analyze_timing(self.plan, trace)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any(x.get("reason") == "identity_repeat_mismatch" for x in result["mismatches"]))


@unittest.skipUnless(os.environ.get("PUMA_SOURCE") and shutil.which("dotnet"), "Needs real Puma source and .NET 8")
class RealMotorTimingTests(unittest.TestCase):
    def test_actual_motor_detects_grace_windows(self):
        source = Path(os.environ["PUMA_SOURCE"])
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "timing"
            result = run_timing(make_timing_plan(source), source, out)
            self.assertEqual(result["status"], "passed", result)
            self.assertEqual(result, verify_timing(out))
            self.assertEqual([len(x["accepted_delay_ticks"]) for x in result["curves"]], [14, 1, 16, 1])


if __name__ == "__main__": unittest.main()
