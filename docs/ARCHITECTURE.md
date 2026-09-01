# Architecture

## Thesis

The scarce resource is not code generation. It is **search quality**: finding a mechanic worth spending 13KB on, rejecting attractive dead ends early, and preserving the useful discoveries made by different models.

`game-engine` therefore separates four concerns:

1. **Idea-space search** — deterministic mechanic recombination creates a broad, reproducible substrate before any LLM is asked to be creative.
2. **Swarm cognition** — heterogeneous agents propose, attack, mutate, and integrate candidates.
3. **Executable contracts** — every candidate becomes structured data rather than a disappearing chat transcript.
4. **Reality gates** — controls, byte budget, offline behavior, browser behavior, and playtest evidence can veto a beautiful idea.

## Swarm topology

```text
                         ┌──────────────┐
                         │ Game Brief   │
                         └──────┬───────┘
                                │
                    ┌───────────▼───────────┐
                    │ Divergence / Inventors │
                    └───────────┬───────────┘
                                │ candidate population
          ┌─────────────────────┼──────────────────────┐
          ▼                     ▼                      ▼
 Gameplay director       Byte architect        Visual/audio/XR/online
          └─────────────────────┼──────────────────────┘
                                ▼
                       Adversarial critics
                                │
                          veto + mutations
                                ▼
                      Tournament / selection
                                │
                         lineage-preserving
                              mutation
                                ▼
                            Integrator
                                │
               ┌────────────────┴────────────────┐
               ▼                                 ▼
          GameSpec                         Byte ledger
               │                                 │
               └──────────────┬──────────────────┘
                              ▼
                      prototype / package
                              ▼
               browser + human playtest evidence
                              ▼
                         next generation
```

## Why deterministic idea-space search exists

A pure LLM swarm tends to collapse toward fashionable game genres. The procedural idea-space generator deliberately mixes verbs, physics, encounter structures, and rule inversions. LLMs then *improve and interpret* unusual seeds rather than all starting from the same cultural prior.

## Artifact contract

Every run writes:

- `manifest.json` — seed, brief, engine version, population diagnostics.
- `leaderboard.json` — every concept plus all judge scores.
- `winner.json` — champion candidate and scorecard.
- `STUDIO_BRIEF.md` — human-readable north-star specification.

Future build phases add `game-spec.json`, `byte-ledger.json`, `playtest.jsonl`, replay traces, screenshots, package hashes, and lineage graphs.

## Provider boundary

The core is intentionally provider-neutral. `providers/openai_compatible.py` can talk to any OpenAI-compatible chat-completions endpoint. Additional adapters should implement one method: `complete(system, prompt) -> str`.

This lets a run assign different jobs to different models rather than pretending one model is best at every role.
