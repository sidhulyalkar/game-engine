import json
from dataclasses import dataclass

from game_engine.repair import RepairForge, load_repair_candidates
from game_engine.schema import Brief, Concept


@dataclass
class FakeSpec:
    name: str = "repairer-a"


class FakeRepairer:
    name = "repairer-a"

    def complete(self, system: str, prompt: str) -> str:
        return '{"index_html":"<!doctype html><html><body><canvas id=c></canvas><script>c.width=320;c.height=180</script></body></html>","repair_notes":["bounded cleanup fixed"]}'


def _write_parent(tmp_path):
    build_dir = tmp_path / "builder-parent"
    build_dir.mkdir()
    (build_dir / "index.html").write_text("<!doctype html><html><body><canvas></canvas></body></html>")
    (tmp_path / "builds.json").write_text(json.dumps([{
        "provider": "builder",
        "build_id": "parent",
        "ok": True,
        "source_dir": str(build_dir),
        "zip_path": "x.zip",
        "compressed_bytes": 300,
        "byte_headroom": 1700,
        "warnings": [],
        "error": None,
    }]))


def _write_audit(audit_dir):
    audit_dir.mkdir()
    (audit_dir / "audits.json").write_text(json.dumps([{
        "build_id": "parent",
        "provider": "builder",
        "critic_count": 2,
        "scores": {"logic_correctness": 5.0},
        "overall": 6.2,
        "blockers": 1,
        "majors": 1,
        "verdict_votes": {"advance": 0, "repair": 2, "reject": 0},
        "status": "repair",
        "critic_audits": [],
    }]))


def test_repair_candidates_only_include_repair_status(tmp_path):
    _write_parent(tmp_path)
    audit_dir = tmp_path / "audit"
    _write_audit(audit_dir)
    rows = load_repair_candidates(tmp_path, audit_dir, max_parents=1)
    assert len(rows) == 1
    assert rows[0][0]["build_id"] == "parent"


def test_repair_forge_writes_packaged_child(tmp_path):
    _write_parent(tmp_path)
    audit_dir = tmp_path / "audit"
    _write_audit(audit_dir)
    concept = Concept(
        concept_id="abc", title="Tether", hook="hook", core_mechanic="spring",
        player_goal="score", controls="move and release", core_loop=["move", "release"],
        escalation=["faster"], visual_grammar="trails", audio_grammar="bleeps",
        category_fit=["desktop"], byte_hypothesis="canvas", risks=[], tags=[]
    )
    out = tmp_path / "repairs"
    results = RepairForge([(FakeSpec(), FakeRepairer())], max_workers=1).build(
        Brief(theme="Unicorns and Rainbows", size_limit_bytes=2048),
        concept,
        tmp_path,
        audit_dir,
        out,
    )
    assert len(results) == 1
    assert results[0].ok
    assert results[0].parent_build_id == "parent"
    assert (out / "repairs.json").exists()
    assert (out / "builds.json").exists()
