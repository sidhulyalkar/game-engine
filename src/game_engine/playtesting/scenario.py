from __future__ import annotations

import hashlib
import json
from typing import Any

VERSION = 1
BUTTONS = {
    "unicorn-stampede": {"left", "right", "up", "down", "start", "switch", "dash", "whip", "pause", "rules"},
    "puma-platformer": {"left", "right", "up", "down", "jump", "pounce", "attack", "dash", "roll", "stalk", "interact", "pause"},
}


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def integer(value: Any, low: int, high: int, label: str) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{label} must be an integer in [{low}, {high}]")
    return value


def validate(data: dict) -> dict:
    if not isinstance(data, dict) or set(data) - {"version", "template", "seed", "setup", "actions", "expect"}:
        raise ValueError("Unknown scenario field or invalid scenario")
    if data.get("version") != VERSION:
        raise ValueError("Unsupported scenario version")
    template = data.get("template")
    if template not in BUTTONS:
        raise ValueError("Unsupported template")
    seed = integer(data.get("seed", 13), 0, 2147483647, "seed")
    setup = data.get("setup", {})
    allowed = {"world", "difficulty", "entry"} if template == "unicorn-stampede" else {"world"}
    if not isinstance(setup, dict) or set(setup) - allowed:
        raise ValueError("Unknown setup field")
    setup = dict(setup)
    setup["world"] = integer(setup.get("world", 0), 0, 2, "world")
    if template == "unicorn-stampede":
        setup["difficulty"] = integer(setup.get("difficulty", 0), 0, 3, "difficulty")
        setup["entry"] = setup.get("entry", "menu")
        if setup["entry"] not in {"menu", "tutorial", "campaign"}:
            raise ValueError("Unsupported entry")
    actions = data.get("actions")
    if not isinstance(actions, list) or not 1 <= len(actions) <= 2000:
        raise ValueError("Provide 1–2000 actions")
    normalized = []
    for action in actions:
        if not isinstance(action, dict) or set(action) - {"ticks", "buttons", "pointer"}:
            raise ValueError("Unknown action field")
        ticks = integer(action.get("ticks"), 1, 3600, "ticks")
        buttons = action.get("buttons", [])
        if not isinstance(buttons, list) or any(not isinstance(b, str) or b not in BUTTONS[template] for b in buttons):
            raise ValueError("Unsupported button")
        if len(set(buttons)) != len(buttons):
            raise ValueError("Duplicate button")
        item = {"ticks": ticks, "buttons": sorted(buttons)}
        if "pointer" in action:
            p = action["pointer"]
            if template != "unicorn-stampede" or not isinstance(p, list) or len(p) != 2 or any(type(v) not in (int, float) or not 0 <= v <= 1 for v in p):
                raise ValueError("pointer must contain two normalized screen coordinates")
            item["pointer"] = p
        normalized.append(item)
    if sum(a["ticks"] for a in normalized) > 18000:
        raise ValueError("Scenario exceeds 18000 simulation ticks")
    expect = data.get("expect", {})
    if not isinstance(expect, dict) or set(expect) - {"phase", "min_progress", "max_deaths"}:
        raise ValueError("Unknown expectation")
    if "phase" in expect and expect["phase"] not in {"title", "play", "end", "complete"}:
        raise ValueError("Unknown expected phase")
    if "min_progress" in expect and (type(expect["min_progress"]) not in (int, float) or not 0 <= expect["min_progress"] <= 1):
        raise ValueError("min_progress must be in [0,1]")
    if "max_deaths" in expect:
        if template == "unicorn-stampede":
            raise ValueError("Unicorn uses captures rather than player deaths; max_deaths is unsupported")
        integer(expect["max_deaths"], 0, 18000, "max_deaths")
    return {"version": VERSION, "template": template, "seed": seed, "setup": setup, "actions": normalized, "expect": expect}
