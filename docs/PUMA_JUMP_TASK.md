# From jump acceptance to collision-world success

## Implemented experiment

The first gap task uses the actual `GameSession.Step` motor, collision resolution,
contact probes and death handling. A fixture replaces the authored campaign with
two stationary stone platforms. It clears enemies, pickups, hazards, discoveries
and other scenery to isolate the gap task. It never assigns Grounded during a
trial or rewrites physics. Unity rendering and the full campaign remain outside
this experiment's scope.

Spawn at (-2, 1); the departure platform spans x=-10 to 0 with top y=1. The
target starts at x=2, 4, 6 or 8 with the same height and width 30. Hold right.
For each gap, first record a no-jump reference and measure its first grounded to
airborne transition. Then freeze the rule: press at reference departure tick
plus offsets -1 through 24, holding jump after the press. Every arm gets the
same absolute input timing, regardless of its trajectory. This is an open-loop
timing sweep, not a learned human policy or a reaction-time estimate.

Compare default CoyoteSeconds (.11) with half a 120 Hz tick, keeping buffering
and other tuning fixed. Each of 208 distinct conditions has two exact repeats,
giving 416 trials plus four reference runs. Bound each run at 240 ticks or its
first death. The primary endpoint is a grounded contact with the target platform
before the first death. Airborne passage over the gap does not count. Record
ordinary jumps and wall kicks separately: a late input can recruit wall-jump
mechanics and must not be described as a coyote jump.

## Frozen expectations versus exploratory result

The hypothesis is that default coyote time increases landing success at some
delayed inputs. No winning offsets are prescribed or selected after viewing
results. A zero or adverse effect remains a valid experiment outcome.

Validity controls require identical repeat traces, no target landings in the
no-jump reference, and successful on-time (-1 offset) landings in both arms of
the easy two-unit gap. Failed controls are reported separately from treatment
effects. The four gaps and discrete offsets are a designed grid, not a sampled
population: counts do not estimate human success rates and carry no population
confidence interval. Hashes identify committed provenance, not cryptographic
proof that a deliberately forged trace was executed.

The versioned plan binds source, harness, analyzer, geometry rules, schedule and
endpoint. CI runs it from a commit made before execution and retains all step
records and outcomes. Failed attempts must be retained if the fixture needs
revision. The first execution is exploratory fixture qualification.

```bash
game-engine puma-jump-run examples/studies/puma-jump-plan.json ../puma-platformer --out runs/puma-jump
game-engine puma-jump-analyze runs/puma-jump
```

For a different source version, freeze a new plan with `puma-jump-plan` before
execution. Source changes after planning are rejected. The analyzer reconstructs
landings, reference departures and curves from raw records, and rejects missing
trials, input drift, false target geometry, nonfinite states and edited summaries.

## Highest-value continuation

| Stage | Deliverable | Advance only when |
| --- | --- | --- |
| Current | Motor control plus collision-world coyote experiment | Controls pass; original outcomes and failures are retained |
| Next | Separate buffer landing/rejump task and timestep checks | Buffer acceptance changes an actual obstacle outcome; 60/120/240 Hz differences are explained |
| Then | Rendered session capture for one fixed task | Frames, simulation events and measured input/display timestamps align within a stated tolerance |
| Human pilot | Balanced A/B sessions; responsiveness, fairness and preference questions | Players understand the task and missing-session handling works |
| Held-out validation | Freeze a predictor from automated metrics to human judgments | Evaluate on unseen participants and level families; compare against simple difficulty-only baselines |
| Generator feedback | Bounded parameter proposals, paired evaluation and human review | Predictions transfer to unseen variants without breaking gameplay or the 13 KB build gate |
| Algonaut preparation | Action/state/video feature ablations under the existing evaluation protocol | Actual rendered features generalize across held-out games; authorized neural evaluation remains separate |

Prioritize these gates over expanding the generator or training expensive agents.
A useful near-term claim is “a measured timing intervention improved this task
for these inputs,” followed by a human preference result. Universal optimal game
design is not an identifiable objective. Define the target players, task and
trade-off between accessibility, mastery and challenge before optimization.

Keep the existing Algonaut real-data baseline moving independently. These game
tasks can provide controlled representation diagnostics; they do not create
brain targets or establish competition performance. Before competition-specific
training, check the published rules and permitted data/model conditions.
