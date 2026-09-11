import copy
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from game_engine.playtesting.analysis import analyze
from game_engine.playtesting.commands import suite_scenarios
from game_engine.playtesting.repair import apply_repair, load_evidence, repair_prompt
from game_engine.playtesting.runner import compare, replay, run
from game_engine.playtesting.scenario import digest, validate


def scenario(template="unicorn-stampede", ticks=600):
    return validate({"version": 1, "template": template, "actions": [{"ticks": ticks, "buttons": []}]})


def row(tick, **overrides):
    return {"tick": tick, "phase": "play", "paused": False, "progress": 0.0, "deaths": 0,
            "entities": [{"id": "npc", "x": 0, "y": 0, "exempt": False, "controlled": False}], **overrides}


class ContractTests(unittest.TestCase):
    def test_unknown_fields_and_executable_actions_rejected(self):
        for field in ("eval", "script", "command"):
            s = scenario(); s["actions"][0][field] = "process.exit()"
            with self.assertRaises(ValueError): validate(s)

    def test_finite_and_integer_budget(self):
        for ticks in (True, 0, -1, 3601, 1.5):
            with self.assertRaises(ValueError): scenario(ticks=ticks)
        s = scenario(); s["actions"] *= 31
        with self.assertRaises(ValueError): validate(s)

    def test_unsupported_control_rejected(self):
        s = scenario("puma-platformer"); s["actions"][0]["buttons"] = ["whip"]
        with self.assertRaises(ValueError): validate(s)

    def test_nan_pointer_rejected(self):
        s = scenario(); s["actions"][0]["pointer"] = [float("nan"), .5]
        with self.assertRaises(ValueError): validate(s)

    def test_seeded_suite_is_repeatable_and_covers_worlds(self):
        a = list(suite_scenarios("unicorn-stampede", 13, 1234))
        self.assertEqual(a, list(suite_scenarios("unicorn-stampede", 13, 1234)))
        self.assertEqual([s["setup"]["world"] for s in a], [0, 1, 2])
        for s in a: self.assertEqual(sum(x["ticks"] for x in validate(s)["actions"]), 1234)

    def test_stationary_is_review_not_automatic_failure(self):
        r = analyze({"tick_hz":60,"observations":[row(0),row(180),row(600)]}, scenario())
        self.assertEqual(r["status"], "passed_checks")
        self.assertIn("stationary_npc", [f["code"] for f in r["findings"]])

    def test_distraction_control_and_pause_are_not_stuck(self):
        for mode in ("exempt", "controlled", "paused"):
            rows = [row(0), row(180), row(600)]
            for r in rows:
                if mode == "paused": r[mode] = True
                else: r["entities"][0][mode] = True
            result = analyze({"tick_hz":60,"observations":rows}, scenario())
            self.assertNotIn("stationary_npc", [f["code"] for f in result["findings"]])

    def test_exemption_resets_stationary_window(self):
        rows = [row(0), row(120), row(180), row(240)]
        rows[1]["entities"][0]["exempt"] = True
        result = analyze({"tick_hz":60,"observations":rows}, scenario(ticks=240))
        self.assertFalse(result["findings"])

    def test_nonfinite_and_incomplete_trace_fail_closed(self):
        for bad in (None, float("nan"), float("inf")):
            rows = [row(0),row(600)]; rows[-1]["entities"][0]["x"] = bad
            with self.assertRaises(ValueError): analyze({"tick_hz":60,"observations":rows},scenario())
        with self.assertRaises(ValueError): analyze({"tick_hz":60,"observations":[row(0),row(599)]},scenario())

    def test_missed_target_is_a_failure_not_unsolvability(self):
        s = scenario(); s["expect"] = {"min_progress":.5}
        result = analyze({"tick_hz":60,"observations":[row(0),row(600)]},s)
        self.assertEqual(result["status"], "failed")
        self.assertIn("does not prove", result["findings"][1]["message"])

    def test_comparison_rejects_different_scenarios_and_errors(self):
        with self.assertRaises(ValueError): compare({"status":"error"},{"status":"error"})
        a = {"status":"passed_checks","scenario_sha256":"a","adapter_sha256":"b"}
        with self.assertRaises(ValueError): compare(a,{**a,"scenario_sha256":"c"})


