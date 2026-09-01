from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AgentRole:
    name: str
    mission: str
    veto: str | None = None


STUDIO_ROLES = [
    AgentRole("wild_inventor", "Maximize mechanic novelty. Steal no surface theme; recombine underlying interaction principles."),
    AgentRole("gameplay_director", "Make the first 60 seconds legible, tactile, escalating, and replayable.", "Reject concepts with no mastery curve."),
    AgentRole("byte_architect", "Find procedural representations and shared systems that make ambition cheaper.", "Reject designs whose fun depends on large shipped assets."),
    AgentRole("visual_director", "Create a coherent visual grammar where motion, particles, camera, and color communicate state."),
    AgentRole("audio_director", "Make procedural audio reinforce timing, danger, success, and world identity."),
    AgentRole("onboarding_critic", "Assume a player gives the game ten seconds. Remove confusion before adding features.", "Reject unexplained control/state changes."),
    AgentRole("adversarial_designer", "Try to break dominant strategies, pacing, fairness, bosses, and scoring exploits."),
    AgentRole("competition_judge", "Score innovation, theme, gameplay, graphics, audio, controls, category fit, and memorability."),
    AgentRole("integrator", "Synthesize disagreements into the smallest coherent game, preserving the strongest interaction."),
]

CATEGORY_SPECIALISTS = {
    "desktop": AgentRole("desktop_specialist", "Optimize keyboard/mouse feel, precision, readability, and instant restart loops."),
    "mobile": AgentRole("mobile_specialist", "Design one-thumb/two-thumb touch controls with no hover assumptions."),
    "online": AgentRole("online_specialist", "Add meaningful social play while preserving a complete offline-first game."),
    "webxr": AgentRole("webxr_specialist", "Use embodied spatial interaction that could not be replaced by a flat cursor."),
}
