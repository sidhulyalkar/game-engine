# game-engine 🦄⚙️

**An evolutionary swarm studio for inventing, attacking, evolving, building, and packaging tiny web games.**

The first target is js13kGames: find genuinely interesting mechanics, make them understandable in seconds, turn procedural systems into spectacle, and keep the final ZIP under 13KB. The longer-term target is broader: Desktop, Mobile, Online, WebXR, and hybrid games generated through a rigorous multi-model design process rather than a single giant prompt.

## Why this exists

Frontier models are excellent builders, but asking one model to “make a great game” collapses several different jobs into one conversation. `game-engine` separates them into a studio:

```text
brief → divergent inventors → specialist critics → tournament
      → lineage-preserving mutations → integrator → prototype
      → browser/playtest/byte evidence → next generation
```

The system is intentionally adversarial. A Byte Architect is allowed to kill a gorgeous idea that cannot fit. An Onboarding Critic can veto an innovative mechanic nobody understands. A Gameplay Director can delete features. An Adversarial Designer tries to break scoring and bosses. Category specialists demand that Online and WebXR add something native to those media.

## v0.1: Foundry kernel

This repository now includes:

- a structured `Brief → Concept → ScoreCard` artifact contract;
- deterministic mechanic-space search to keep model swarms from converging on the same fashionable genres;
- novelty-aware deduplication;
- competition-style judging across innovation, theme, gameplay, graphics, audio, controls, byte fit, and replayability;
- finalist mutation with lineage preservation;
- reproducible run artifacts and a human-readable studio brief;
- a real ZIP-size gate at **13 × 1024 = 13,312 bytes** by default;
- a dependency-free OpenAI-compatible provider adapter for future heterogeneous swarms;
- CI tests plus an autonomous ideation smoke run.

## Try it

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e . pytest
pytest -q

game-engine ideate examples/briefs/js13k-2026.json \
  --out runs/js13k-2026 \
  --seed 13 \
  --concepts 32
```

Inspect:

```text
runs/js13k-2026/
├── manifest.json
├── leaderboard.json
├── winner.json
└── STUDIO_BRIEF.md
```

Package any playable game directory containing a top-level `index.html`:

```bash
game-engine pack path/to/game --zip dist/game.zip
```

The command fails non-zero when the ZIP exceeds the configured byte budget.

## The swarm

Core roles are defined in `src/game_engine/agents.py`:

| Role | Job |
|---|---|
| Wild Inventor | Search unusual interaction space |
| Gameplay Director | Protect clarity, game feel, mastery, pacing |
| Byte Architect | Convert ambition into procedural/shared systems |
| Visual Director | Make state readable and spectacular without shipped assets |
| Audio Director | Make WebAudio part of feedback and identity |
| Onboarding Critic | Test the ten-second comprehension threshold |
| Adversarial Designer | Break dominant strategies, bosses, scoring, fairness |
| Competition Judge | Evaluate the whole player experience |
| Integrator | Delete contradictions and ship one coherent game |

Desktop, Mobile, Online, and WebXR specialists extend the panel when those categories are targeted.

## Design principle: bytes are not the objective

The objective is **compressed player value**. Code golf that saves 200 bytes but makes controls worse is a losing trade. Conversely, a tiny procedural system that creates ten enemy behaviors, animation, audio modulation, and scoring decisions is extremely valuable.

The engine will eventually track a Pareto frontier across:

```text
fun × comprehension × mastery × novelty × theme × graphics × audio
× controls × replayability × robustness × category value ÷ compressed bytes
```

## Provider strategy

`game-engine` will not hard-code one “best model.” A provider is a tiny interface, and studio roles can be distributed across heterogeneous models. Independent first-round proposals reduce groupthink; only later do agents see the discoveries of competitors and mutate them.

The included `OpenAICompatibleClient` supports any endpoint exposing an OpenAI-style `/chat/completions` API. M1 adds provider registries, schema repair, parallel execution, token/cost ledgers, and role routing.

## Where this goes next

The important next step is **not more brainstorming**. It is closing the loop from idea to executable evidence:

1. models emit a strict `GameSpec`;
2. builder agents produce competing HTML/JS prototypes;
3. each build is minified, zipped, and byte-gated;
4. browser agents play the build without access to hidden state;
5. screenshots, errors, frame timing, deaths, confusion, and replay traces become evidence;
6. the swarm mutates the best lineage;
7. only improvements survive.

That is the path from “LLMs suggest game ideas” to an autonomous experimental game studio.

## Docs

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — system architecture and artifact contracts
- [`docs/SWARM_PROTOCOL.md`](docs/SWARM_PROTOCOL.md) — roles, debate protocol, anti-groupthink rules
- [`docs/JS13K_PLAYBOOK.md`](docs/JS13K_PLAYBOOK.md) — compressed-value design heuristics
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — path to autonomous building, browser playtesting, WebXR, and Online

## Current 2026 research target

The supplied brief targets **Unicorns and Rainbows** and asks the search system to treat theme as mechanics/state rather than wallpaper. It also keeps the Online core offline-first and reserves WebXR for interaction that actually benefits from embodiment.

---

The north star: **a tiny game should feel impossibly larger than its ZIP file.**

## Multi-model mode

The repository also has a real concurrent swarm execution path. Copy `studio.example.json`, enable the providers you actually have credentials for, map each model to studio roles, export only the relevant API-key environment variables, then run:

```bash
game-engine swarm-ideate examples/briefs/js13k-2026.json \
  --providers studio.local.json \
  --out runs/swarm-01 \
  --workers 8
```

Each provider/role assignment runs independently and failure-isolated. The run records `contributions.json`, so a flaky endpoint or malformed model response cannot silently poison the rest of the swarm. NVIDIA NIM is supported through the same adapter because its hosted endpoint is OpenAI-compatible.

## Prototype forge

Once an ideation run has produced `winner.json`, enabled providers can compete again as implementation engineers:

```bash
game-engine swarm-build runs/js13k-2026/winner.json \
  --providers studio.local.json \
  --out runs/prototypes-01
```

Each model receives the same brief and champion concept, returns a standalone `index.html`, and is isolated into its own build directory. The forge immediately creates a ZIP, checks the real compressed byte limit, records headroom/warnings/failures in `builds.json`, and never lets one broken model response erase the other contenders. This is intentionally a **prototype** gate: gameplay/browser evidence should decide which build survives next, not file size alone.
