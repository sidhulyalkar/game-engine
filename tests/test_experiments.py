import copy
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from game_engine.playtesting.experiments import make_plan, paired_effect, run_plan, seal, summarize, validate_plan
from game_engine.playtesting.features import export_features
from game_engine.playtesting.repair import load_evidence
from game_engine.playtesting.runner import run


class StatisticsTests(unittest.TestCase):
    def test_effect_is_paired_and_small_samples_are_not_overstated(self):
        self.assertEqual(paired_effect([1,3])["mean_delta"],2)
        self.assertIsNone(paired_effect([1,3])["bootstrap_95_percentile"])
        self.assertEqual(paired_effect([0]*5)["bootstrap_95_percentile"],[0,0])
        self.assertEqual(paired_effect([1,2,3,4,5]),paired_effect([1,2,3,4,5]))
        with self.assertRaises(ValueError): paired_effect([float("nan")])


@unittest.skipUnless(os.environ.get("UNICORN_SOURCE"),"Needs real Unicorn source")
class ExperimentIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        self.source=Path(os.environ["UNICORN_SOURCE"])
    def tearDown(self): self.temp.cleanup()
    def plan(self): return make_plan("unicorn-stampede",self.source,self.source,"Identity control must have zero paired effect",[13],12)

    def test_identity_study_has_three_pairs_but_one_seed_cluster(self):
        p=self.plan(); result=run_plan(p,self.source,self.source,self.root/"study")
        self.assertEqual(result["effect"]["mean_delta"],0)
        self.assertEqual(len(result["pairs"]),3)
        self.assertEqual(result["effect"]["seed_clusters"],1)
        self.assertIsNone(result["effect"]["bootstrap_95_percentile"])

    def test_plan_tamper_duplicate_schedule_and_source_drift_rejected(self):
        p=self.plan(); p["plan"]["hypothesis"]="after seeing results"
        with self.assertRaises(ValueError): validate_plan(p)
        p=self.plan(); p["plan"]["schedule"][0]=p["plan"]["schedule"][1]
        with self.assertRaises(ValueError): validate_plan(seal(p["plan"]))
        p=self.plan(); other=self.root/"other"; shutil.copytree(self.source/"src",other/"src")
        with (other/"src/core.js").open("a") as f: f.write("\n// changed\n")
        with self.assertRaises(ValueError): run_plan(p,self.source,other,self.root/"study")

    def test_errors_do_not_become_zero_scores(self):
        bad=self.root/"bad"; shutil.copytree(self.source/"src",bad/"src")
        with (bad/"src/core.js").open("a") as f: f.write("\nthrow new Error('bad variant');\n")
        p=make_plan("unicorn-stampede",self.source,bad,"Failure accounting",[13],12)
        result=run_plan(p,self.source,bad,self.root/"study")
        self.assertEqual(result["status"],"incomplete")
        self.assertEqual(len(result["errors"]),3)
        self.assertNotIn("effect",result)

    def test_features_are_prefix_causal_and_measurements_cannot_be_forged(self):
        base={"version":1,"template":"unicorn-stampede","setup":{"entry":"campaign"},
              "actions":[{"ticks":30,"buttons":["right"]},{"ticks":30,"buttons":["left"]}]}
        other=copy.deepcopy(base); other["actions"][1]["buttons"]=["up"]
        run(self.source,base,self.root/"a"); run(self.source,other,self.root/"b")
        a=export_features(self.root/"a","unicorn-lineage")["packet"]
        b=export_features(self.root/"b","unicorn-lineage")["packet"]
        prefix=sum(t<=.5 for t in a["time_s"])
        self.assertEqual(a["values"][:prefix],b["values"][:prefix])
        self.assertFalse(a["brain_alignment_ready"])
        path=self.root/"a/report.json"; report=json.loads(path.read_text()); report["final"]["progress"]=1
        path.write_text(json.dumps(report))
        with self.assertRaises(ValueError): load_evidence(self.root/"a")


if __name__=="__main__": unittest.main()