@unittest.skipUnless(os.environ.get("UNICORN_SOURCE"), "Set UNICORN_SOURCE to the pinned real template checkout")
class UnicornIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.work = Path(self.temp.name)
        self.source = Path(os.environ["UNICORN_SOURCE"])
        self.scenario = json.loads((Path(__file__).parents[1]/"examples/playtests/unicorn-tutorial.json").read_text())
    def tearDown(self): self.temp.cleanup()

    def test_real_menu_tutorial_replay_and_control_identity(self):
        a = run(self.source,self.scenario,self.work/"a")
        self.assertEqual(a["status"],"passed_checks",a.get("error"))
        self.assertEqual(sum(e["controlled"] for e in a["final"]["entities"]),1)
        b = replay(self.source,self.work/"a",self.work/"b")
        self.assertTrue(b["replay_matches"])

    def test_failure_then_bounded_repair_restores_progress_without_touching_source(self):
        broken = self.work/"broken"
        shutil.copytree(self.source/"src",broken/"src")
        p = broken/"src/expansion.js"
        original = p.read_text()
        injection = "\nupdate=function(dt){};\n"
        p.write_text(original+injection)
        baseline = run(broken,self.scenario,self.work/"baseline")
        self.assertEqual(baseline["status"],"failed")
        proposal = {"baseline_source_sha256":baseline["source"]["sha256"],
                    "hypothesis":"Remove injected no-op update to restore the real simulation",
                    "edits":[{"path":"src/expansion.js","old":injection,"new":"\n"}]}
        result = apply_repair(broken,self.work/"baseline",proposal,self.work/"repair")
        self.assertEqual(result["resolved"],["progress_target_missed"])
        self.assertEqual(p.read_text(),original+injection)
        self.assertFalse(result["release_qualified"])

    def test_unauthorized_edit_and_stale_trace_rejected(self):
        baseline = run(self.source,self.scenario,self.work/"base")
        proposal = {"baseline_source_sha256":baseline["source"]["sha256"],"hypothesis":"bad",
                    "edits":[{"path":"../../evaluator.py","old":"x","new":"y"}]}
        with self.assertRaises(ValueError): apply_repair(self.source,self.work/"base",proposal,self.work/"bad")
        (self.work/"base/trace.json").write_text('{}')
        with self.assertRaises(ValueError): load_evidence(self.work/"base")

    def test_runtime_exception_is_error_not_pass(self):
        bad = self.work/"bad"
        shutil.copytree(self.source/"src",bad/"src")
        with (bad/"src/expansion.js").open("a") as f: f.write("\nthrow new Error('injected failure');")
        result = run(bad,self.scenario,self.work/"report")
        self.assertEqual(result["status"],"error")
        self.assertIn("injected failure",result["error"])


@unittest.skipUnless(os.environ.get("PUMA_SOURCE"), "Set PUMA_SOURCE and install .NET 8 for the real core adapter")
class PumaIntegrationTests(unittest.TestCase):
    def test_real_core_replays_and_input_edges_work(self):
        source = Path(os.environ["PUMA_SOURCE"])
        s = json.loads((Path(__file__).parents[1]/"examples/playtests/puma-movement.json").read_text())
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            a = run(source,s,out/"a")
            self.assertEqual(a["status"],"passed_checks",a.get("error"))
            trace = json.loads((out/"a/trace.json").read_text())
            self.assertGreater(a["final"]["player"]["x"],trace["observations"][0]["player"]["x"])
            events = [e["name"] for r in trace["observations"] for e in r["events"]]
            self.assertEqual(sum("Jump" in e for e in events),1)
            self.assertTrue(replay(source,out/"a",out/"b")["replay_matches"])


if __name__ == "__main__": unittest.main()
