# Swarm Protocol

## The studio is a debate, not a committee

Agents do not vote on vague prose. They exchange structured candidates, falsifiable criticisms, requested mutations, and vetoes.

### Core roles

- **Wild Inventor**: maximize interaction novelty.
- **Gameplay Director**: first-minute comprehension, tactile response, mastery curve.
- **Byte Architect**: make ambition cheap through shared primitives, procedural generation, compact state machines, seeded content, and data reuse.
- **Visual Director**: turn state into motion/color/shape rather than ornamental assets.
- **Audio Director**: synthesize feedback and music from gameplay state.
- **Onboarding Critic**: tests the ten-second understanding threshold.
- **Adversarial Designer**: searches for dominant strategies, boring safe play, impossible states, and boss exploits.
- **Category Specialists**: Desktop, Mobile, Online, WebXR.
- **Competition Judge**: scores the whole game, not code cleverness.
- **Integrator**: owns coherence and can delete features.

## Generation cycle

1. Generate a wide population from mechanic atoms.
2. Ask multiple models to reinterpret different seeds independently.
3. Deduplicate by semantic/mechanic similarity.
4. Judge each candidate across the current competition criteria plus byte fit and replayability.
5. Preserve a Pareto frontier, not only one scalar champion.
6. Mutate finalists around their weakest criteria.
7. Cross-pollinate only after independent exploration, so the swarm does not converge too early.
8. Produce a single integrated spec with explicit non-goals.
9. Build the smallest playable slice.
10. Feed playtest and package evidence back into the next generation.

## Anti-groupthink rules

- Do not show inventors the current champion before their first proposal.
- Keep one adversarial agent blind to model-authored rationales; show only the playable/spec evidence.
- Reward disagreement that predicts a measurable failure.
- Store failed ideas and failure reasons. Repeating a dead end without new evidence is penalized.
- Force at least one mutation to simplify rather than add.

## Useful competition metric

The system optimizes a vector:

`[fun, comprehension, mastery, novelty, theme, graphics, audio, controls, byte-fit, robustness, replayability, category-specific-value]`

A game can be visually spectacular and still lose if its first 30 seconds are confusing. Likewise, a clever compression trick earns nothing unless it buys player-visible value.
