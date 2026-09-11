"""Causal, target-free feature exchange for representation experiments."""
from __future__ import annotations

import json
import math
from pathlib import Path

from .repair import load_evidence
from .scenario import digest

FEATURES = [
    {"name": "action.left", "unit": "binary", "family": "controller"},
    {"name": "action.right", "unit": "binary", "family": "controller"},
    {"name": "action.up", "unit": "binary", "family": "controller"},
    {"name": "action.down", "unit": "binary", "family": "controller"},
    {"name": "action.dash", "unit": "binary", "family": "controller"},
    {"name": "action.pause", "unit": "binary", "family": "controller"},
    {"name": "state.progress", "unit": "fraction_template_specific", "family": "privileged_state"},
    {"name": "state.progress_rate", "unit": "fraction_per_second_template_specific", "family": "privileged_state"},
    {"name": "state.player_speed", "unit": "native_world_units_per_second", "family": "privileged_state"},
    {"name": "state.player_observed", "unit": "binary", "family": "availability"},
]


def export_features(evidence: Path, family_id: str) -> dict:
    if not isinstance(family_id,str) or not family_id.strip() or len(family_id)>120:
        raise ValueError("A stable source-lineage family ID is required")
    report = load_evidence(evidence)
    trace = json.loads((evidence/"trace.json").read_text())
    s = report["scenario"]
    # Action at tick n describes the input applied to the step ending at n.
    boundaries=[]; end=0
    for action in s["actions"]:
        start=end+1; end+=action["ticks"]
        boundaries.append((start,end,set(action["buttons"])))
    index=0; values=[]; times=[]; previous=None
    for row in trace["observations"]:
        tick=row["tick"]
        while index+1<len(boundaries) and tick>boundaries[index][1]: index+=1
        buttons=boundaries[index][2] if tick>=boundaries[index][0] else set()
        player=row.get("player")
        if player is not None and (not isinstance(player,dict) or any(type(player.get(k)) not in (int,float) or not math.isfinite(player[k]) for k in ("x","y"))):
            raise ValueError("Invalid player coordinates")
        rate=speed=0.0
        if previous is not None:
            dt=(tick-previous["tick"])/trace["tick_hz"]
            rate=(row["progress"]-previous["progress"])/dt
            # World transitions and missing players are discontinuities, not velocity.
            if player is not None and previous.get("player") is not None and row["world"]==previous["world"] and row["phase"]==previous["phase"]:
                speed=math.hypot(player["x"]-previous["player"]["x"],player["y"]-previous["player"]["y"])/dt
        values.append([float(b in buttons) for b in ("left","right","up","down","dash","pause")]+[row["progress"],rate,speed,float(player is not None)])
        times.append(tick/trace["tick_hz"]); previous=row
    packet={"format":"gameplay-features-v1","evidence_scope":"instrumented_gameplay_no_neural_targets",
            "time_basis":"simulation_seconds_end_of_step","causal_support":"past_and_present_only",
            "brain_alignment_ready":False,"has_neural_targets":False,
            "template":s["template"],"world":s["setup"]["world"],"family_id":family_id,
            "recording_id":report["trace_sha256"],"source_sha256":report["source"]["sha256"],
            "scenario_sha256":report["scenario_sha256"],"adapter_sha256":report["adapter_sha256"],
            "features":FEATURES,"time_s":times,"values":values}
    return {"packet":packet,"packet_sha256":digest(packet)}
