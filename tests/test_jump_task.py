import copy
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from game_engine.playtesting.jump_task import make_jump_plan, measurements, run_jump, validate_plan, verify_jump
from game_engine.playtesting.scenario import digest


class JumpEvidenceTests(unittest.TestCase):
    def row(self, tick, **kwargs):
        return dict({"tick": tick, "x": -1, "y": 1, "grounded": True, "ground_index": 0,
                     "events": 0, "deaths": 0, "jump_pressed": False}, **kwargs)

    def test_airborne_crossing_is_not_landing_and_wall_kick_is_distinct(self):
        rows = [self.row(1), self.row(2, x=3, y=2, grounded=False, ground_index=-1, events=8, jump_pressed=True)]
        result = measurements(rows, 2, 2, 2)
        self.assertFalse(result["success"])
        self.assertEqual(result["wall_kick_ticks"], [2])
        self.assertEqual(result["jump_ticks"], [])
        rows.append(self.row(3, x=3, ground_index=1, events=2))
        self.assertEqual(measurements(rows, 2, 2, 3)["landing_tick"], 3)

    def test_truncation_and_forged_geometry_rejected(self):
        with self.assertRaises(ValueError): measurements([self.row(1)], 2, -1, 240)
        with self.assertRaises(ValueError): measurements([self.row(1, ground_index=1)], 2, -1, 1)
        with self.assertRaises(ValueError): measurements([self.row(1, x=float("nan"))], 2, -1, 1)

    def test_respawn_is_retained_and_post_death_records_rejected(self):
        rows = [self.row(1, deaths=1, events=128, grounded=False, ground_index=-1)]
        result = measurements(rows, 2, -1, 240)
        self.assertFalse(result["success"]); self.assertEqual(result["deaths"], 1)
        with self.assertRaises(ValueError): measurements(rows+[self.row(2)], 2, -1, 240)

    def test_plan_schedule_drift_and_runtime_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root/"source"; core = source/"Assets/Wildbound/Core"
            core.mkdir(parents=True); (core/"Test.cs").write_text("// never executed\n")
            p = make_jump_plan(source)
            self.assertEqual(len(p["plan"]["schedule"]),416)
            bad = copy.deepcopy(p); bad["plan"]["schedule"].pop(); bad["plan_sha256"] = digest(bad["plan"])
            with self.assertRaises(ValueError): validate_plan(bad)
            with patch("game_engine.playtesting.jump_task.shutil.which", return_value=None):
                result = run_jump(p, source, root/"out")
            self.assertEqual(result["status"], "error"); self.assertNotIn("curves", result)
            (core/"Test.cs").write_text("// drift\n")
            with self.assertRaises(ValueError): run_jump(p, source, root/"drift")


@unittest.skipUnless(os.environ.get("PUMA_SOURCE") and shutil.which("dotnet"), "Requires real Puma core and .NET 8")
class RealGapTests(unittest.TestCase):
    def test_real_collision_task_and_evidence_reconstruction(self):
        source = Path(os.environ["PUMA_SOURCE"])
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)/"gap"
            result = run_jump(make_jump_plan(source), source, out)
            self.assertEqual(result["status"], "passed_controls", result)
            self.assertEqual(result, verify_jump(out))
            import json
            trace = json.loads((out/"trace.json").read_text()); trace["trials"].pop()
            (out/"trace.json").write_text(json.dumps(trace))
            with self.assertRaises(ValueError): verify_jump(out)


if __name__ == "__main__": unittest.main()
