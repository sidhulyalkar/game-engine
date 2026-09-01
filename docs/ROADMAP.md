# Roadmap

## M0 — Foundry kernel (this branch)

- Structured briefs, concepts, scorecards, lineage.
- Deterministic creative search to prevent LLM genre collapse.
- Evolutionary selection + mutation.
- Competition-aware static judge panel.
- Reproducible run artifacts.
- Real ZIP byte gate.
- Provider-neutral model adapter boundary.
- CI smoke run.

## M1 — Real multi-model swarm

- Provider registry configured by `studio.toml` / environment variables.
- Parallel role assignments across GPT, Claude/Fable-style agents, Gemini, DeepSeek, Kimi, Qwen, Nemotron, and local models where APIs permit.
- Strict JSON schemas with repair/retry.
- Cost/token/latency ledger per discovery.
- Blind first-round proposals and controlled cross-pollination.

## M2 — Autonomous prototype forge (started)

Already landed in v0.1: multi-provider `winner.json -> standalone index.html` prototype races, isolated build directories, ZIP creation, byte-limit enforcement, and build ledgers.

Next:
- Split concept selection from a richer `GameSpec` contract.
- Add implementation patch rounds instead of one-shot generation.
- Minify + ZIP + byte accounting after every mutation.
- Git worktree/branch per contender.
- Automatic rollback when a mutation worsens evidence.

## M3 — Browser reality lab

- Playwright Chromium/Firefox/WebKit smoke tests.
- Deterministic input scripts, screenshot capture, console error gate.
- Instrumented replays: deaths, idle time, missed affordances, restart time, frame time.
- Visual-regression and control-latency checks.

## M4 — Agentic playtesting

- Vision-capable playtest agents get only what a human player gets: screen + controls.
- Separate designer agents never see hidden runtime state.
- Novelty/fun hypotheses are tested through behavioral traces rather than self-scoring prose.
- Human micro-playtests become first-class evidence.

## M5 — 13KB specialist evolution

- Compression-aware patch search.
- Shared code-golf transforms validated by behavior equivalence.
- Procedural rendering/audio pattern library with measured compressed cost.
- Pareto optimization across judge score, bytes, FPS, startup, and comprehensibility.

## M6 — WebXR studio

- WebXR capability contracts, controller/hand/head interaction primitives.
- Spatial comfort critic, locomotion safety, seated/standing variants.
- 3D procedural geometry and compact shader experiments.
- Device/browser verification matrix.

## M7 — Online/hybrid studio

- Offline-first game core plus optional js13k relay layer.
- Lockstep/rollback/state-sync strategy selector.
- Lag/jitter/drop simulation.
- Bots that preserve solo play.
- Social mechanic critic: networking must change the game, not just add another player sprite.

## M8 — Portfolio game factory

- Website-ready export: playable build, poster frame, short capture, README/postmortem, controls card, technical notes.
- Game genealogy browser showing how ideas evolved.
- Reusable personal design language without making every game feel identical.
