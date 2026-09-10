# Playtesting real game templates

This first implementation closes a bounded loop: execute a scenario, retain the
inputs and observations, diagnose contract failures, propose exact source edits,
retest a separate candidate, and compare evidence. It never promotes a candidate.

## Supported sources

| Template | Tested source baseline | Adapter | Limits |
| --- | --- | --- | --- |
| Unicorn Stampede | `2303fa2012a9388c8eaab2ea8063129b7a9e4d36` (v0.37) | Actual nine JavaScript runtime files, 60Hz, input events, drawing API stubs | Canvas pixels, audio output, compressed artifact, newer local HTML variants unqualified |
| Puma: Wildbound | `34cd95c70312a3beb88def0a2c3fcb4962a221b6` | Actual `Assets/Wildbound/Core/*.cs`, .NET 8, 120Hz | Unity rendering, Unity input routing, WebGL and menus unqualified |

Neither game is vendored or rewritten. Keep their checkouts outside the engine.
The test adapter, logs, and model prompts do not enter the 13KB game ZIP. Puma is
a Unity game and has no 13KB constraint. Use Unicorn's existing release builder
and packaged tests for its 13,312-byte release requirement.

## Quick start

Install Python 3.11+, Node.js 22, and .NET 8 for Puma. From this repository:

```bash
pip install -e .
game-engine playtest ../unicorn-stampede examples/playtests/unicorn-tutorial.json --out runs/tutorial
game-engine playtest-replay ../unicorn-stampede runs/tutorial --out runs/tutorial-replay
game-engine playtest ../puma-platformer examples/playtests/puma-movement.json --out runs/puma
game-engine playtest-suite unicorn-stampede ../unicorn-stampede --ticks 1200 --out runs/unicorn-worlds
game-engine playtest-suite puma-platformer ../puma-platformer --ticks 2400 --out runs/puma-worlds
```

Output directories must be new and outside the game source tree. Each completed
run includes `scenario.json`, `trace.json`, and `report.json`. Runtime errors write
an error report and exit nonzero. Missing .NET is an error, never a passing Puma
result. `passed_checks` only means this scenario met its explicit assertions and
trace validity checks. A completed replay can reproduce a failed scenario.

## Scenario contract

Scenarios contain a version, template, seed, setup, ordered actions and optional
expectations. Buttons are held throughout an action. Repeating a button in the
next action keeps it held; insert an action without it to release and press again.
Puma press/release edges are emitted once, while held jump and pounce state persist.
Pointer coordinates in Unicorn are normalized screen coordinates, not hidden
object targets. Inputs never accept executable code.

The maximum scenario budget is 18,000 ticks and 2,000 actions. Wall-clock timeout
defaults to 60 seconds per execution; Puma compilation has a separate timeout.
The stress suite uses seeded input variation in three worlds. It is not a planner,
beginner model, completion proof, or an estimate of player enjoyment.

`setup.entry=campaign` and `setup.world` are privileged scenario fixtures. They
can bypass unlocks. The tutorial example starts at the real menu instead. Puma
starts directly in its simulation. Reports must not describe these fixtures as
proof that a player discovered content through the UI.

Unicorn's date-based world seed and Math.random are fixed, save data starts fresh,
and all held inputs are replayed in a fresh context. Rendering functions execute
against stubs, preserving their random draws; pixel correctness is not tested.
Puma's authored core has no world RNG: the seed changes generated controller
inputs in a suite, not the authored map. Replay checks exact normalized JSON
traces and adapter hashes. Cross-platform float differences can legitimately
produce a replay mismatch; do not silently loosen equality.

## Diagnosis and repair

Contract failures (wrong phase, insufficient declared progress, death budget)
are separate from review findings. A stationary autonomous unicorn is flagged
after three seconds, excluding controlled, distracted, stunned, or captured
entities. This is a hypothesis for inspection, not an automatic game defect.
No progress under a stress controller does not prove an objective unreachable.
Unicorn reports `deaths=null` because the game has no player-life accounting;
use `metrics.captured` and `metrics.won` to inspect its actual loss mechanics.

Prepare a prompt without spending model tokens:

```bash
game-engine playtest-propose ../unicorn-stampede runs/tutorial --file src/herd.js --out runs/proposal
```

Add `--providers studio.local.json` to call the first enabled configured provider.
The provider receives the chosen 1–3 source files, explicit scenario, findings,
measurements, and preservation requirements. It returns a hypothesis and at most
three exact replacements. An empty edits list means it declined. Provider output
is saved as a proposal and is not executed by this command.

After reviewing the proposal:

```bash
game-engine playtest-apply ../unicorn-stampede runs/tutorial runs/proposal/proposal.json --out runs/candidate-1
game-engine playtest-compare runs/tutorial runs/candidate-1/evidence
```

Application verifies baseline fingerprints, restricts edits to manifested runtime
files, requires exact unique matches, copies only runtime files to a new candidate,
and repeats the same scenario. Tests and evaluators cannot be edited through this
interface. The candidate folder is a diagnostic source subset, not a distributable
game. Apply an accepted diff to a normal checkout for full regression and release
testing. A resolved finding does not override new failures. Even a clean comparison
returns `review_required`, never automatic merge or a fun score.

## Execution boundary

Run only trusted local game code and reviewed patches on your workstation.
`node:vm` and the .NET child process are **not security sandboxes**. The runner
removes inherited credentials, uses temporary working directories, limits
scenario length, and terminates timed-out process groups on POSIX. It does not
prevent arbitrary trusted-source code from reading files or using the network.
Do not automatically execute unreviewed model code here. A production autonomous
worker needs a disposable VM/container with network disabled, read-only source
mounts, memory/CPU/disk limits, and no host credentials. Output is checked against
a 32MB limit after execution; this is not a hard disk-quota enforcement mechanism.

## Verification

```bash
UNICORN_SOURCE=/absolute/path/unicorn-stampede PUMA_SOURCE=/absolute/path/puma-platformer pytest -q
```

The dedicated workflow pins both game commits, executes their existing regression
cases, runs all three worlds, checks replay, and uploads trace evidence. The local
unit suite also runs without pytest through `python -m unittest discover -s tests
-p test_playtesting.py`. It includes a deliberate no-op update mutation: the
baseline misses tutorial progress, an exact repair restores progress, and the
original faulty source remains unchanged. That demonstrates the repair plumbing,
not discovery of an actual bug in the user's game.

## Next stages

1. Rendered browser artifact adapter with real screenshots and input timing.
2. Unity PlayMode/WebGL adapter that checks visuals and UI routing separately.
3. Goal-directed and timing-limited controllers validated against real players.
4. Adaptive test allocation after reliable scenario coverage exists.
5. Equal-budget generation versus text-critique versus playtest-feedback study.

Keep frozen holdout scenarios and human comparisons separate from the mutation
loop. Do not let a successful heuristic test justify removing required mechanics.
