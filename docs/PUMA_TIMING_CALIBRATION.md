# Puma timing sensitivity calibration

## Question

Can a controlled measurement detect the grace windows implemented by the real
Puma movement motor, and distinguish a change in one window from the other?
This is a positive control for the measurement method, not evidence that a
particular tuning is more enjoyable or that a player will finish a level.

The fixture compiles the pinned game's actual C# Core sources with
`PumaTimingHost.cs`, calls `PumaMotor.Prepare`, and records each step's input,
imposed ground-contact flag, emitted event flags and vertical velocity. It does
not run Unity, collision resolution, camera motion, or a human controller. It
does not integrate positions. Its scope is explicitly
`imposed_contact_motor_calibration` and these records are not passed off as full
gameplay feature packets or neural observations.

## Frozen protocol

At 120 Hz, sweep integer input offsets from 0 through 24 ticks (0–200 ms).
Every condition uses a fresh motor. Execute two identity repeats of each
condition in a deterministic shuffled order: 25 offsets × two mechanisms × two
arms × two repeats = 200 trials and 100 distinct conditions.

| Mechanism | Contact/input intervention | Default arm | Narrow arm |
| --- | --- | --- | --- |
| Coyote time | Prime the grounded timer, impose airborne state, press after d steps | CoyoteSeconds = 0.11 | CoyoteSeconds = half a tick |
| Jump buffering | Press airborne, impose landing d steps later | BufferSeconds = 0.13 | BufferSeconds = half a tick |

The other tuning value retains its default in each comparison. Offset zero is
a grounded, on-time press. A narrow **positive** buffer retains on-time jumps;
setting BufferSeconds to zero would suppress even on-time jump processing in
this implementation and confound the intended timing manipulation.

Ground contact is assigned immediately before `Prepare`. The default windows
are away from integer tick boundaries, avoiding exact float-equality cases.
At this call boundary, the frozen mechanistic predictions are:

- Coyote default accepts offsets 0–13; narrow accepts only 0.
- Buffer default accepts offsets 0–15; narrow accepts only 0.
- Both repeat traces are identical, including measured vertical velocity.
- All other offsets produce no jump event. No jump occurs before the final step.

These predictions were frozen by reading the source before executing the sweep.
A pass establishes sensitivity to known motor behavior under this fixture.
It is not independent discovery of a new game-design principle. No confidence
interval or p-value is attached to enumerated deterministic conditions; identity
repeats are not independent players. Observed boundaries are quantized by the
8.33 ms timestep, and cannot measure continuous human response times.

## First measured result

The [first CI execution](https://github.com/sidhulyalkar/game-engine/actions/runs/34627042077)
at commit `0134e027f51eb48d8b45d62fd22de4a9f903e84e` passed all 200 trials,
with no prediction or identity-repeat mismatches. Its [measured summary](evidence/puma-timing-calibration.json)
retains the plan and trace fingerprints. Full step records are in that run's
`game-design-pilot-evidence` artifact.

| Window | Default: last accepted sampled offset | Narrow: accepted sampled offsets |
| --- | --- | --- |
| Coyote time | 13 ticks / 108.33 ms after leaving imposed ground | On-time only |
| Jump buffering | 15 ticks / 125 ms before imposed landing | On-time only |

This establishes the anticipated motor sensitivity at 120 Hz. It does not
establish that the same numerical tolerance is visible through collision,
rendering or human input, nor that wider windows improve player preference.

## Reproduce and inspect

The checked-in plan binds the exact source bytes, harness and analyzer before
CI executes it. With .NET 8 and the pinned Puma checkout:

```bash
game-engine puma-timing-run examples/studies/puma-timing-plan.json ../puma-platformer --out runs/puma-timing
game-engine puma-timing-analyze runs/puma-timing
```

For an explicitly new source/version, freeze a new plan first:

```bash
game-engine puma-timing-plan ../puma-platformer --out runs/new-timing-plan.json
```

Keep failed plans/results and distinguish revised predictions from the original
protocol. The analyzer derives curves from raw event records; it does not trust
the saved summary. Wrong trial counts/order, changed inputs, unintended tuning
changes, nonfinite state and changed provenance are rejected. Runtime failures
retain the plan and error, and produce no curves. A completed scientific control
failure retains the measured curves and mismatches.

CI retains `plan.json`, `trace.json` and `summary.json` inside the
`game-design-pilot-evidence` artifact. Hashes detect modification, but cannot
prove that a trace came from an honest execution if every record is deliberately
rewritten. Re-running the committed source in CI provides execution evidence.

## Next experimental boundary

1. Preserve this motor test as a fast sensitivity control.
2. Add an actual collision-world jump task with input offsets, testing whether
   the accepted-input window changes successful landing or obstacle clearance.
3. Capture rendered frames and measured input/display timestamps to compare
   internal acceptance with what a player sees.
4. Use balanced human A/B sessions to measure responsiveness, fairness and
   preference. Then test which automated metrics predict held-out preferences.

For Algonaut preparation, these controlled labels can eventually probe whether
video representations encode action timing and consequences. This fixture itself
contains neither rendered stimuli nor neural targets and cannot support that
claim yet.
