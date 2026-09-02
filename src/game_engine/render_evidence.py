from __future__ import annotations

import re


def normalize_visible_text(value: str | None) -> str:
    """Normalize volatile numeric UI while preserving semantic state text."""
    text = (value or "").strip().lower()
    text = re.sub(r"\d+(?:\.\d+)?", "#", text)
    return " ".join(text.split())


def assess_render_surface(
    *,
    canvas_count: int,
    canvas_nonblank: bool,
    visual_change: bool,
    initial_text: str | None,
    after_text: str | None,
) -> tuple[list[str], list[str]]:
    """Classify browser rendering conservatively.

    Browser Reality Lab is a technical gate, not a visual-quality judge. A canvas
    that our sampler cannot prove painted should only be fatal when the page also
    shows no visible/dynamic evidence. Gameplay/vision layers can reject sparse or
    ugly rendering later without turning sampling uncertainty into a false crash.
    """
    errors: list[str] = []
    warnings: list[str] = []
    visible_text = bool((initial_text or "").strip() or (after_text or "").strip())

    if canvas_count and not canvas_nonblank:
        if visual_change or visible_text:
            warnings.append(
                "canvas sampler found no painted pixels, but page has visible or dynamic evidence; "
                "defer semantic blankness to gameplay/vision review"
            )
        else:
            errors.append("canvas appears blank and page produced no other visible/dynamic evidence")
    elif not canvas_count and not visible_text:
        errors.append("no canvas and no visible text detected")

    return errors, warnings
