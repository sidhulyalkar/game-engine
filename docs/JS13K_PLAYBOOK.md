# js13k Playbook

## Design for compressed value

Treat bytes as a portfolio. Every system should either:

- create player decisions,
- communicate state,
- amplify game feel,
- generate reusable content, or
- remove failure risk.

Prefer one mechanic that creates many situations over many mechanics that each create one situation.

## High-leverage techniques

- Canvas 2D primitives and transforms instead of raster assets.
- Reuse simulation state as animation state.
- Seeded generators for enemy waves, arenas, palettes, and music.
- Data-oriented enemy archetypes sharing one update/render path.
- WebAudio synthesis where parameters are derived from combo, velocity, tension, health, or biome.
- Signed-distance-ish shape tricks, alpha layering, screen shake, trails, hit-stop, and camera easing for cheap spectacle.
- One action with context-sensitive depth instead of extra buttons.
- Bosses composed from existing verbs plus altered timing/space.

## Byte ledger

Before polishing, reserve approximate compressed budget buckets:

- engine + loop: 1.5–2.5 KB
- core mechanic + physics: 2–3 KB
- enemies/progression/boss: 2–3 KB
- rendering/game feel: 2–3 KB
- audio: 1–2 KB
- UI/tutorial/restart: 0.7–1.2 KB
- contingency: at least 1 KB

These are heuristics, not quotas. Compression changes the economics. The important rule is to measure the actual ZIP continuously.

## Competition reality

The 2026 theme is **Unicorns and Rainbows**. The system should force the theme into mechanics or state when possible, not merely paint generic enemies rainbow colors.

For Online, preserve an offline-complete mode and make network play additive. For WebXR, require embodied spatial interaction that would lose meaning if replaced with a mouse cursor.
