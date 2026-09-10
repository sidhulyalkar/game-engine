from __future__ import annotations

import math


def analyze(trace: dict, scenario: dict) -> dict:
    """Separate contractual failures from hypotheses needing a developer's review."""
    rows = trace.get("observations", [])
    hz = trace.get("tick_hz")
    if not rows or hz != (60 if scenario["template"] == "unicorn-stampede" else 120):
        raise ValueError("Missing observations or invalid clock")
    total = sum(a["ticks"] for a in scenario["actions"])
    if rows[0].get("tick") != 0 or rows[-1].get("tick") != total:
        raise ValueError("Incomplete trace")
    findings = []
    def finding(code, severity, start, end, message, entity=None):
        findings.append(dict(code=code, severity=severity, start_tick=start, end_tick=end,
                             entity=entity, message=message))
    last = -1
    stationary = {}
    epsilon = 3 if scenario["template"] == "unicorn-stampede" else .05
    for row in rows:
        tick = row.get("tick")
        if type(tick) is not int or tick <= last:
            raise ValueError("Ticks must strictly increase")
        last = tick
        if row.get("phase") not in {"title", "play", "end", "complete"}:
            raise ValueError("Unknown phase")
        for key in ("progress", "deaths"):
            value = row.get(key)
            if key == "deaths" and value is None and scenario["template"] == "unicorn-stampede":
                continue
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError(f"Non-finite/missing {key} at tick {tick}")
        if not 0 <= row["progress"] <= 1 or (row["deaths"] is not None and row["deaths"] < 0):
            raise ValueError("Invalid measurement range")
        entities = row.get("entities")
        if not isinstance(entities, list):
            raise ValueError("Missing entities")
        seen = set()
        for entity in entities:
            identity = entity.get("id")
            if not isinstance(identity, str) or identity in seen:
                raise ValueError("Invalid or duplicate entity ID")
            seen.add(identity)
            x, y = entity.get("x"), entity.get("y")
            if any(type(v) not in (int, float) or not math.isfinite(v) for v in (x, y)):
                raise ValueError(f"Non-finite position at tick {tick}: {identity}")
            # Player stillness alone is not a bug; track autonomous unicorns only.
            eligible = row["phase"] == "play" and not row.get("paused") and not entity.get("exempt") and not entity.get("controlled")
            old = stationary.get(identity)
            if not eligible:
                stationary.pop(identity, None)
            elif old is None or math.hypot(x-old[1], y-old[2]) > epsilon:
                stationary[identity] = (tick, x, y, False)
            elif tick-old[0] >= 3*hz and not old[3]:
                finding("stationary_npc", "review", old[0], tick,
                        "Autonomous entity stayed near one point for 3s without a reported exemption; inspect replay before diagnosing a bug.", identity)
                stationary[identity] = (*old[:3], True)
        for identity in set(stationary) - seen:
            stationary.pop(identity)
    final = rows[-1]
    expect = scenario["expect"]
    if "phase" in expect and final["phase"] != expect["phase"]:
        finding("phase_mismatch", "failure", 0, total, f"Expected {expect['phase']}, observed {final['phase']}.")
    if final["progress"] < expect.get("min_progress", 0):
        finding("progress_target_missed", "failure", 0, total, "Declared progress target was not reached within this input budget; this does not prove unreachability.")
    if final["deaths"] is not None and final["deaths"] > expect.get("max_deaths", total):
        finding("death_budget_exceeded", "failure", 0, total, "Declared death budget exceeded.")
    play = [r for r in rows if r["phase"] == "play" and not r.get("paused")]
    if len(play) > 1 and play[-1]["tick"]-play[0]["tick"] >= 10*hz and max(r["progress"] for r in play)-play[0]["progress"] < .001:
        finding("no_measured_progress", "review", play[0]["tick"], play[-1]["tick"],
                "This controller produced no measured progress; inspect coverage and strategy before changing difficulty.")
    return {"status": "failed" if any(f["severity"] == "failure" for f in findings) else "passed_checks",
            "findings": findings, "final": final, "samples": len(rows), "ticks": total,
            "scope": "Instrumented deterministic scenario only; no claim of fun, human comprehension, rendering correctness, or release qualification."}
